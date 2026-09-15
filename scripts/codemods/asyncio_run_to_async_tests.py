"""One-shot codemod (Phase 3.2): `asyncio.run(run())` tests -> native async tests.

Before::

    def test_x():
        async def run():
            ...body...

        asyncio.run(run())

After::

    async def test_x():
        ...body...

Only the exact shape above is rewritten (a test whose body is one inner
``async def`` followed by ``asyncio.run(<inner>())`` as the last statement,
optionally with statements *before* the inner def). Any other
``asyncio.run`` inside a test function becomes ``await ...`` and the test is
made ``async``. Helper functions and module-level calls are left alone.
Requires pytest-asyncio with ``asyncio_mode = auto`` (see pytest.ini).

Usage: python scripts/codemods/asyncio_run_to_async_tests.py backend/tests/*.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import libcst as cst
import libcst.matchers as m


def _is_asyncio_run_call(node: cst.BaseExpression) -> bool:
    return m.matches(
        node,
        m.Call(func=m.Attribute(value=m.Name("asyncio"), attr=m.Name("run"))),
    )


class _AwaitInsteadOfRun(cst.CSTTransformer):
    """Inside one test body: asyncio.run(x) -> await x. Does not descend into nested defs."""

    def __init__(self) -> None:
        self.changed = False
        self._depth = 0

    def visit_FunctionDef(self, node: cst.FunctionDef) -> bool:
        self._depth += 1
        return False  # never rewrite inside nested functions

    def leave_FunctionDef(self, original: cst.FunctionDef, updated: cst.FunctionDef) -> cst.FunctionDef:
        self._depth -= 1
        return updated

    def visit_Lambda(self, node: cst.Lambda) -> bool:
        return False

    def leave_Call(self, original: cst.Call, updated: cst.Call) -> cst.BaseExpression:
        if self._depth == 0 and _is_asyncio_run_call(updated) and len(updated.args) == 1:
            self.changed = True
            return cst.Await(expression=updated.args[0].value)
        return updated


class TestRewriter(cst.CSTTransformer):
    def __init__(self) -> None:
        self.rewritten = 0
        self.awaited = 0

    def leave_FunctionDef(self, original: cst.FunctionDef, updated: cst.FunctionDef) -> cst.FunctionDef:
        if not updated.name.value.startswith("test_") or updated.asynchronous is not None:
            return updated
        if not isinstance(updated.body, cst.IndentedBlock):
            return updated
        stmts = list(updated.body.body)
        if not stmts:
            return updated

        last = stmts[-1]
        # Shape A: ... ; async def inner(): BODY ; asyncio.run(inner())
        if (
            len(stmts) >= 2
            and isinstance(stmts[-2], cst.FunctionDef)
            and stmts[-2].asynchronous is not None
            and not stmts[-2].params.params
            and not stmts[-2].params.kwonly_params
            and not stmts[-2].decorators
            and m.matches(
                last,
                m.SimpleStatementLine(
                    body=[
                        m.Expr(
                            value=m.Call(
                                func=m.Attribute(value=m.Name("asyncio"), attr=m.Name("run")),
                                args=[m.Arg(value=m.Call(func=m.Name(stmts[-2].name.value), args=[]))],
                            )
                        )
                    ]
                ),
            )
        ):
            inner = stmts[-2]
            prefix = stmts[:-2]
            inner_body = inner.body
            if not isinstance(inner_body, cst.IndentedBlock):
                return updated
            # A test body that references the inner function's name elsewhere
            # (e.g. `run` passed around) is not safe to inline.
            name = inner.name.value
            for s in prefix:
                if m.findall(s, m.Name(name)):
                    return updated
            new_body = list(prefix) + list(inner_body.body)
            # Keep a leading docstring/comment of the inner body readable.
            self.rewritten += 1
            return updated.with_changes(
                asynchronous=cst.Asynchronous(),
                body=updated.body.with_changes(body=new_body),
            )

        # Shape B: any other asyncio.run(...) directly in the test body -> await.
        t = _AwaitInsteadOfRun()
        new_body = updated.body.visit(t)
        if t.changed:
            self.awaited += 1
            return updated.with_changes(asynchronous=cst.Asynchronous(), body=new_body)
        return updated


def rewrite(path: Path) -> tuple[int, int]:
    src = path.read_text()
    if "asyncio.run(" not in src:
        return 0, 0
    module = cst.parse_module(src)
    tr = TestRewriter()
    new = module.visit(tr)
    if tr.rewritten or tr.awaited:
        path.write_text(new.code)
    return tr.rewritten, tr.awaited


def main(argv: list[str]) -> int:
    total_a = total_b = 0
    for arg in argv:
        a, b = rewrite(Path(arg))
        total_a += a
        total_b += b
        if a or b:
            print(f"{arg}: inlined={a} awaited={b}")
    print(f"total inlined={total_a} awaited={total_b}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
