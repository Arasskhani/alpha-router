"""Render Usage & Activity pages to PDF via headless Chromium (Playwright)."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from urllib.parse import urlencode, urlparse, urlunparse

from app.services.rbac import is_admin_panel_role, normalize_role_slug

logger = logging.getLogger(__name__)

ACTIVITY_PDF_HIDE_CSS = """
.sidebar,
.sidebar-flyout,
.sidebar-peek-rail,
.app-topbar,
.read-only-banner,
.activity-toolbar,
.activity-back,
.activity-expand-btn,
.activity-filters,
.activity-menu-wrap,
.modal-overlay,
.activity-export-status,
.activity-page .error,
.activity-page .muted {
  display: none !important;
}
html,
body,
#root,
.layout,
.main-column,
.content,
.content:has(.activity-page),
.content--dashboard:has(.activity-page) {
  overflow: visible !important;
  height: auto !important;
  max-height: none !important;
  min-height: 0 !important;
}
body:not(.login-route) {
  overflow: visible !important;
  height: auto !important;
}
.layout {
  display: block !important;
}
.main-column {
  width: 100% !important;
}
.content {
  padding: 0 !important;
}
.activity-page {
  max-width: none !important;
}
"""


class ActivityPdfError(Exception):
    """PDF capture failed."""


def _frontend_base_url() -> str:
    """Prefer 127.0.0.1 over localhost (Windows IPv6 issues in headless browsers)."""
    base = get_settings().frontend_url.rstrip("/")
    parsed = urlparse(base)
    host = parsed.hostname or "127.0.0.1"
    if host.lower() == "localhost":
        host = "127.0.0.1"
    port = parsed.port
    netloc = f"{host}:{port}" if port else host
    return urlunparse(parsed._replace(netloc=netloc))


def build_activity_frontend_url(
    *,
    scope: str,
    user_role: str,
    period: str,
    prompts_period: str | None,
    timezone: str,
    group_by: str = "model",
    model_id: str | None = None,
    username: str | None = None,
    app: str | None = None,
    response_status: str | None = None,
    user_id: int | None = None,
    group_id: int | None = None,
    connection_id: int | None = None,
    api_key_id: int | None = None,
) -> str:
    pp = prompts_period or ("day" if period not in ("day", "week", "month") else period)
    if pp not in ("day", "week", "month"):
        pp = "week"

    params: dict[str, str] = {
        "period": period,
        "promptsPeriod": pp,
        "tz": timezone,
        "exportMode": "pdf",
    }
    if scope == "service":
        params["groupBy"] = group_by
        if model_id:
            params["model"] = model_id
        if username:
            params["user"] = username
        if app:
            params["app"] = app
        if response_status in ("success", "fail"):
            params["status"] = response_status
    elif model_id:
        params["model"] = model_id

    if scope == "service":
        path = "/admin"
    elif scope == "mine":
        path = "/admin/my-activity" if is_admin_panel_role(normalize_role_slug(user_role)) else "/app/my-activity"
    elif scope == "user":
        path = f"/admin/users/{user_id}/activity"
    elif scope == "group":
        path = f"/admin/groups/{group_id}/activity"
    elif scope == "connection":
        path = f"/admin/connections/{connection_id}/activity"
    elif scope == "api_key":
        path = f"/admin/api-keys/{api_key_id}/activity"
    else:
        raise ActivityPdfError(f"Unsupported activity scope: {scope}")

    return f"{_frontend_base_url()}{path}?{urlencode(params)}"


def _page_debug_snapshot(page) -> str:
    try:
        title = page.title()
        url = page.url
        root_html = page.eval_on_selector(
            "#root",
            "el => el ? el.innerHTML.slice(0, 400) : ''",
        )
        return f"url={url!r}, title={title!r}, root={root_html!r}"
    except Exception as exc:
        return f"debug unavailable: {exc}"


def _launch_browser(playwright):
    settings = get_settings()
    channel = (settings.playwright_browser_channel or "").strip()
    exe = os.environ.get("PLAYWRIGHT_EXECUTABLE_PATH", "").strip()
    launch_kwargs: dict = {"headless": True}
    if exe:
        launch_kwargs["executable_path"] = exe
        return playwright.chromium.launch(**launch_kwargs)
    if channel and channel != "chromium":
        try:
            return playwright.chromium.launch(channel=channel, **launch_kwargs)
        except Exception as channel_exc:
            logger.warning("Playwright channel %s unavailable: %s", channel, channel_exc)
    try:
        return playwright.chromium.launch(**launch_kwargs)
    except Exception as bundled_exc:
        raise ActivityPdfError(
            "No Chromium browser available for PDF export. Install Google Chrome or run: "
            "playwright install chromium"
        ) from bundled_exc


def _matches_activity_api(scope: str, url: str) -> bool:
    if scope == "service":
        return "/api/admin/dashboard/activity" in url
    if scope == "mine":
        return "/api/user/activity" in url
    if scope == "user":
        return "/api/admin/users/" in url and "/activity" in url
    if scope == "group":
        return "/api/admin/groups/" in url and "/activity" in url
    if scope == "connection":
        return "/api/admin/connections/" in url and "/activity" in url
    if scope == "api_key":
        return "/api/admin/api-keys/" in url and "/activity" in url
    return "/activity" in url


def _render_activity_page_pdf_sync(
    *,
    url: str,
    jwt_token: str,
    user_role: str,
    scope: str,
) -> bytes:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise ActivityPdfError(
            "Playwright is not installed. Run: pip install playwright && playwright install chromium"
        ) from exc

    token_json = json.dumps(jwt_token)
    role_json = json.dumps(user_role)
    init_script = f"""
