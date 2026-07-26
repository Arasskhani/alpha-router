"""Security tests for the stream_chat MCP connector integration (Step 6).

Verifies the gating: connectors are only exposed when the user opts in,
and the iteration limit caps runaway tool-call loops. The per-user token
isolation and SSRF guards are covered in test_mcp_client_service.py.
"""

from __future__ import annotations

from app.services.chat_tools_service import ChatToolsConfig, parse_tools_config


def test_parse_tools_config_connectors_opt_in():
    cfg = parse_tools_config({"tools": {"connectors": True}})
    assert cfg.connectors is True


def test_parse_tools_config_connectors_default_off():
    cfg = parse_tools_config({"tools": {"web_search": True}})
    assert cfg.connectors is False


def test_parse_tools_config_connectors_top_level_flag():
    cfg = parse_tools_config({"connectors": True})
    assert cfg.connectors is True


def test_chat_tools_in_schema_accepts_connectors():
    from app.api.chat import ChatToolsIn

    body = ChatToolsIn(connectors=True)
    assert body.connectors is True
    dumped = body.model_dump()
    assert dumped["connectors"] is True


def test_opt_out_does_not_set_tools_flag():
    """When connectors is False, the config must not advertise connectors."""
    cfg = parse_tools_config({"tools": {"connectors": False, "code_interpreter": True}})
    assert cfg.connectors is False
    assert cfg.code_interpreter is True


def test_max_mcp_iterations_constant_exists():
    """The agent loop must cap MCP tool-call iterations to prevent runaway loops."""
    import inspect

    from app.services import proxy_service

    src = inspect.getsource(proxy_service)
    assert "MAX_MCP_ITERATIONS" in src
    assert "mcp_iterations < MAX_MCP_ITERATIONS" in src
