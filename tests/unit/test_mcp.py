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
    expected = {"open", "goto", "snapshot", "click", "type", "read", "screenshot", "run"}
    assert expected <= set(TOOL_NAMES)


@pytest.mark.asyncio
async def test_tools_require_open_first():
    from grip.mcp import server
    server.reset_state()
    with pytest.raises(RuntimeError, match="open"):
        await server.call_tool("click", {"target": "Buy"})


@pytest.mark.asyncio
async def test_unknown_tool_raises_rather_than_answering_with_a_string():
    """A tool error is now a protocol-level signal (is_error=True at the real
    dispatch layer, mcp.server.mcpserver.server._handle_call_tool), not text the
    client has to pattern-match for "ERROR"."""
    from grip.mcp import server
    server.reset_state()
    server._page = object()
    with pytest.raises(ValueError, match="unknown tool"):
        await server.call_tool("teleport", {})
    server.reset_state()


@pytest.mark.asyncio
async def test_main_registers_every_tool_with_its_schema():
    """The tool schemas are derived from the wrapper signatures, so a renamed
    argument would silently ship a tool no client can call."""
    pytest.importorskip("mcp")
    from mcp.server import MCPServer
    from mcp.server.mcpserver.exceptions import ToolError

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
    assert schemas["goto"] == ["url"]
    assert schemas["type"] == ["target", "text"]
    assert schemas["snapshot"] == []
    assert schemas["screenshot"] == []
    assert schemas["run"] == ["goal", "url"]

    # A failing tool raises rather than answering with an "ERROR: ..." string.
    # MCPServer.call_tool (used here) propagates it as ToolError; the real wire
    # path (_handle_call_tool, what server.run() actually serves) catches
    # exactly this and converts it into CallToolResult(is_error=True) instead —
    # that conversion is the framework's job, not ours to reimplement here.
    server.reset_state()
    with pytest.raises(ToolError, match="open"):
        await captured["s"].call_tool("click", {"target": "x"})


@pytest.mark.asyncio
async def test_lifespan_closes_the_browser_on_clean_shutdown():
    """The clean stdio-exit path used to strand a Chrome process: reset_state()
    only dropped the handle, close() was never called anywhere. The lifespan
    context manager MCPServer enters/exits around the whole session is where a
    clean exit — client disconnects, stdin closes, SIGTERM — actually unwinds."""
    from grip.mcp import server

    closed = []

    class _FakeBrowser:
        async def close(self):
            closed.append(True)

    server.reset_state()
    server._browser = _FakeBrowser()
    server._page = object()
    async with server._lifespan(None):
        pass
    assert closed == [True]
    assert server._browser is None
    assert server._page is None


class _FakePage:
    """A page whose snapshots really change, driven through the real build_delta.

    Deliberately not a MagicMock: `mock.delta` is a truthy Mock, so payload()
    would take the delta branch unconditionally and the assertions would go
    green without a delta ever being computed.
    """

    def __init__(self, labels, cold_clicks=()):
        self._labels = list(labels)
        self._cold_clicks = set(cold_clicks)
        self._n = 0
        self._current_snapshot = None
        self._previous_snapshot = None
        self.delta = None
        from grip.compression.summarizer import Summarizer
        self._summarizer = Summarizer()

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

    def payload(self, last_sent_version):
        from grip.page import render_payload
        return render_payload(
            self._current_snapshot, self.delta, last_sent_version, self._summarizer
        )

    async def click(self, target):
        # The real Page.click snapshots itself when the ref cache is cold, which is
        # the state goto() leaves behind.
        if target in self._cold_clicks:
            await self.snapshot()
        return None


