# api/health.py
from fastapi import FastAPI
from fastapi.responses import JSONResponse

app = FastAPI()
@app.get("/api/health")
def health():
    return JSONResponse({"ok": True}, headers={"content-type": "application/json"})
