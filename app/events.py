# api/events.py
from __future__ import annotations

import os
from typing import Any, Dict, Optional
from datetime import datetime, timezone, timedelta
import re

from fastapi import FastAPI, Request, HTTPException, Header
from fastapi.responses import JSONResponse

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.auth.transport.requests import Request as GRequest
from google.oauth2.credentials import Credentials
from google.oauth2.service_account import Credentials as ServiceAccountCredentials

SCOPES = ["https://www.googleapis.com/auth/calendar"]

app = FastAPI()

CAL_ID = os.environ.get("GOOGLE_CALENDAR_ID", "primary")
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")


# ----------------- Infra helpers -----------------
def cors_headers(origin: Optional[str]) -> Dict[str, str]:
    allowed = os.environ.get("ALLOWED_ORIGIN", "")
    ok = bool(origin) and (allowed == "*" or origin == allowed)
    return {
        "Access-Control-Allow-Origin": origin if ok else ("*" if allowed == "*" else ""),
        "Vary": "Origin",
        "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type,Authorization",
        "Access-Control-Max-Age": "86400",
        "content-type": "application/json",
    }

def require_admin(authorization: Optional[str]) -> None:
    token = (authorization or "").removeprefix("Bearer ").strip()
    if not ADMIN_TOKEN or token != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")

def get_credentials() -> Credentials:
    # Prefer service account (best for Vercel)
    svc_email = os.environ.get("GOOGLE_CLIENT_EMAIL")
    svc_key = os.environ.get("GOOGLE_PRIVATE_KEY")
    if svc_email and svc_key:
        info = {
            "type": "service_account",
            "client_email": svc_email,
            "private_key": svc_key.replace("\\n", "\n"),
            "token_uri": "https://oauth2.googleapis.com/token",
        }
        return ServiceAccountCredentials.from_service_account_info(info, scopes=SCOPES)

    # Fallback: OAuth env (refresh token)
    cid, csec, rtok = (
        os.environ.get("GOOGLE_CLIENT_ID"),
        os.environ.get("GOOGLE_CLIENT_SECRET"),
        os.environ.get("GOOGLE_REFRESH_TOKEN"),
    )
    if cid and csec and rtok:
        creds = Credentials(
            token=None,
            refresh_token=rtok,
            client_id=cid,
            client_secret=csec,
            token_uri="https://oauth2.googleapis.com/token",
            scopes=SCOPES,
        )
        if not creds.valid:
            creds.refresh(GRequest())
        return creds

    # Local dev: token.json
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
        if not creds.valid and creds.refresh_token:
            creds.refresh(GRequest())
            try:
                with open("token.json", "w") as f:
                    f.write(creds.to_json())
            except Exception:
                pass
        return creds

    raise RuntimeError("No Google credentials available.")


def gcal_service():
    return build("calendar", "v3", credentials=get_credentials())


# ----------------- Event helpers -----------------
WEEKDAY_MAP = {
    "SU": "SU", "SUN": "SU", "SUNDAY": "SU",
    "MO": "MO", "MON": "MO", "MONDAY": "MO",
    "TU": "TU", "TUE": "TU", "TUESDAY": "TU",
    "WE": "WE", "WED": "WE", "WEDNESDAY": "WE",
    "TH": "TH", "THU": "TH", "THURSDAY": "TH",
    "FR": "FR", "FRI": "FR", "FRIDAY": "FR",
    "SA": "SA", "SAT": "SA", "SATURDAY": "SA",
}

