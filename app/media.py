# api/media.py
from __future__ import annotations

import os
import re
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from fastapi import FastAPI, Request, HTTPException, Header, Query, File, UploadFile, Form
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, HttpUrl, ValidationError, field_validator

try:
    import redis.asyncio as redis  # optional persistence
except Exception:
    redis = None

try:
    import httpx  # for Vercel Blob uploads
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False

app = FastAPI()

# --------------------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------------------
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN") or ""
ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN", "")
REDIS_URL = os.environ.get("REDIS_URL")
VERCEL_BLOB_TOKEN = os.environ.get("BLOB_READ_WRITE_TOKEN") or ""  # Vercel Blob Storage token

# GitHub direct-commit config (optional alternative to Vercel Blob)
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN") or ""
GITHUB_REPO = os.environ.get("GITHUB_REPO", "embedded-purdue/embedded-purdue.github.io")
GITHUB_BASE_BRANCH = os.environ.get("GITHUB_BASE_BRANCH", "main")
GITHUB_MEDIA_ROOT = os.environ.get("GITHUB_MEDIA_ROOT", "public/projects")

# Limits
MAX_FILES = int(os.environ.get("MEDIA_MAX_FILES", "10"))
MAX_FILE_SIZE = int(os.environ.get("MEDIA_MAX_FILE_SIZE", str(25 * 1024 * 1024)))     # 25MB
MAX_TOTAL_SIZE = int(os.environ.get("MEDIA_MAX_TOTAL_SIZE", str(100 * 1024 * 1024)))  # 100MB

"""Allowed MIME and extensions
We validate both extension and type (loosely for text/*) to support a wide range of media:
- Images: png, jpg, jpeg, webp, gif, svg
- Video: mp4, webm
- Docs: pdf
- Data: csv, txt, log, json, yaml, yml, toml
- Code: ts, tsx, js, jsx, py, c, h, cpp, hpp, ino, rs, go, java, kt, swift, sh, bash, zsh, css, scss, md, mdx
- HTML: html, htm
"""
ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif", "image/svg+xml"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}
VIDEO_EXTENSIONS = {".mp4", ".webm"}
DOC_EXTENSIONS = {".pdf"}
DATA_EXTENSIONS = {".csv", ".txt", ".log", ".json", ".yaml", ".yml", ".toml"}
CODE_EXTENSIONS = {
    ".ts", ".tsx", ".js", ".jsx", ".py", ".c", ".h", ".cpp", ".hpp", ".ino",
    ".rs", ".go", ".java", ".kt", ".swift", ".sh", ".bash", ".zsh", ".css", ".scss",
    ".md", ".markdown", ".mdx",
}
HTML_EXTENSIONS = {".html", ".htm"}

ALLOWED_EXTENSIONS = (
    IMAGE_EXTENSIONS
    | VIDEO_EXTENSIONS
    | DOC_EXTENSIONS
    | DATA_EXTENSIONS
    | CODE_EXTENSIONS
    | HTML_EXTENSIONS
)

MEDIA_KEY = "media:list"

def _ext(name: str) -> str:
    parts = name.lower().rsplit(".", 1)
    return f".{parts[-1]}" if len(parts) == 2 else ""

def _is_markdown(name: str, mime: str) -> bool:
    e = _ext(name)
    return e in {".md", ".markdown"} or mime in {"text/markdown"}

def _mime_is_allowed(mime: str) -> bool:
    # Images: specific whitelist (browsers sometimes send image/jpg)
    if mime.startswith("image/"):
        return mime in ALLOWED_IMAGE_TYPES or mime in {"image/jpg"}
    # Videos: mp4, webm only
    if mime in {"video/mp4", "video/webm"} or mime.startswith("video/") and mime.split("/", 1)[1] in {"mp4", "webm"}:
        return True
    # Text: allow any text/* (markdown, html, css, csv, shell, source, etc.)
    if mime.startswith("text/"):
        return True
    # Common application types for docs/data/code
    if mime in {
        "application/pdf",
        "application/json",
        "application/javascript",
        "application/x-yaml",
        "application/yaml",
        "application/toml",
        "application/octet-stream",
    }:
        return True
    return False

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
        if not _mime_is_allowed(v):
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


