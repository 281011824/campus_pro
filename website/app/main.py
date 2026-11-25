"""
班主任工作台 Web 入口（单体版）。

FastAPI 直接 import tasks.head_teacher_workbench 业务模块，
不再经过 Redis 队列中转，也不需要独立 worker 进程。
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, ORJSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from loguru import logger

from app import APP_DIR, api, middleware
from app.api.v1 import share as share_api
from app.api.v1 import student_family as family_api
from app.initializer import g
from app.services import deyu_auth, inspector_auth, student_auth, wecom_oauth
from tasks.domain.growth import (datadomains, growth_archive)
from tasks.domain.identity import (accounts, bindings, classes, org)
from tasks.shared import db
from tasks.modules.head_teacher import assistant
from tasks.modules.leader import admins
from tasks.modules.supervisor import (dorms, inspection)
from tasks.modules.head_teacher import (moral_criteria, roster, seating)
from tasks.modules.student import student_accounts

# 禁用第三方库的 INFO 及以下级别日志
for _name in (
    "websockets",
    "uvicorn",
    "uvicorn.error",
    "uvicorn.access",
    "asyncio",
    "multiprocessing",
):
    logging.getLogger(_name).setLevel(logging.WARNING)

g.setup()

openapi_url = "/openapi.json"
docs_url = "/docs"
redoc_url = "/redoc"
if g.config.APP_DISABLE_DOCS is True:
    openapi_url, docs_url, redoc_url = None, None, None


@asynccontextmanager
async def lifespan(xapp: FastAPI):
    logger.info(f"Application env '{g.config.APP_ENV}'")
    logger.info(f"Application yaml '{g.config.YAML_PATH.name}'")
    logger.info(f"Application title '{g.config.APP_TITLE}'")
    logger.info(f"Application version '{g.config.APP_VERSION}'")
    # 初始化业务层：SQLite 建表 + 通讯录同步 + 数据域建表/演示数据
    db.init_db()
    info = org.sync_directory()
    datadomains.init()
    moral_criteria.init()
    roster.init()
    growth_archive.init()
    seating.init()
    accounts.init()
    bindings.init()
    admins.init()
    classes.init()
    dorms.init()
    student_accounts.init()
    assistant.init()
    inspection.init()
    logger.info(f"SQLite initialized · posts={info['posts']} persons={len(org.persons())}")
    logger.info("Application server running (monolithic mode, no Redis needed)")
    yield
    logger.info("Application server shutdown")


templates = Jinja2Templates(directory=str(APP_DIR / "templates"))

app = FastAPI(
    title=g.config.APP_TITLE,
    summary=g.config.APP_SUMMARY,
    description=g.config.APP_DESCRIPTION,
    version=g.config.APP_VERSION,
    debug=g.config.APP_DEBUG,
    openapi_url=openapi_url,
    docs_url=docs_url,
    redoc_url=redoc_url,
    lifespan=lifespan,
    default_response_class=ORJSONResponse,
)

# 分享与家长端路由显式注册（两模块标记 _active=False，避免与 api.register_routers 重复）
app.include_router(share_api.router, prefix="/api/v1", tags=["share"])
app.include_router(family_api.router, prefix="/api/v1", tags=["family"])


@app.get("/")
async def index(request: Request):
    """根路径：已启用登录时先进登录页，否则直接进入工作台。"""
    session_user = wecom_oauth.read_session(
        request.cookies.get(wecom_oauth.SESSION_COOKIE, ""),
    )
    if not session_user and (
        g.config.LOCAL_LOGIN_USERS or wecom_oauth.is_enabled()
    ):
        return RedirectResponse("/api/v1/login", status_code=302)
    if session_user and admins.is_active_admin(session_user):
        return RedirectResponse("/api/admin", status_code=302)
    if session_user and deyu_auth.is_deyu_account(session_user):
        return RedirectResponse("/api/deyu", status_code=302)
    if session_user and inspector_auth.is_inspector_account(session_user):
        return RedirectResponse("/api/inspector", status_code=302)
    if session_user and student_auth.is_student_account(session_user):
        return RedirectResponse("/api/student", status_code=302)
    return RedirectResponse("/api/head_teacher_workbench", status_code=302)


@app.get("/healthz")
async def healthz():
    """进程存活探针，不代表后台 worker 可用。"""
    return {"app": g.config.APP_TITLE, "status": "ok"}


@app.get("/api/head_teacher_workbench")
async def head_teacher_workbench_page(request: Request):
    # 启用登录后，未登录直接进登录页，避免页面骨架能开、接口全 401 卡在“加载中”
    session_user = wecom_oauth.read_session(
        request.cookies.get(wecom_oauth.SESSION_COOKIE, ""),
    )
    if not session_user and wecom_oauth.auth_required():
        return RedirectResponse(
            "/api/v1/login?next=/api/head_teacher_workbench", status_code=302,
        )
    if (
        session_user
        and not admins.is_active_admin(session_user)
        and deyu_auth.is_deyu_account(session_user)
    ):
        return RedirectResponse("/api/deyu", status_code=302)
    return templates.TemplateResponse(
        request, "head_teacher_workbench/index.html", {"request": request},
    )


@app.get("/api/admin")
async def admin_page(request: Request):
    """后台管理台页面：未登录跳登录页；已登录但非管理员回工作台（避免骨架可见、数据全 403）。"""
    session_user = wecom_oauth.read_session(
        request.cookies.get(wecom_oauth.SESSION_COOKIE, ""),
    )
    if not session_user and wecom_oauth.auth_required():
        return RedirectResponse("/api/v1/login?next=/api/admin", status_code=302)
    if session_user and not admins.is_active_admin(session_user):
        if deyu_auth.is_deyu_account(session_user):
            return RedirectResponse("/api/deyu", status_code=302)
        return RedirectResponse("/api/head_teacher_workbench", status_code=302)
    return templates.TemplateResponse(
        request, "admin/index.html", {"request": request},
    )


@app.get("/api/deyu")
async def deyu_page(request: Request):
    """政教处工作台页面：未登录跳登录页；已登录但非政教处/管理员回各自首页。"""
    session_user = wecom_oauth.read_session(
        request.cookies.get(wecom_oauth.SESSION_COOKIE, ""),
    )
    if not session_user and wecom_oauth.auth_required():
        return RedirectResponse("/api/v1/login?next=/api/deyu", status_code=302)
    if session_user and not deyu_auth.current_deyu(request):
        if admins.is_active_admin(session_user):
            return RedirectResponse("/api/admin", status_code=302)
        return RedirectResponse("/api/head_teacher_workbench", status_code=302)
    return templates.TemplateResponse(
        request, "deyu/index.html", {"request": request},
    )


@app.get("/api/inspector")
async def inspector_page(request: Request):
    """教官 / 寝管巡查页：未登录跳登录页；已登录但无权限回各自首页。"""
    session_user = wecom_oauth.read_session(
        request.cookies.get(wecom_oauth.SESSION_COOKIE, ""),
    )
    if not session_user and wecom_oauth.auth_required():
        return RedirectResponse("/api/v1/login?next=/api/inspector", status_code=302)
    if session_user and not inspector_auth.current_inspector(request):
        if admins.is_active_admin(session_user):
            return RedirectResponse("/api/admin", status_code=302)
        if deyu_auth.is_deyu_account(session_user):
            return RedirectResponse("/api/deyu", status_code=302)
        return RedirectResponse("/api/head_teacher_workbench", status_code=302)
    return templates.TemplateResponse(
        request, "inspector/index.html", {"request": request},
    )


@app.get("/api/student")
async def student_page(request: Request):
    """学生个人门户：未登录跳登录页；非学生回各自首页。"""
    session_user = wecom_oauth.read_session(
        request.cookies.get(wecom_oauth.SESSION_COOKIE, ""),
    )
    if not session_user and wecom_oauth.auth_required():
        return RedirectResponse("/api/v1/login?next=/api/student", status_code=302)
    if session_user and not student_auth.is_student_account(session_user):
        if admins.is_active_admin(session_user):
            return RedirectResponse("/api/admin", status_code=302)
        if deyu_auth.is_deyu_account(session_user):
            return RedirectResponse("/api/deyu", status_code=302)
        if inspector_auth.is_inspector_account(session_user):
            return RedirectResponse("/api/inspector", status_code=302)
        return RedirectResponse("/api/head_teacher_workbench", status_code=302)
    return templates.TemplateResponse(
        request, "student/index.html", {"request": request},
    )


@app.get("/api/family/login")
async def family_login_page(request: Request):
    """家长登录页（公开）。"""
    return templates.TemplateResponse(
        request, "student/family.html", {"request": request, "mode": "login", "authed": False},
    )


@app.get("/api/family")
async def family_page(request: Request):
    """家长端：无有效家长会话一律回登录页。"""
    if not student_auth.current_parent(request):
        return RedirectResponse("/api/family/login", status_code=302)
    return templates.TemplateResponse(
        request, "student/family.html", {"request": request, "mode": "home", "authed": True},
    )


@app.get("/s/{code}")
async def share_view_page(request: Request, code: str):
    """成长分享公开只读页（码由页面自行校验）。"""
    return templates.TemplateResponse(
        request, "student/share_view.html", {"request": request, "code": code},
    )


@app.get("/favicon.ico")
async def favicon():
    return FileResponse(str(APP_DIR / "static" / "favicon.ico"))


app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")

middleware.register_middlewares(app)
api.register_routers(app)