def build_rrule(body: Dict[str, Any]) -> Optional[list[str]]:
    """
    Accept one of:
      - rrule: "RRULE:FREQ=WEEKLY;INTERVAL=1;BYDAY=MO,WE"
      - repeat: {
          "freq": "DAILY|WEEKLY|MONTHLY|YEARLY",
          "interval": 2,
          "byDay": ["MO","WE"] or ["mon","wed"],
          "byMonthDay": [1,15],
          "count": 10,
          "until": "2025-12-31T23:59:59Z" or "2025-12-31"
        }
    Returns a list like ["RRULE:..."] or None.
    """
    if "rrule" in body and body["rrule"]:
        s = str(body["rrule"]).strip()
        if not s.upper().startswith("RRULE:"):
            s = "RRULE:" + s
        return [s]

    rep = body.get("repeat")
    if not rep:
        return None

    parts = []
    freq = str(rep.get("freq", "")).upper()
    if freq not in {"DAILY", "WEEKLY", "MONTHLY", "YEARLY"}:
        raise HTTPException(status_code=400, detail="repeat.freq must be DAILY/WEEKLY/MONTHLY/YEARLY")
    parts.append(f"FREQ={freq}")

    if rep.get("interval"):
        parts.append(f"INTERVAL={int(rep['interval'])}")

    if rep.get("byDay"):
        by = []
        for d in rep["byDay"]:
            code = WEEKDAY_MAP.get(str(d).upper())
            if not code:
                raise HTTPException(status_code=400, detail=f"Invalid byDay value: {d}")
            by.append(code)
        if by:
            parts.append(f"BYDAY={','.join(by)}")

    if rep.get("byMonthDay"):
        days = [str(int(x)) for x in rep["byMonthDay"]]
        parts.append(f"BYMONTHDAY={','.join(days)}")

    if rep.get("count"):
        parts.append(f"COUNT={int(rep['count'])}")

    if rep.get("until"):
        raw = str(rep["until"]).strip()
        # Accept date-only (YYYY-MM-DD) or ISO datetime with/without seconds and with Z or offset
        try:
            # Date-only
            try:
                d = datetime.strptime(raw, "%Y-%m-%d")
                parts.append(f"UNTIL={d.strftime('%Y%m%d')}")
            except ValueError:
                # Datetime path: ensure it parses and convert to UTC
                iso = raw
                # Replace trailing Z with +00:00 for fromisoformat compatibility
                if iso.endswith("Z"):
                    iso = iso[:-1] + "+00:00"
                # If time portion lacks seconds (e.g., HH:MM or HH:MM+/-HH:MM), insert :00
                # Match patterns like YYYY-MM-DDTHH:MM(+ZZ:ZZ)? or ...THH:MM
                if re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}([+-]\d{2}:\d{2})?$", iso):
                    # Insert :00 at the right place (before timezone or end)
                    if "+" in iso[16:] or "-" in iso[16:]:
                        # Has timezone, insert seconds before zone
                        iso = re.sub(r"^(.*T\d{2}:\d{2})(?=[+-]\d{2}:\d{2}$)", r"\1:00", iso)
                    else:
                        iso = iso + ":00"
                dt = datetime.fromisoformat(iso)
                if dt.tzinfo is None:
                    # Assume naive means UTC
                    dt = dt.replace(tzinfo=timezone.utc)
                dt = dt.astimezone(timezone.utc)
                parts.append(f"UNTIL={dt.strftime('%Y%m%dT%H%M%SZ')}")
        except Exception:
            raise HTTPException(status_code=400, detail="repeat.until must be YYYY-MM-DD or ISO datetime")

    return [f"RRULE:{';'.join(parts)}"] if parts else None


def build_time_fields(body: Dict[str, Any]) -> tuple[dict, dict]:
    """
    Support either all-day:
      startDate: "2025-10-20", endDate: "2025-10-20"
    or date-time:
      startISO: "2025-10-20T09:00:00-04:00", endISO: "2025-10-20T10:00:00-04:00"
      timeZone: "America/New_York" (optional)
    """
    tz = body.get("timeZone")
    # All-day event handling: accept startDate and optional endDate.
    if body.get("startDate"):
        sd = str(body["startDate"]).strip()
        ed = str(body.get("endDate") or sd).strip()
        # Google requires end.date to be exclusive; if equal or earlier, bump end by +1 day
        try:
            sd_dt = datetime.strptime(sd, "%Y-%m-%d")
            ed_dt = datetime.strptime(ed, "%Y-%m-%d")
            if ed_dt <= sd_dt:
                ed_dt = sd_dt + timedelta(days=1)
                ed = ed_dt.strftime("%Y-%m-%d")
        except Exception:
            # If parsing fails, fall back to provided strings
            pass
        start = {"date": sd}
        end = {"date": ed}
        # All-day events cannot include timeZone in Google payload
        return start, end

    if not body.get("startISO") or not body.get("endISO"):
        raise HTTPException(status_code=400, detail="Provide startISO/endISO or startDate/endDate")

    start = {"dateTime": body["startISO"]}
    end = {"dateTime": body["endISO"]}
    if tz:
        start["timeZone"] = tz
        end["timeZone"] = tz
    return start, end


