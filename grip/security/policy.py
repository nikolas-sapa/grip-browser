from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

from grip.errors.types import BrowserError, ErrorType, GripError

# The metadata addresses are the ones that matter on a cloud runner:
# 169.254.169.254 is the AWS/GCP/Azure instance metadata endpoint, 169.254.170.2
# is ECS's. Reaching either from a page the agent was told to visit hands out
# credentials.
_METADATA_HOSTS = {"169.254.169.254", "169.254.170.2", "metadata.google.internal"}


def _canonical_ipv4(host: str) -> str | None:
    """Normalize IPv4 spellings Chrome/inet_aton accept but ipaddress.ip_address
    rejects — decimal (2130706433), octal (0177.0.0.1), hex (0x7f000001), and
    short dotted-quad (127.1) — to a canonical dotted-quad string. Matches
    inet_aton's a / a.b / a.b.c / a.b.c.d parsing (trailing part fills the
    remaining bits). Returns None if `host` isn't an inet_aton-parseable IPv4
    form, in which case it's either a normal dotted-quad, an IPv6 literal, or
    a DNS name — all handled unchanged below."""
    try:
        return socket.inet_ntoa(socket.inet_aton(host))
    except (OSError, UnicodeError):
        return None


class NavigationPolicy:
    """Decides what a grip browser may open.

    Fail-closed by default: http(s) to public addresses only. Callers that
    genuinely drive a local dev server or read local files opt in per-Browser.
    A default-open policy makes every "summarize this URL" feature an SSRF plus
    a local-file read.

    One residual gap, stated plainly rather than implied away:

    * A DNS name is resolved inside Chrome, so this policy never sees the
      address the request lands on. `internal.corp.example` pointing at
      10.0.0.5 passes. Pinning the resolved IP would mean resolving here and
      forcing Chrome onto that address; that is out of scope.

    * WebSocket handshakes are not covered. CDP's Fetch domain — the
      mechanism Page uses to pause and refuse a request before it leaves
      (see Page._ensure_fetch_interception) — does not intercept
      `Fetch.requestPaused` for WebSocket upgrades; this is a Chromium
      limitation, not a gap in how Page wires it up. Page JS running
      `new WebSocket('ws://169.254.169.254/')` reaches the internal host
      regardless of this policy. There is no in-process fix for this.

    * `window.open()` / `target="_blank"` is closed outright, not merely
      unenforced — see `allow_popups` below.

    Every navigation entry point (Browser.open(), Page.goto(), and each
    Document-level redirect leg) runs the URL through `enforce()` below, so a
    302 from a public URL to 169.254.169.254 is refused too — see Page.goto().
    """

    def __init__(
        self,
        allow_private: bool = False,
        allow_file: bool = False,
        allow_popups: bool = False,
    ) -> None:
        self._allow_private = allow_private
        self._allow_file = allow_file
        self._allow_popups = allow_popups

    @property
    def allow_private(self) -> bool:
        """Whether this policy has anything left to enforce against private/
        loopback/link-local targets. Callers that gate expensive enforcement
        machinery (e.g. Page's Fetch-domain interception) on "is this policy
        actually restrictive" read this instead of reaching into `_allow_private`."""
        return self._allow_private

    @property
    def allow_popups(self) -> bool:
        """Whether `window.open()` / `target="_blank"` is permitted to actually
        open, instead of being closed on attach (see Page._ensure_popup_blocking).

        Default is False — the secure, previously-unreviewed v0.6.0 behaviour
        stays the default, it just becomes an explicit, documented choice
        instead of a silent one.

        Opting in costs exactly what blocking exists to prevent: a popup opens
        a brand-new CDP target with its own independent Fetch-domain state, and
        this policy is NOT enforced inside it — no SSRF/private-address check,
        no scheme check, nothing. A page that can `window.open()` at all can
        reach `http://169.254.169.254/` or `file:///etc/passwd` from inside the
        popup regardless of how this policy is otherwise configured. Set this
        only when you trust the target to open windows — e.g. driving an OAuth
        provider you already trust.

        ponytail: the proper long-term fix is per-target Fetch interception —
        arm Fetch.enable on the popup's session before resuming it from its
        paused state, so the same policy applies there too. That needs
        session-scoped command routing and demuxing Fetch.requestPaused by
        session, which CDPEngine does not do today (one target per websocket).
        This flag is the stopgap until that lands.
        """
        return self._allow_popups

    def check(self, url: str) -> str | None:
        """Return a human-readable refusal reason, or None if the URL is allowed."""
        # Bare about:blank is the one non-http exception, and it stays an exception:
        # an empty tab reaches no network and reads no file, so refusing it buys
        # zero coverage against SSRF or local file disclosure while breaking grip's
        # own idiom for "open a tab" (Target.createTarget uses it internally).
        # Deliberately an exact match, not a scheme check — about:cache,
        # about:net-internals and the rest of chrome://-adjacent internals do expose
        # browser state and stay refused. Do not "tighten" this to `scheme ==
        # "about"`, and do not loosen it to a prefix.
        if url.strip().lower() == "about:blank":
            return None
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            if parsed.scheme == "file" and self._allow_file:
                return None
            return f"scheme {parsed.scheme!r} is not allowed (http/https only)"
        host = parsed.hostname or ""
        # Canonicalize before any check below: 2130706433, 0177.0.0.1,
        # 0x7f000001 and 127.1 are all loopback to Chrome (inet_aton
        # semantics) but ipaddress.ip_address rejects every one of them,
        # which used to fall through to the "it's a DNS name" branch.
        check_host = _canonical_ipv4(host) or host
        if check_host in _METADATA_HOSTS:
            return f"{host} is a cloud metadata endpoint"
        if host == "localhost" or host.endswith(".localhost"):
            if not self._allow_private:
                return "localhost is not allowed (pass allow_private=True to permit)"
            return None
        try:
            addr = ipaddress.ip_address(check_host)
        except ValueError:
            # A DNS name — see the class docstring for why this is a pass.
            return None
        if (addr.is_private or addr.is_loopback or addr.is_link_local) and not self._allow_private:
            return f"{host} is a private or internal address"
        return None


def enforce(policy: NavigationPolicy, url: str) -> None:
    """Raise if `policy` refuses `url`. The one place that turns a refusal
    reason into a typed error, so every navigation entry point — Browser.open(),
    Page.goto(), and its redirect-leg recheck — raises the same GripError
    instead of each growing its own ValueError/RuntimeError."""
    if reason := policy.check(url):
        raise GripError(BrowserError(
            type=ErrorType.NAVIGATION_REFUSED,
            message=f"navigation refused: {reason}",
            confidence=1.0,
            recovery=[],
        ))
