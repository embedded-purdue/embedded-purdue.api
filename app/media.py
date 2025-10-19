# api/media.py
from __future__ import annotations

import os
import re
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from fastapi import FastAPI, Request, HTTPException, Header, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, HttpUrl, ValidationError, field_validator

try:
    import redis.asyncio as redis  # optional persistence
except Exception:
    redis = None

app = FastAPI()

# --------------------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------------------
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN") or ""
ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN", "")
REDIS_URL = os.environ.get("REDIS_URL")

# Limits
MAX_FILES = int(os.environ.get("MEDIA_MAX_FILES", "10"))
MAX_FILE_SIZE = int(os.environ.get("MEDIA_MAX_FILE_SIZE", str(25 * 1024 * 1024)))     # 25MB
MAX_TOTAL_SIZE = int(os.environ.get("MEDIA_MAX_TOTAL_SIZE", str(100 * 1024 * 1024)))  # 100MB

# Allowed types/extensions
ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif", "image/svg+xml"}
ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".md", ".markdown"}

MEDIA_KEY = "media:list"

def _ext(name: str) -> str:
    parts = name.lower().rsplit(".", 1)
    return f".{parts[-1]}" if len(parts) == 2 else ""

def _is_markdown(name: str, mime: str) -> bool:
    e = _ext(name)
    return e in {".md", ".markdown"} or mime in {"text/markdown"}

# --------------------------------------------------------------------------------------
# Pydantic models
# --------------------------------------------------------------------------------------
class MediaFile(BaseModel):
    url: HttpUrl
    name: str = Field(min_length=1, max_length=512)
    type: str = Field(min_length=1, max_length=128)
    size: int = Field(ge=0, le=1_000_000_000)

    @field_validator("name")
    @classmethod
    def ext_allowed(cls, v: str) -> str:
        if _ext(v) not in ALLOWED_EXTENSIONS:
            raise ValueError(f"unsupported extension: {_ext(v) or '(none)'}")
        return v

    @field_validator("type")
    @classmethod
    def mime_allowed(cls, v: str) -> str:
        if v.startswith("image/"):
            # allow common images (browsers sometimes send image/jpg)
            if v not in ALLOWED_IMAGE_TYPES and v not in {"image/jpg"}:
                raise ValueError(f"unsupported image type: {v}")
        else:
            if v not in {"text/markdown", "text/plain", "application/octet-stream"}:
                raise ValueError(f"unsupported file type: {v}")
        return v


class MediaCreate(BaseModel):
    kind: str = Field(pattern=r"^(project|workshop|other)$")
    title: str = Field(min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=10_000)
    files: List[MediaFile] = Field(min_items=1, max_items=MAX_FILES)

    @field_validator("files")
    @classmethod
    def size_limits(cls, files: List[MediaFile]) -> List[MediaFile]:
        total = 0
        for f in files:
            total += f.size
            if f.size > MAX_FILE_SIZE:
                raise ValueError(f"{f.name} exceeds per-file limit ({MAX_FILE_SIZE} bytes)")
        if total > MAX_TOTAL_SIZE:
            raise ValueError(f"total upload size exceeds {MAX_TOTAL_SIZE} bytes")
        return files


class MediaItem(BaseModel):
    id: str
    kind: str
    title: str
    description: str | None
    files: List[MediaFile]
    markdownFiles: List[MediaFile]  # NEW: only the .md/.markdown files (if any)
    createdAt: str

