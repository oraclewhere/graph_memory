"""FastAPI 应用入口。"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="graph_memory", version="0.2.0")
app.include_router(router)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
def root() -> FileResponse:
    return FileResponse(str(STATIC_DIR / "notes.html"))


@app.get("/graph")
def graph_page() -> FileResponse:
    return FileResponse(str(STATIC_DIR / "index.html"))