@app.post("/api/media/upload")
async def upload_media(
    request: Request,
    kind: str = Form(...),
    title: str = Form(...),
    description: str = Form(default=""),
    files: List[UploadFile] = File(...),
    authorization: str | None = Header(default=None),
):
    """
    Direct file upload endpoint using multipart/form-data
    
    Form fields:
    - kind: project | workshop | other
    - title: Title for the media item
    - description: Optional description
    - files: Multiple files (images and/or markdown)
    
    Uploads files to Vercel Blob Storage and creates media item.
    Supported files include images (png,jpg,jpeg,webp,gif,svg), videos (mp4,webm),
    docs (pdf), html (html,htm), code (ts,tsx,js,jsx,py,c,cpp,ino,rs,go,java,kt,swift,sh,bash,zsh,css,scss,md,mdx),
    and data (csv,txt,log,json,yaml,yml,toml).
    """
    headers = cors_headers(request.headers.get("origin"))
    require_admin(authorization)
    
    # Validate inputs
    if kind not in {"project", "workshop", "other"}:
        raise HTTPException(status_code=400, detail="kind must be project, workshop, or other")
    
    if not title or len(title) > 200:
        raise HTTPException(status_code=400, detail="title must be 1-200 characters")
    
    if len(files) == 0 or len(files) > MAX_FILES:
        raise HTTPException(status_code=400, detail=f"Must upload 1-{MAX_FILES} files")
    
    if not VERCEL_BLOB_TOKEN:
        raise HTTPException(status_code=500, detail="Vercel Blob Storage not configured. Set BLOB_READ_WRITE_TOKEN")
    
    if not HTTPX_AVAILABLE:
        raise HTTPException(status_code=500, detail="httpx library not available for uploads")
    
    # Upload files to Vercel Blob
    uploaded_files = []
    total_size = 0
    
    try:
        async with httpx.AsyncClient() as client:
            for file in files:
                # Read file content
                content = await file.read()
                file_size = len(content)
                
                # Check size limits
                if file_size > MAX_FILE_SIZE:
                    raise HTTPException(
                        status_code=400,
                        detail=f"{file.filename} exceeds {MAX_FILE_SIZE} bytes"
                    )
                
                total_size += file_size
                if total_size > MAX_TOTAL_SIZE:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Total upload size exceeds {MAX_TOTAL_SIZE} bytes"
                    )
                
                # Validate extension
                ext = _ext(file.filename or "")
                if ext not in ALLOWED_EXTENSIONS:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Unsupported extension: {ext or '(none)'}"
                    )

                # Validate mime type broadly (images/videos specific, text/* allowed, common application/* allowed)
                if not _mime_is_allowed(file.content_type or "application/octet-stream"):
                    raise HTTPException(
                        status_code=400,
                        detail=f"Unsupported content-type: {file.content_type}"
                    )
                
                # Upload to Vercel Blob
                # https://vercel.com/docs/storage/vercel-blob/using-blob-sdk
                blob_response = await client.post(
                    f"https://blob.vercel-storage.com",
                    headers={
                        "authorization": f"Bearer {VERCEL_BLOB_TOKEN}",
                        "x-content-type": file.content_type or "application/octet-stream",
                    },
                    params={
                        "filename": file.filename,
                    },
                    content=content,
                )
                
                if blob_response.status_code != 200:
                    raise HTTPException(
                        status_code=500,
                        detail=f"Blob upload failed for {file.filename}: {blob_response.text}"
                    )
                
                blob_data = blob_response.json()
                
                uploaded_files.append(
                    MediaFile(
                        url=blob_data["url"],
                        name=file.filename or "unnamed",
                        type=file.content_type or "application/octet-stream",
                        size=file_size,
                    )
                )
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")
    
    # Create media item
    markdown_files = [f for f in uploaded_files if _is_markdown(f.name, f.type)]
    
    # Enforce markdown policy
    if markdown_files and kind not in {"project", "workshop"}:
        raise HTTPException(
            status_code=400,
            detail="Markdown files only allowed for 'project' or 'workshop' kinds"
        )
    
    item: Dict[str, Any] = MediaItem(
        id=str(uuid.uuid4()),
        kind=kind,
        title=title,
        description=description or None,
        files=uploaded_files,
        markdownFiles=markdown_files,
        createdAt=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    ).model_dump()
    
    try:
        await storage.add(item)
        return JSONResponse(item, status_code=201, headers=headers)
    except Exception as e:
        return JSONResponse({"error": f"Save failed: {str(e)}"}, status_code=500, headers=headers)


