"""FastAPI 应用入口。"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.admin_routes import router as admin_router
from app.api.auth_routes import router as auth_router
from app.api.routes import router
from app.api.user_routes import router as user_router
from app.services.auth import SessionLocal, create_initial_admin, init_db

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="graph_memory", version="0.3.0")
app.include_router(router)
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(user_router)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.on_event("startup")
def startup():
    """应用启动时初始化数据库和创建初始管理员。"""
    try:
        init_db()
        # 创建初始管理员（如果不存在）
        db = SessionLocal()
        try:
            create_initial_admin(db)
        finally:
            db.close()
    except Exception as e:
        # MySQL 可能还没启动，不阻塞应用启动
        print(f"Warning: MySQL initialization failed: {e}")


@app.get("/")
def root() -> FileResponse:
    return FileResponse(str(STATIC_DIR / "notes.html"))


@app.get("/graph")
def graph_page() -> FileResponse:
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/login")
def login_page() -> FileResponse:
    return FileResponse(str(STATIC_DIR / "login.html"))


@app.get("/profile")
def profile_page() -> FileResponse:
    return FileResponse(str(STATIC_DIR / "profile.html"))