# ----------------- Routes -----------------
@app.options("/{path:path}")
def options_any(request: Request, path: str):
    return JSONResponse({}, headers=cors_headers(request.headers.get("origin")))

@app.get("/api/events")
def list_events(request: Request):
    headers = cors_headers(request.headers.get("origin"))
    try:
        service = gcal_service()
        now = datetime.now(timezone.utc).isoformat()
        result = (
            service.events()
            .list(
                calendarId=CAL_ID,
                timeMin=now,
                maxResults=50,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        items = result.get("items", [])
        data = [
            {
                "id": e.get("id"),
                "title": e.get("summary", "(untitled)"),
                "description": e.get("description", ""),
                "url": e.get("htmlLink", ""),
                "start": e.get("start", {}).get("dateTime") or e.get("start", {}).get("date"),
                "end": e.get("end", {}).get("dateTime") or e.get("end", {}).get("date"),
                "location": e.get("location", ""),
                "recurrence": e.get("recurrence", []),
                "attendees": e.get("attendees", []),
            }
            for e in items
        ]
        return JSONResponse(data, headers=headers)
    except HttpError as err:
        # Try to surface more detailed Google error info
        detail = None
        payload = {"error": str(err)}
        try:
            if hasattr(err, "content") and err.content:
                import json as _json
                detail = _json.loads(err.content.decode("utf-8"))
        except Exception:
            detail = None
        if detail:
            payload["detail"] = detail
        return JSONResponse(payload, status_code=500, headers=headers)

@app.post("/api/events")
async def create_event(request: Request, authorization: str | None = Header(default=None)):
    """
    Accepts flexible inputs and supports recurrence.

    Timed event:
    {
      "title": "Workshop",
      "description": "Intro",
      "startISO": "2025-10-20T09:00:00-04:00",
      "endISO": "2025-10-20T10:00:00-04:00",
      "timeZone": "America/New_York",    // optional
      "location": "WALC 1018",
      "attendees": [{"email":"a@x.com"}],
      "reminders": {"useDefault": false, "overrides":[{"method":"email","minutes":1440}]},
      "url": "https://register.example.com",
      "repeat": { "freq":"WEEKLY", "interval":1, "byDay":["MO"], "count":6 }  // OR "rrule":"RRULE:FREQ=WEEKLY;BYDAY=MO;COUNT=6"
    }

    All-day:
    {
      "title":"Hackday",
      "startDate":"2025-10-25",
      "endDate":"2025-10-26"
    }
    """
    headers = cors_headers(request.headers.get("origin"))
    require_admin(authorization)

    body = await request.json()
    if not body.get("title"):
        raise HTTPException(status_code=400, detail="title is required")

    # Build time fields
    start, end = build_time_fields(body)

    # Description + optional URL append
    desc = body.get("description") or ""
    if body.get("url"):
        desc = f"{desc}\n\nMore info: {body['url']}".strip()

    # Recurrence
    recurrence = build_rrule(body)

    event_payload: Dict[str, Any] = {
        "summary": body["title"],
        "location": body.get("location"),
        "description": desc,
        "start": start,
        "end": end,
    }
    if recurrence:
        event_payload["recurrence"] = recurrence
    if body.get("attendees"):
        event_payload["attendees"] = body["attendees"]
    if body.get("reminders"):
        event_payload["reminders"] = body["reminders"]

    try:
        service = gcal_service()
        created = service.events().insert(calendarId=CAL_ID, body=event_payload).execute()
        return JSONResponse(
            {"id": created.get("id"), "htmlLink": created.get("htmlLink")},
            status_code=201,
            headers=headers,
        )
    except HttpError as err:
        # Surface Google error details if available
        payload = {"error": str(err)}
        try:
            if hasattr(err, "content") and err.content:
                import json as _json
                detail = _json.loads(err.content.decode("utf-8"))
                if detail:
                    payload["detail"] = detail
        except Exception:
            pass
        return JSONResponse(payload, status_code=500, headers=headers)
