"""A route that answers a POST with a redirect must say 303 (or 302).

Starlette's ``RedirectResponse`` defaults to 307, which tells the browser to
repeat the same method and body at the new address. After a form POST (the
SAML ACS is one) that sends the POST on to a page that only answers GET, and
the user sees ``405 Method Not Allowed``. SAML sign-in was broken exactly like
that; this test keeps the next POST handler from doing it again.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

API_DIR = Path(__file__).resolve().parent.parent / "app" / "api"
WRITE_METHODS = {"post", "put", "patch", "delete"}
ALLOWED = {302, 303}


def _status_of(call: ast.Call) -> int | None:
    """The literal status code a RedirectResponse(...) call passes, or None for the default."""
    for keyword in call.keywords:
        if keyword.arg == "status_code":
            value = keyword.value
            if isinstance(value, ast.Constant) and isinstance(value.value, int):
                return value.value
            return -1  # computed: flagged, a reviewer should look
    if len(call.args) > 1:
        value = call.args[1]
        if isinstance(value, ast.Constant) and isinstance(value.value, int):
            return value.value
        return -1
    return None


def _offenders() -> list[str]:
    found: list[str] = []
    for path in sorted(API_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            methods = {
                dec.func.attr
                for dec in node.decorator_list
                if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)
            } & WRITE_METHODS
            if not methods:
                continue
            for call in ast.walk(node):
                if isinstance(call, ast.Call) and getattr(call.func, "id", None) == "RedirectResponse":
                    status = _status_of(call)
                    if status not in ALLOWED:
                        shown = "default 307" if status is None else status
                        found.append(f"{path.name}:{call.lineno} {node.name} ({shown})")
    return found


def test_redirects_after_a_write_request_switch_the_browser_to_get() -> None:
    assert _offenders() == []


def test_the_check_would_catch_the_default(tmp_path, monkeypatch) -> None:
    bad = tmp_path / "bad.py"
    bad.write_text(
        "from fastapi import APIRouter\n"
        "from fastapi.responses import RedirectResponse\n"
        "router = APIRouter()\n"
        "@router.post('/x')\n"
        "async def x():\n"
        "    return RedirectResponse('/y')\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(sys.modules[__name__], "API_DIR", tmp_path)
    assert _offenders() == ["bad.py:6 x (default 307)"]