class _FakeBrowser:
    def __init__(self, page):
        self._page = page
        self._llm = None
        self.trace = None

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

        def payload(self, last_sent_version):
            from grip.page import render_payload
            return render_payload(self._current_snapshot, self.delta, last_sent_version, None)

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
    from grip.compression.summarizer import PageSnapshot, Summarizer
    from grip.mcp import server

    server.reset_state()

    class FakePage:
        def __init__(self):
            self.delta = None
            self._summarizer = Summarizer()
            # A real snapshot, not a sentinel: the payload path renders it to
            # decide whether the delta is actually cheaper than sending it.
            self._current_snapshot = PageSnapshot(
                version=2, url="https://x.test", title="SNAPSHOT-TITLE",
                elements=[], text_content="a page body long enough that dropping "
                "one element is plainly the cheaper thing to send",
                tokens_estimated=0,
            )

        def payload(self, last_sent_version):
            from grip.page import render_payload
            return render_payload(
                self._current_snapshot, self.delta, last_sent_version, self._summarizer
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
    """The min(delta, full) guard: `render_payload` (shared by grip.mcp.server and
    Runner via Page.payload()) must never emit a delta larger than the full
    snapshot it would replace. This is the same shape as the RESULTS_AB.md
    pathological case — a delta measured at 259x the cost of the snapshot it
    would have replaced, with nothing upstream stopping it from being sent."""
    from grip.compression.delta import SnapshotDelta
    from grip.compression.summarizer import PageSnapshot, Summarizer
    from grip.mcp import server

    server.reset_state()

    class _FatDeltaPage:
        def __init__(self):
            self._summarizer = Summarizer()
            self._current_snapshot = PageSnapshot(
                version=2, url="https://x.test", title="T", elements=[],
                text_content="short body", tokens_estimated=0,
            )
            # Pathological: hundreds of content_ops dwarfing the 3-word snapshot
            # they would replace.
            self.delta = SnapshotDelta(
                version=2, previous_version=1,
                content_ops=[f"+{i}: {'word' * 10}" for i in range(400)],
            )

        def payload(self, last_sent_version):
            from grip.page import render_payload
            return render_payload(
                self._current_snapshot, self.delta, last_sent_version, self._summarizer
            )

        async def snapshot(self):
            return self._current_snapshot

    server._page = _FatDeltaPage()
    server._last_sent_version = 1
    try:
        out = await server.call_tool("snapshot", {})
        assert out.startswith("PAGE:"), "sent a delta that cost more than the full page"
        assert len(out) < 200, "the fallback itself must not still be the oversized delta"
        # The baseline follows what was actually sent, or the next delta is
        # written against a version the client never received.
        assert server._last_sent_version == 2
    finally:
        server.reset_state()


class _MultiTabPage(_FakePage):
    """_FakePage plus the bits list_tabs/switch_tab/close_tab actually touch:
    an identity (_target_id), a URL, and a close() that reports itself."""

    def __init__(self, target_id, url, closed_log):
        super().__init__([url])
        self._target_id = target_id
        self._current_url = url
        self._closed_log = closed_log

    async def close(self):
        self._closed_log.append(self._target_id)


class _MultiTabBrowser:
    """Owns several tabs at once, like the real Browser._pages list — enough
    for list_tabs/switch_tab/close_tab to exercise Browser.pages/get_page."""

    def __init__(self, pages):
        self._all_pages = list(pages)
        self._llm = None
        self.trace = None

    @property
    def pages(self):
        return tuple(self._all_pages)

    def get_page(self, target_id):
        for p in self._all_pages:
            if p._target_id == target_id:
                return p
        return None

    async def open(self, url, **kwargs):
        return self._all_pages[0]


@pytest.mark.asyncio
async def test_list_tabs_marks_the_active_one():
    from grip.mcp import server

    server.reset_state()
    closed = []
    page_a = _MultiTabPage("A1", "https://a.test", closed)
    page_b = _MultiTabPage("B2", "https://b.test", closed)
    server._browser = _MultiTabBrowser([page_a, page_b])
    server._page = page_b
    try:
        out = await server.call_tool("list_tabs", {})
    finally:
        server.reset_state()
    assert "A1\thttps://a.test" in out
    assert "B2\thttps://b.test\t[active]" in out


@pytest.mark.asyncio
async def test_switch_tab_makes_a_different_open_tab_active():
    from grip.mcp import server

    server.reset_state()
    closed = []
    page_a = _MultiTabPage("A1", "https://a.test", closed)
    page_b = _MultiTabPage("B2", "https://b.test", closed)
    server._browser = _MultiTabBrowser([page_a, page_b])
    server._page = page_a
    try:
        out = await server.call_tool("switch_tab", {"target_id": "B2"})
        assert server._page is page_b
        assert out.startswith("PAGE:"), "a switched-to tab is a fresh baseline"

        with pytest.raises(ValueError, match="no open tab"):
            await server.call_tool("switch_tab", {"target_id": "nope"})
    finally:
        server.reset_state()


@pytest.mark.asyncio
async def test_close_tab_by_id_leaves_the_active_tab_alone():
    from grip.mcp import server

    server.reset_state()
    closed = []
    page_a = _MultiTabPage("A1", "https://a.test", closed)
    page_b = _MultiTabPage("B2", "https://b.test", closed)
    server._browser = _MultiTabBrowser([page_a, page_b])
    server._page = page_a
    try:
        out = await server.call_tool("close_tab", {"target_id": "B2"})
    finally:
        server.reset_state()
    assert closed == ["B2"]
    assert "B2" in out


@pytest.mark.asyncio
async def test_close_tab_defaults_to_active_and_clears_it():
    """Closing the active tab must not silently repoint _page at another tab —
    the next click/type would land somewhere the client didn't ask for."""
    from grip.mcp import server

    server.reset_state()
    closed = []
    page_a = _MultiTabPage("A1", "https://a.test", closed)
    server._browser = _MultiTabBrowser([page_a])
    server._page = page_a
    try:
        await server.call_tool("close_tab", {})
        assert closed == ["A1"]
        assert server._page is None
        with pytest.raises(RuntimeError, match="open"):
            await server.call_tool("snapshot", {})
    finally:
        server.reset_state()