# --------------------------------------------------------------------------------------
# CORS / Auth
# --------------------------------------------------------------------------------------
def cors_headers(origin: Optional[str]) -> Dict[str, str]:
    ok = bool(origin) and (ALLOWED_ORIGIN == "*" or origin == ALLOWED_ORIGIN)
    return {
        "Access-Control-Allow-Origin": origin if ok else ("*" if ALLOWED_ORIGIN == "*" else ""),
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

# --------------------------------------------------------------------------------------
# Storage (Redis or in-memory)
# --------------------------------------------------------------------------------------
class Storage:
    def __init__(self) -> None:
        self._mem: List[Dict[str, Any]] = []
        self._r = None

    async def init(self) -> None:
        if REDIS_URL and redis:
            self._r = redis.from_url(REDIS_URL, encoding="utf-8", decode_responses=True)

    async def add(self, item: Dict[str, Any]) -> None:
        # newest-first
        if self._r:
            import json as _json
            await self._r.lpush(MEDIA_KEY, _json.dumps(item))  # type: ignore[arg-type]
        else:
            self._mem.insert(0, item)

    async def list(
        self,
        kind: Optional[str],
        q: Optional[str],
        only_markdown: bool,
        limit: int,
        cursor: Optional[str],
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        if self._r:
            n = await self._r.llen(MEDIA_KEY)  # type: ignore[union-attr]
            start = int(cursor) if cursor and cursor.isdigit() else 0
            end = min(start + limit - 1, n - 1)
            raw = await self._r.lrange(MEDIA_KEY, start, end)  # type: ignore[union-attr]
            items: List[Dict[str, Any]] = []
            for it in raw:
                try:
                    import json as _json
                    obj = _json.loads(it) if isinstance(it, str) else it
                    if isinstance(obj, dict):
                        items.append(obj)
                except Exception:
                    continue
            items = _filter_and_search(items, kind, q, only_markdown)
            next_cursor = str(end + 1) if end + 1 < n else None
            return items, next_cursor
        else:
            items = list(self._mem)
            items = _filter_and_search(items, kind, q, only_markdown)
            index = 0
            if cursor:
                try:
                    createdAt, cid = cursor.split("|", 1)
                    index = next(
                        (i + 1 for i, it in enumerate(items) if it["createdAt"] == createdAt and it["id"] == cid),
                        0,
                    )
                except Exception:
                    index = 0
            sliced = items[index : index + limit]
            next_cur = None
            if len(items) > index + limit:
                last = sliced[-1]
                next_cur = f'{last["createdAt"]}|{last["id"]}'
            return sliced, next_cur


def _filter_and_search(
    items: List[Dict[str, Any]],
    kind: Optional[str],
    q: Optional[str],
    only_markdown: bool,
) -> List[Dict[str, Any]]:
    if kind:
        items = [it for it in items if it.get("kind") == kind]
    if only_markdown:
        items = [it for it in items if it.get("markdownFiles")]
    if q:
        pat = re.compile(re.escape(q), re.IGNORECASE)
        items = [
            it for it in items
            if pat.search(it.get("title", "")) or pat.search(it.get("description") or "")
        ]
    return items


storage = Storage()

@app.on_event("startup")
async def _startup():
    await storage.init()

# --------------------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------------------
@app.options("/{path:path}")
def options_any(request: Request, path: str):
    return JSONResponse({}, headers=cors_headers(request.headers.get("origin")))

@app.get("/api/media")
async def list_media(
    request: Request,
    kind: Optional[str] = Query(default=None, pattern="^(project|workshop|other)$"),
    q: Optional[str] = Query(default=None, min_length=1, max_length=100),
    limit: int = Query(default=20, ge=1, le=100),
    cursor: Optional[str] = Query(default=None),
    only: Optional[str] = Query(default=None),  # e.g. only=markdown
):
    """
    List media with optional filters:
      - kind: project|workshop|other
      - q: case-insensitive search in title/description
      - only=markdown: return only items with markdownFiles
      - limit/cursor: pagination
    """
    headers = cors_headers(request.headers.get("origin"))
    try:
        only_markdown = (only or "").lower() == "markdown"
        items, next_cursor = await storage.list(kind, q, only_markdown, limit, cursor)
        return JSONResponse({"items": items, "nextCursor": next_cursor}, headers=headers)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500, headers=headers)

@app.post("/api/media")
async def save_media(
    request: Request,
    authorization: str | None = Header(default=None),
):
    """
    JSON payload:
    {
      "kind": "project" | "workshop" | "other",
      "title": "Some Title",
      "description": "optional",
      "files": [
        {"url":"https://blob.vercel-storage.com/.../cover.png","name":"cover.png","type":"image/png","size":12345},
        {"url":"https://blob.vercel-storage.com/.../post.md","name":"post.md","type":"text/markdown","size":321}
      ]
    }

    - Markdown files are allowed **only** for kind = project | workshop.
    - Images allowed for any kind.
    """
    headers = cors_headers(request.headers.get("origin"))
    require_admin(authorization)

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # Validate schema
    try:
        payload = MediaCreate.model_validate(body)
    except ValidationError as ve:
        raise HTTPException(status_code=400, detail=ve.errors())

    # Enforce markdown policy: only project/workshop can include .md
    has_md = any(_is_markdown(f.name, f.type) for f in payload.files)
    if has_md and payload.kind not in {"project", "workshop"}:
        raise HTTPException(status_code=400, detail="Markdown allowed only for 'project' or 'workshop' kinds")

    markdown_files = [f for f in payload.files if _is_markdown(f.name, f.type)]

    item: Dict[str, Any] = MediaItem(
        id=str(uuid.uuid4()),
        kind=payload.kind,
        title=payload.title,
        description=payload.description or None,
        files=payload.files,
        markdownFiles=markdown_files,
        createdAt=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    ).model_dump()

    try:
        await storage.add(item)
        return JSONResponse(item, status_code=201, headers=headers)
    except Exception as e:
        return JSONResponse({"error": f"Save failed: {str(e)}"}, status_code=500, headers=headers)
