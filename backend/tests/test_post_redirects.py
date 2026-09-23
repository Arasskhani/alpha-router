"""A route that answers a write request with a redirect must say 303 (or 302).

Starlette's ``RedirectResponse`` defaults to 307, which tells the browser to
repeat the same method and body at the new address. After a form POST (the
SAML ACS is one) that sends the POST on to a page that only answers GET, and
the user sees ``405 Method Not Allowed``. SAML sign-in was broken exactly like
that; this test keeps the next handler from doing it again.

What it reads, in every module under app/api (subpackages included):

- handlers registered for POST, PUT, PATCH or DELETE: ``@router.post`` and
  friends, and ``@router.api_route`` / ``router.add_api_route`` with
  ``methods=``;
- the ``RedirectResponse`` calls inside them, under whatever name it was
  imported as, or spelt ``responses.RedirectResponse``;
- ``response_class=RedirectResponse`` on the route itself, where FastAPI turns
  the returned URL into a redirect with the route's ``status_code``.

A status given as a number or as a ``status.HTTP_...`` constant is understood;
anything computed is flagged for a person to look at. A redirect built in a
helper function that the handler calls is not followed.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest

API_DIR = Path(__file__).resolve().parent.parent / "app" / "api"
WRITE_METHODS = {"post", "put", "patch", "delete"}
ALLOWED = {302, 303}
COMPUTED = -1

Handler = ast.FunctionDef | ast.AsyncFunctionDef


def _code(value: ast.expr) -> int:
    """303, ``status.HTTP_303_SEE_OTHER`` or ``HTTP_303_SEE_OTHER`` as a number; COMPUTED otherwise."""
    if isinstance(value, ast.Constant) and isinstance(value.value, int):
        return value.value
    name = value.attr if isinstance(value, ast.Attribute) else value.id if isinstance(value, ast.Name) else ""
    match = re.fullmatch(r"HTTP_(\d{3})(?:_\w+)?", name)
    return int(match.group(1)) if match else COMPUTED


def _keyword(call: ast.Call, name: str) -> ast.expr | None:
    return next((keyword.value for keyword in call.keywords if keyword.arg == name), None)


def _status_of(call: ast.Call) -> int | None:
    """The status a RedirectResponse(...) call passes, or None for its default (307)."""
    value = _keyword(call, "status_code")
    if value is None and len(call.args) > 1:
        value = call.args[1]
    return None if value is None else _code(value)


def _redirect_names(tree: ast.Module) -> set[str]:
    """The names RedirectResponse goes by in this module."""
    names = {"RedirectResponse"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names.update(alias.asname or alias.name for alias in node.names if alias.name == "RedirectResponse")
    return names


def _is_redirect(expr: ast.expr, names: set[str]) -> bool:
    if isinstance(expr, ast.Name):
        return expr.id in names
    return isinstance(expr, ast.Attribute) and expr.attr == "RedirectResponse"


def _write_methods(call: ast.Call) -> set[str]:
    """The write methods a route decorator or an add_api_route call registers."""
    if not isinstance(call.func, ast.Attribute):
        return set()
    if call.func.attr in WRITE_METHODS:
        return {call.func.attr}
    if call.func.attr not in {"api_route", "add_api_route"}:
        return set()
    methods = _keyword(call, "methods")
    if not isinstance(methods, (ast.List, ast.Tuple, ast.Set)):
        return set()  # FastAPI's default: GET
    return {
        element.value.lower()
        for element in methods.elts
        if isinstance(element, ast.Constant) and isinstance(element.value, str)
    } & WRITE_METHODS


def _handlers(tree: ast.Module) -> list[tuple[Handler, ast.Call]]:
    """Each write handler with the call that registers it."""
    functions = [node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    found = [
        (function, decorator)
        for function in functions
        for decorator in function.decorator_list
        if isinstance(decorator, ast.Call) and _write_methods(decorator)
    ]
    by_name = {function.name: function for function in functions}
    for call in ast.walk(tree):
        if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)):
            continue
        if call.func.attr != "add_api_route" or not _write_methods(call):
            continue
        endpoint = call.args[1] if len(call.args) > 1 else _keyword(call, "endpoint")
        if isinstance(endpoint, ast.Name) and endpoint.id in by_name:
            found.append((by_name[endpoint.id], call))
    return found


def _shown(status: int | None) -> str:
    return "default 307" if status is None else "computed" if status == COMPUTED else str(status)


def _offenders() -> list[str]:
    found: set[str] = set()
    for path in sorted(API_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = _redirect_names(tree)
        where = path.relative_to(API_DIR).as_posix()
        for handler, route in _handlers(tree):
            response_class = _keyword(route, "response_class")
            if response_class is not None and _is_redirect(response_class, names):
                route_status = _keyword(route, "status_code")
                status = None if route_status is None else _code(route_status)
                if status not in ALLOWED:
                    found.add(f"{where}:{route.lineno} {handler.name} (response_class, {_shown(status)})")
            for call in ast.walk(handler):
                if isinstance(call, ast.Call) and _is_redirect(call.func, names):
                    status = _status_of(call)
                    if status not in ALLOWED:
                        found.add(f"{where}:{call.lineno} {handler.name} ({_shown(status)})")
    return sorted(found)


def test_redirects_after_a_write_request_switch_the_browser_to_get() -> None:
    assert _offenders() == []


HEADER = (
    "from fastapi import APIRouter, status\n"
    "from fastapi.responses import RedirectResponse\n"
    "from fastapi import responses\n"
    "router = APIRouter()\n"
)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        pytest.param(
            "@router.post('/x')\nasync def x():\n    return RedirectResponse('/y')\n",
            ["bad.py:7 x (default 307)"],
            id="default",
        ),
        pytest.param(
            "@router.post('/x')\nasync def x():\n    return RedirectResponse('/y', status_code=status.HTTP_303_SEE_OTHER)\n",
            [],
            id="status-constant",
        ),
        pytest.param(
            "@router.put('/x')\ndef x():\n    return RedirectResponse('/y', status.HTTP_307_TEMPORARY_REDIRECT)\n",
            ["bad.py:7 x (307)"],
            id="positional-constant",
        ),
        pytest.param(
            "@router.post('/x')\nasync def x(code: int):\n    return RedirectResponse('/y', status_code=code)\n",
            ["bad.py:7 x (computed)"],
            id="computed",
        ),
        pytest.param(
            "@router.api_route('/x', methods=['GET', 'POST'])\nasync def x():\n    return RedirectResponse('/y')\n",
            ["bad.py:7 x (default 307)"],
            id="api-route",
        ),
        pytest.param(
            "async def x():\n    return RedirectResponse('/y')\nrouter.add_api_route('/x', x, methods=['POST'])\n",
            ["bad.py:6 x (default 307)"],
            id="add-api-route",
        ),
        pytest.param(
            "@router.post('/x', response_class=RedirectResponse)\nasync def x():\n    return '/y'\n",
            ["bad.py:5 x (response_class, default 307)"],
            id="response-class",
        ),
        pytest.param(
            "@router.post('/x', response_class=RedirectResponse, status_code=303)\nasync def x():\n    return '/y'\n",
            [],
            id="response-class-303",
        ),
        pytest.param(
            "from starlette.responses import RedirectResponse as Go\n"
            "@router.patch('/x')\nasync def x():\n    return Go('/y')\n",
            ["bad.py:8 x (default 307)"],
            id="aliased",
        ),
        pytest.param(
            "@router.delete('/x')\nasync def x():\n    return responses.RedirectResponse('/y')\n",
            ["bad.py:7 x (default 307)"],
            id="attribute",
        ),
        pytest.param(
            "@router.get('/x')\nasync def x():\n    return RedirectResponse('/y')\n"
            "@router.api_route('/z')\nasync def z():\n    return RedirectResponse('/y')\n",
            [],
            id="get-is-fine",
        ),
    ],
)
def test_the_check_reads_each_way_of_writing_a_redirect(tmp_path, monkeypatch, source, expected) -> None:
    (tmp_path / "bad.py").write_text(HEADER + source, encoding="utf-8")
    monkeypatch.setattr(sys.modules[__name__], "API_DIR", tmp_path)
    assert _offenders() == expected


def test_the_check_looks_into_subpackages(tmp_path, monkeypatch) -> None:
    (tmp_path / "admin").mkdir()
    (tmp_path / "admin" / "sso.py").write_text(
        HEADER + "@router.post('/x')\nasync def x():\n    return RedirectResponse('/y')\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(sys.modules[__name__], "API_DIR", tmp_path)
    assert _offenders() == ["admin/sso.py:7 x (default 307)"]
