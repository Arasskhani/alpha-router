"""Every query that looks for model providers reads only model connections.

A web search connection's key must never be synced for models, offered where
models or provider connections are chosen, or counted as a model provider. A
query on ``connections`` that reaches models through ``AIModel`` (a join on
``AIModel.connection_id``, or ``db.get`` of a model's own connection) is safe
by construction: a web search connection has no models. Anything else names
its kind, or is listed here with the reason it reads every kind.
"""

from __future__ import annotations

import re
from pathlib import Path

_APP = Path(__file__).resolve().parents[1] / "app"

#: Statements that start a query on connections directly.
_DIRECT = re.compile(r"select\(Connection(\.id)?\)|select_from\(Connection\)")
#: How far a statement may run past its start (a multi-line select).
_SPAN = 400

#: (file, a fragment of the line) for the queries that read every kind on purpose.
_EVERY_KIND = {
    # The Connections page lists both kinds, each in its tab.
    ("api/admin.py", "select(Connection).order_by(Connection.id.desc())"),
}


def _direct_queries() -> list[tuple[str, int, str]]:
    found = []
    for path in sorted(_APP.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(_APP).as_posix()
        for match in _DIRECT.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            found.append((rel, line, text[match.start() : match.start() + _SPAN]))
    return found


def test_every_direct_query_on_connections_names_its_kind():
    unfiltered = []
    for rel, line, statement in _direct_queries():
        if any(rel == file and statement.startswith(fragment) for file, fragment in _EVERY_KIND):
            continue
        head = statement.split("\n\n", 1)[0]
        if "model_connection()" in head or "web_search_connection()" in head:
            continue
        unfiltered.append(f"{rel}:{line}")
    assert not unfiltered, (
        "A query on connections that does not say which kind it reads (add model_connection() or "
        "web_search_connection(), or list it in _EVERY_KIND with the reason): " + ", ".join(unfiltered)
    )


def test_the_guard_sees_the_queries_it_is_about():
    files = {rel for rel, _, _ in _direct_queries()}
    assert {"services/scheduler.py", "services/transcription_service.py", "api/admin.py"} <= files
