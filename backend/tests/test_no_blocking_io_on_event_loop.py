"""No synchronous object-storage call may run inside an ``async def``.

``_put_object_once`` ran ``oss.put_object`` through ``asyncio.to_thread`` and
``oss.object_exists`` directly on the next line up - both are boto3 network
calls, and with boto3's retries the un-threaded one could hold the event loop
for tens of seconds on a slow storage backend, stopping every concurrent SSE
stream in that worker mid-token.

A test that names the two functions would have to be rewritten every time
storage grows a new helper, so this walks the AST instead: any call to a known
blocking ``object_storage_service`` function, lexically inside an ``async def``
and not wrapped in ``to_thread``/``run_in_executor``, fails.
"""

from __future__ import annotations

import ast
import pathlib

#: Synchronous boto3 wrappers in object_storage_service. Anything here must be
#: handed to a thread before it is called from async code.
BLOCKING_CALLS = frozenset(
    {
        "object_exists",
        "put_object",
        "get_object_bytes",
        "delete_object",
        "ensure_bucket",
        "purge_user_cdn_objects",
        "list_objects",
        "head_object",
    }
)

_OFFLOADERS = frozenset({"to_thread", "run_in_executor", "run_sync"})

APP = pathlib.Path(__file__).resolve().parents[1] / "app"


def _called_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


class _Visitor(ast.NodeVisitor):
    def __init__(self, path: pathlib.Path) -> None:
        self.path = path
        self.depth = 0
        self.offenders: list[str] = []

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
        self.depth += 1
        self.generic_visit(node)
        self.depth -= 1

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        # A plain def inside an async def runs on whatever calls it; treat it as
        # a boundary rather than guessing.
        outer, self.depth = self.depth, 0
        self.generic_visit(node)
        self.depth = outer

    def visit_Call(self, node: ast.Call) -> None:
        name = _called_name(node)
        if name in _OFFLOADERS:
            # The blocking callable is an argument here, not a call. Walk the
            # rest of the arguments but not the offloaded reference itself.
            for arg in node.args[1:] + [kw.value for kw in node.keywords]:
                self.visit(arg)
            return
        if self.depth > 0 and name in BLOCKING_CALLS:
            self.offenders.append(f"{self.path}:{node.lineno} {name}()")
        self.generic_visit(node)


def test_object_storage_is_never_called_synchronously_from_async_code():
    offenders: list[str] = []
    for path in sorted(APP.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        visitor = _Visitor(path.relative_to(APP.parent))
        visitor.visit(tree)
        offenders.extend(visitor.offenders)

    assert offenders == [], "synchronous object-storage calls inside async functions:\n  " + "\n  ".join(offenders)