localStorage.setItem("alpha_router_token", {token_json});
localStorage.setItem("alpha_router_role", {role_json});
localStorage.setItem("alpha_router_is_active", "1");
localStorage.setItem("alpha_router_login_at", String(Date.now()));
"""

    logger.info("Rendering activity PDF from %s", url)

    with sync_playwright() as playwright:
        browser = _launch_browser(playwright)
        try:
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            context.add_init_script(init_script)
            page = context.new_page()

            def _activity_response(resp) -> bool:
                return resp.request.method == "GET" and resp.ok and _matches_activity_api(scope, resp.url)

            try:
                with page.expect_response(_activity_response, timeout=90_000):
                    page.goto(url, wait_until="domcontentloaded", timeout=120_000)
            except Exception as nav_exc:
                if "/login" in page.url:
                    raise ActivityPdfError(
                        f"PDF export authentication failed (redirected to login). {_page_debug_snapshot(page)}"
                    ) from nav_exc
                err_el = page.query_selector(".activity-page .error, .error")
                err_text = err_el.inner_text().strip() if err_el else ""
                raise ActivityPdfError(
                    f"Activity data did not load ({_page_debug_snapshot(page)}"
                    f"{f', error={err_text!r}' if err_text else ''}): {nav_exc}"
                ) from nav_exc

            if "/login" in page.url:
                raise ActivityPdfError(
                    f"PDF export authentication failed (redirected to login). {_page_debug_snapshot(page)}"
                )

            page.wait_for_selector("#root", timeout=60_000)
            page.wait_for_selector(".activity-page", state="attached", timeout=60_000)
            page.wait_for_selector(".activity-metrics-grid", state="attached", timeout=60_000)
            page.wait_for_timeout(1500)
            page.add_style_tag(content=ACTIVITY_PDF_HIDE_CSS)
            page.emulate_media(media="screen")

            return page.pdf(
                format="A4",
                print_background=True,
                prefer_css_page_size=False,
                margin={"top": "10mm", "right": "8mm", "bottom": "10mm", "left": "8mm"},
                scale=0.82,
            )
        except ActivityPdfError:
            raise
        except Exception as exc:
            snapshot = _page_debug_snapshot(page) if "page" in locals() else "no page"
            raise ActivityPdfError(f"PDF capture failed ({snapshot}): {exc}") from exc
        finally:
            browser.close()


async def render_activity_page_pdf(
    *,
    scope: str,
    user_role: str,
    jwt_token: str,
    period: str,
    prompts_period: str | None,
    timezone: str,
    group_by: str = "model",
    model_id: str | None = None,
    username: str | None = None,
    app: str | None = None,
    response_status: str | None = None,
    user_id: int | None = None,
    group_id: int | None = None,
    connection_id: int | None = None,
    api_key_id: int | None = None,
) -> bytes:
    url = build_activity_frontend_url(
        scope=scope,
        user_role=user_role,
        period=period,
        prompts_period=prompts_period,
        timezone=timezone,
        group_by=group_by,
        model_id=model_id,
        username=username,
        app=app,
        response_status=response_status,
        user_id=user_id,
        group_id=group_id,
        connection_id=connection_id,
        api_key_id=api_key_id,
    )
    try:
        # Run in a worker thread so uvicorn can serve the SPA/API while Chromium loads the page.
        return await asyncio.to_thread(
            _render_activity_page_pdf_sync,
            url=url,
            jwt_token=jwt_token,
            user_role=user_role,
            scope=scope,
        )
    except ActivityPdfError:
        raise
    except Exception as exc:
        logger.exception("Activity PDF render failed")
        raise ActivityPdfError(
            f"PDF render failed: {exc}. Ensure the UI is reachable at {_frontend_base_url()} "
            "and Google Chrome or Edge is installed."
        ) from exc
