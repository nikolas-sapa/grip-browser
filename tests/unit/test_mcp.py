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


class _FakePage:
    """A page whose snapshots really change, driven through the real build_delta.

    Deliberately not a MagicMock: `mock.delta` is a truthy Mock, so _payload would
    take the delta branch unconditionally and the assertions would go green
    without a delta ever being computed.
    """

    def __init__(self, labels, cold_clicks=()):
        self._labels = list(labels)
        self._cold_clicks = set(cold_clicks)
        self._n = 0
        self._current_snapshot = None
        self._previous_snapshot = None
        self.delta = None

    async def snapshot(self):
        from grip.compression.delta import build_delta
        from grip.compression.summarizer import Element, PageSnapshot

        label = self._labels[min(self._n, len(self._labels) - 1)]
        self._n += 1
        snap = PageSnapshot(
            version=self._n,
            url="https://x.test",
            title="T",
            elements=[Element(
                index=0, tag="button", role="button", text=label, placeholder=None,
                in_shadow_dom=False, cx=0, cy=0, ref="e1", handle="h0",
            )],
            text_content=f"the page body says {label} and some stable trailing words",
            tokens_estimated=0,
        )
        self.delta = build_delta(self._previous_snapshot, snap)
        self._previous_snapshot = snap
        self._current_snapshot = snap
        return snap

    async def click(self, target):
        # The real Page.click snapshots itself when the ref cache is cold, which is
        # the state goto() leaves behind.
        if target in self._cold_clicks:
            await self.snapshot()
        return None


class _FakeBrowser:
    def __init__(self, page):
        self._page = page

    async def open(self, url, **kwargs):
        return self._page


@pytest.mark.asyncio
async def test_delta_is_not_sent_against_a_baseline_the_client_never_saw():
    """click() snapshots internally when the ref cache is cold, so the page's delta
    baseline moves on without anything being transmitted. Sending the next delta
    against that baseline would describe refs the client has never been shown."""
    from grip.mcp import server

    server.reset_state()
    page = _FakePage(["A", "X", "B"], cold_clicks={"B"})
    server._browser = _FakeBrowser(page)
    try:
        await server.call_tool("open", {"url": "https://x.test"})
        out = await server.call_tool("click", {"target": "B"})
    finally:
        server.reset_state()
    assert out.startswith("PAGE:"), (
        "sent a delta whose baseline was the un-transmitted click() snapshot"
    )


@pytest.mark.asyncio
async def test_open_resets_the_delta_baseline():
    """A second open is a fresh page: its first payload must be a full snapshot,
    and the delta after it must be readable against that."""
    from grip.mcp import server

    server.reset_state()
    page = _FakePage(["A", "B", "C"])
    server._browser = _FakeBrowser(page)
    try:
        first = await server.call_tool("open", {"url": "https://x.test"})
        second = await server.call_tool("snapshot", {})
    finally:
        server.reset_state()
    assert first.startswith("PAGE:")
    assert second.startswith("DELTA"), "turn 2 must not resend the full snapshot"


@pytest.mark.asyncio
async def test_missing_snapshot_is_reported_not_answered_with_an_empty_page():
    from grip.mcp import server

    server.reset_state()

    class _NeverSnapshots:
        delta = None
        _current_snapshot = None

        async def snapshot(self):
            return None

    server._page = _NeverSnapshots()
    try:
        with pytest.raises(RuntimeError):
            await server.call_tool("snapshot", {})
    finally:
        server.reset_state()


@pytest.mark.asyncio
async def test_snapshot_returns_the_delta_on_turn_two():
    """grip's differentiator: turn 2+ sends only what changed."""
    from grip.compression.delta import SnapshotDelta
    from grip.compression.summarizer import PageSnapshot
    from grip.mcp import server

    server.reset_state()

    class FakePage:
        def __init__(self):
            self.delta = None
            # A real snapshot, not a sentinel: the payload path renders it to
            # decide whether the delta is actually cheaper than sending it.
            self._current_snapshot = PageSnapshot(
                version=2, url="https://x.test", title="SNAPSHOT-TITLE",
                elements=[], text_content="a page body long enough that dropping "
                "one element is plainly the cheaper thing to send",
                tokens_estimated=0,
            )

        async def snapshot(self):
            self.delta = SnapshotDelta(version=2, previous_version=1, removed=["e3"])
            return self._current_snapshot

    server._page = FakePage()
    # The page is injected rather than opened, so state the baseline the client is
    # standing on: it was shown version 1.
    server._last_sent_version = 1
    out = await server.call_tool("snapshot", {})
    assert "SNAPSHOT-TITLE" not in out, "turn 2 must not resend the full snapshot"
    server.reset_state()


@pytest.mark.asyncio
async def test_a_delta_costlier_than_its_snapshot_is_not_sent():
    """The server carries its own copy of the payload decision, so it needs its
    own proof that an oversized delta falls back to the full page."""
    from grip.compression.delta import SnapshotDelta
    from grip.compression.summarizer import PageSnapshot
    from grip.mcp import server

    server.reset_state()

    class _FatDeltaPage:
        def __init__(self):
            self._current_snapshot = PageSnapshot(
                version=2, url="https://x.test", title="T", elements=[],
                text_content="short body", tokens_estimated=0,
            )
            self.delta = SnapshotDelta(
                version=2, previous_version=1,
                content_ops=[f"+{i}: {'word' * 10}" for i in range(40)],
            )

        async def snapshot(self):
            return self._current_snapshot

    server._page = _FatDeltaPage()
    server._last_sent_version = 1
    try:
        out = await server.call_tool("snapshot", {})
        assert out.startswith("PAGE:"), "sent a delta that cost more than the full page"
        # The baseline follows what was actually sent, or the next delta is
        # written against a version the client never received.
        assert server._last_sent_version == 2
    finally:
        server.reset_state()
