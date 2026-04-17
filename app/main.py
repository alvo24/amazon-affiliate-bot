"""FastAPI entrypoint: server-rendered dashboard + scheduler."""

from __future__ import annotations

import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, desc, select
from starlette.middleware.sessions import SessionMiddleware

from app.config import OVERRIDABLE_KEYS, SECRET_KEYS, get_effective_settings, get_settings
from app.db import engine, init_db
from app.models import Post, Product, RunLog, SettingOverride
from app.scheduler import get_scheduler, start_scheduler, stop_scheduler
from app.service import post_manual, run_once

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ARG001
    logging.basicConfig(
        level=get_settings().log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    init_db()
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(title="Amazon Affiliate Bot", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=get_settings().app_secret)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


# --------------------------------------------------------------------------- #
# Auth helpers
# --------------------------------------------------------------------------- #


def require_login(request: Request) -> None:
    if not request.session.get("authed"):
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            detail="login required",
            headers={"Location": "/login"},
        )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):  # noqa: ARG001
    if exc.status_code == status.HTTP_303_SEE_OTHER and "Location" in (exc.headers or {}):
        return RedirectResponse(url=exc.headers["Location"], status_code=303)
    raise exc


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #


@app.get("/login", response_class=HTMLResponse)
async def login_form(request: Request):
    return templates.TemplateResponse(request, "login.html", {"error": None})


@app.post("/login")
async def login(request: Request, password: str = Form(...)):
    settings = get_effective_settings()
    if secrets.compare_digest(password, settings.app_admin_password):
        request.session["authed"] = True
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(
        request, "login.html", {"error": "Invalid password"}, status_code=401
    )


@app.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, _: None = Depends(require_login)):
    settings = get_effective_settings()
    scheduler = get_scheduler()
    next_run = None
    if scheduler:
        job = scheduler.get_job("auto_post")
        if job and job.next_run_time:
            next_run = job.next_run_time.isoformat()

    with Session(engine) as session:
        recent_runs = session.exec(select(RunLog).order_by(desc(RunLog.started_at)).limit(10)).all()
        recent_posts = session.exec(select(Post).order_by(desc(Post.created_at)).limit(25)).all()
        product_count = len(session.exec(select(Product)).all())

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "settings": settings,
            "status": {
                "amazon_configured": settings.amazon_configured(),
                "facebook_configured": settings.facebook_configured(),
                "instagram_configured": settings.instagram_configured(),
                "pinterest_configured": settings.pinterest_configured(),
                "dry_run": settings.dry_run,
                "next_run": next_run,
                "cron": settings.post_schedule_cron,
                "timezone": settings.timezone,
                "enabled_platforms": settings.platform_list,
                "browse_nodes": settings.browse_node_list,
                "product_count": product_count,
            },
            "recent_runs": recent_runs,
            "recent_posts": recent_posts,
        },
    )


@app.get("/products", response_class=HTMLResponse)
async def products_page(request: Request, _: None = Depends(require_login)):
    with Session(engine) as session:
        products = session.exec(select(Product).order_by(desc(Product.fetched_at))).all()
    return templates.TemplateResponse(request, "products.html", {"products": products})


@app.post("/run-now")
async def run_now(_: None = Depends(require_login)):
    summary = await run_once()
    logger.info("Manual run complete: %s", summary)
    return RedirectResponse(url="/", status_code=303)


@app.get("/post-link", response_class=HTMLResponse)
async def post_link_form(request: Request, _: None = Depends(require_login)):
    settings = get_effective_settings()
    return templates.TemplateResponse(
        request,
        "post_link.html",
        {
            "settings": settings,
            "enabled_platforms": settings.platform_list,
            "result": None,
            "form": {"url": "", "caption": "", "image_url": "", "platforms": settings.platform_list},
            "error": None,
        },
    )


@app.post("/post-link", response_class=HTMLResponse)
async def post_link_submit(
    request: Request,
    _: None = Depends(require_login),
    url: str = Form(...),
    caption: str = Form(...),
    image_url: str = Form(""),
    platforms: list[str] | None = Form(default=None),  # noqa: B008
):
    settings = get_effective_settings()
    cleaned_url = url.strip()
    cleaned_caption = caption.strip()
    cleaned_image = image_url.strip() or None
    chosen = [p for p in (platforms or []) if p in settings.platform_list] or settings.platform_list

    form_state = {
        "url": cleaned_url,
        "caption": cleaned_caption,
        "image_url": cleaned_image or "",
        "platforms": chosen,
    }

    if not cleaned_url or not cleaned_caption:
        return templates.TemplateResponse(
            request,
            "post_link.html",
            {
                "settings": settings,
                "enabled_platforms": settings.platform_list,
                "result": None,
                "form": form_state,
                "error": "URL and caption are both required.",
            },
            status_code=400,
        )

    summary = await post_manual(
        affiliate_url=cleaned_url,
        caption=cleaned_caption,
        image_url=cleaned_image,
        platforms=chosen,
    )

    return templates.TemplateResponse(
        request,
        "post_link.html",
        {
            "settings": settings,
            "enabled_platforms": settings.platform_list,
            "result": summary,
            "form": form_state,
            "error": None,
        },
    )


@app.get("/settings", response_class=HTMLResponse)
async def settings_form(request: Request, _: None = Depends(require_login), saved: str = ""):
    settings = get_effective_settings()
    with Session(engine) as session:
        rows = session.exec(select(SettingOverride)).all()
    overrides = {r.key: r.value for r in rows}

    def current(key: str) -> str:
        val = overrides.get(key)
        if val is None:
            val = getattr(settings, key, "")
            val = "" if val is None else str(val)
        return val

    has_override = {k: k in overrides for k in OVERRIDABLE_KEYS}
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "settings": settings,
            "values": {k: current(k) for k in OVERRIDABLE_KEYS},
            "secret_keys": SECRET_KEYS,
            "has_override": has_override,
            "saved": saved,
        },
    )


@app.post("/settings")
async def settings_submit(request: Request, _: None = Depends(require_login)):
    form = await request.form()
    with Session(engine) as session:
        for key in OVERRIDABLE_KEYS:
            if key == "dry_run":
                new_val = "true" if form.get("dry_run") else "false"
            else:
                raw = form.get(key)
                if raw is None:
                    continue
                new_val = str(raw).strip()

            row = session.get(SettingOverride, key)
            if new_val == "":
                if row is not None:
                    session.delete(row)
                continue
            if row is None:
                session.add(SettingOverride(key=key, value=new_val))
            else:
                row.value = new_val
                session.add(row)
        session.commit()
    return RedirectResponse(url="/settings?saved=1", status_code=303)


@app.get("/api/status")
async def api_status(_: None = Depends(require_login)):
    settings = get_effective_settings()
    scheduler = get_scheduler()
    next_run = None
    if scheduler:
        job = scheduler.get_job("auto_post")
        if job and job.next_run_time:
            next_run = job.next_run_time.isoformat()

    return {
        "dry_run": settings.dry_run,
        "cron": settings.post_schedule_cron,
        "timezone": settings.timezone,
        "next_run": next_run,
        "amazon_configured": settings.amazon_configured(),
        "facebook_configured": settings.facebook_configured(),
        "instagram_configured": settings.instagram_configured(),
        "pinterest_configured": settings.pinterest_configured(),
        "enabled_platforms": settings.platform_list,
    }


@app.get("/healthz")
async def healthz():
    return {"ok": True}
