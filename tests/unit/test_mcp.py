import pytest


def test_importing_grip_does_not_require_the_mcp_extra():
    import grip
    assert grip.Browser is not None


def test_importing_the_server_module_does_not_require_mcp():
    # The mcp import lives inside main(); the module itself must stay importable
    # so the base wheel can be inspected without the extra installed.
    from grip.mcp import server
    assert server is not None


def test_mcp_tools_cover_the_core_surface():
    from grip.mcp.server import TOOL_NAMES
    assert {"open", "snapshot", "click", "type", "read"} <= set(TOOL_NAMES)


@pytest.mark.asyncio
async def test_tools_require_open_first():
    from grip.mcp import server
    server.reset_state()
    out = await server.call_tool("click", {"target": "Buy"})
    assert "ERROR" in out and "open" in out


@pytest.mark.asyncio
async def test_unknown_tool_answers_rather_than_raising():
    from grip.mcp import server
    server.reset_state()
    server._page = object()
    out = await server.call_tool("teleport", {})
    assert "unknown tool" in out
    server.reset_state()


@pytest.mark.asyncio
async def test_main_registers_every_tool_with_its_schema():
    """The tool schemas are derived from the wrapper signatures, so a renamed
    argument would silently ship a tool no client can call."""
    pytest.importorskip("mcp")
    from mcp.server import MCPServer

    from grip.mcp import server

    captured = {}
    original = MCPServer.run
    MCPServer.run = lambda self, transport="stdio", **kw: captured.setdefault("s", self)
    try:
        server.main()
    finally:
        MCPServer.run = original

    tools = await captured["s"].list_tools()
    schemas = {t.name: sorted(t.input_schema.get("properties", {})) for t in tools}
    assert set(schemas) == set(server.TOOL_NAMES)
    assert schemas["open"] == ["url"]
    assert schemas["type"] == ["target", "text"]
    assert schemas["snapshot"] == []

    # A failing tool answers; it does not take the server down with it.
    server.reset_state()
    result = await captured["s"].call_tool("click", {"target": "x"})
    assert "ERROR" in result.content[0].text


@pytest.mark.asyncio
async def test_snapshot_returns_the_delta_on_turn_two():
    """grip's differentiator: turn 2+ sends only what changed."""
    from grip.compression.delta import SnapshotDelta
    from grip.mcp import server

    server.reset_state()

    class FakePage:
        def __init__(self):
            self.delta = None
            self._current_snapshot = "SNAP"

        async def snapshot(self):
            self.delta = SnapshotDelta(version=2, previous_version=1, removed=["e3"])
            return self._current_snapshot

    server._page = FakePage()
    out = await server.call_tool("snapshot", {})
    assert "SNAP" not in out, "turn 2 must not resend the full snapshot"
    server.reset_state()