@app.post("/api/media/upload-gh")
async def upload_media_to_github(
    request: Request,
    projectSlug: str = Form(...),
    title: str = Form(...),
    description: str = Form(default=""),
    files: List[UploadFile] = File(...),
    authorization: str | None = Header(default=None),
):
    """
    Upload files directly into the website repository via GitHub Contents API.

    This avoids external storage. The endpoint will:
      1) Create a new branch from GITHUB_BASE_BRANCH
      2) Commit uploaded files under GITHUB_MEDIA_ROOT/<projectSlug>/
      3) Open a Pull Request back to GITHUB_BASE_BRANCH

    Requirements:
      - GITHUB_TOKEN env var with repo content and PR write permissions
      - httpx installed
      - Branch protection may require manual review of the PR
    """
    headers = cors_headers(request.headers.get("origin"))
    # require_admin(authorization)

    if not HTTPX_AVAILABLE:
        raise HTTPException(status_code=500, detail="httpx library not available for GitHub uploads")
    if not GITHUB_TOKEN:
        raise HTTPException(status_code=500, detail="GITHUB_TOKEN not configured on the API server")

    # sanitize slug/path
    slug = re.sub(r"[^a-z0-9-_]", "-", projectSlug.lower()).strip("-")
    if not slug:
        raise HTTPException(status_code=400, detail="Invalid projectSlug")

    if len(files) == 0 or len(files) > MAX_FILES:
        raise HTTPException(status_code=400, detail=f"Must upload 1-{MAX_FILES} files")

    total_size = 0
    to_commit: List[Tuple[str, bytes, str]] = []  # (path, content, mime)

    for file in files:
        content = await file.read()
        size = len(content)
        ext = _ext(file.filename or "")

        if ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(status_code=400, detail=f"Unsupported extension: {ext or '(none)'}")
        if not _mime_is_allowed(file.content_type or "application/octet-stream"):
            raise HTTPException(status_code=400, detail=f"Unsupported content-type: {file.content_type}")
        if size > MAX_FILE_SIZE:
            raise HTTPException(status_code=400, detail=f"{file.filename} exceeds {MAX_FILE_SIZE} bytes")
        total_size += size
        if total_size > MAX_TOTAL_SIZE:
            raise HTTPException(status_code=400, detail=f"Total upload size exceeds {MAX_TOTAL_SIZE} bytes")

        safe_name = re.sub(r"[^A-Za-z0-9._-]", "-", file.filename or "file")
        rel_path = f"{GITHUB_MEDIA_ROOT}/{slug}/{safe_name}"
        to_commit.append((rel_path, content, file.content_type or "application/octet-stream"))

    branch = f"media/{slug}/{int(time.time())}"
    repo_api = f"https://api.github.com/repos/{GITHUB_REPO}"
    auth_hdr = {"authorization": f"Bearer {GITHUB_TOKEN}", "accept": "application/vnd.github+json"}

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # 1) Get base branch SHA
            ref_res = await client.get(f"{repo_api}/git/ref/heads/{GITHUB_BASE_BRANCH}", headers=auth_hdr)
            if ref_res.status_code != 200:
                raise HTTPException(status_code=500, detail=f"Failed to get base ref: {ref_res.text}")
            base_sha = ref_res.json()["object"]["sha"]

            # 2) Create new branch
            create_ref = await client.post(
                f"{repo_api}/git/refs",
                headers=auth_hdr,
                json={"ref": f"refs/heads/{branch}", "sha": base_sha},
            )
            if create_ref.status_code not in (200, 201):
                # If branch exists, continue
                if create_ref.status_code != 422:
                    raise HTTPException(status_code=500, detail=f"Failed to create branch: {create_ref.text}")

            # 3) Commit each file (PUT contents)
            for rel_path, content, _mime in to_commit:
                import base64

                b64 = base64.b64encode(content).decode("ascii")
                put_res = await client.put(
                    f"{repo_api}/contents/{rel_path}",
                    headers=auth_hdr,
                    json={
                        "message": f"chore(media): add {rel_path} for {slug}",
                        "content": b64,
                        "branch": branch,
                    },
                )
                if put_res.status_code not in (200, 201):
                    raise HTTPException(status_code=500, detail=f"Failed to commit {rel_path}: {put_res.text}")

            # 4) Open PR
            pr_title = f"Add media for {slug}: {title}"
            pr_body = (description or "").strip() or "Automated media upload."
            pr_res = await client.post(
                f"{repo_api}/pulls",
                headers=auth_hdr,
                json={
                    "title": pr_title,
                    "head": branch,
                    "base": GITHUB_BASE_BRANCH,
                    "body": pr_body,
                    "maintainer_can_modify": True,
                },
            )
            if pr_res.status_code not in (200, 201):
                raise HTTPException(status_code=500, detail=f"Failed to create PR: {pr_res.text}")
            pr = pr_res.json()

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"GitHub upload failed: {str(e)}")

    # Build a minimal item record mirroring /api/media so the UI can display immediately if desired
    web_urls = [f"https://raw.githubusercontent.com/{GITHUB_REPO}/{branch}/{p}" for p, _, _ in to_commit]
    item = {
        "id": str(uuid.uuid4()),
        "kind": "project",
        "title": title,
        "description": description or None,
        "files": [
            {
                "url": u,
                "name": p.split("/")[-1],
                "type": "application/octet-stream",
                "size": len(c),
            }
            for (p, c, _m), u in zip(to_commit, web_urls)
        ],
        "markdownFiles": [],
        "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "pullRequestUrl": pr.get("html_url"),
        "branch": branch,
    }

    return JSONResponse(item, status_code=201, headers=headers)
