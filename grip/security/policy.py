from __future__ import annotations

import ipaddress
from urllib.parse import urlparse

# The metadata addresses are the ones that matter on a cloud runner:
# 169.254.169.254 is the AWS/GCP/Azure instance metadata endpoint, 169.254.170.2
# is ECS's. Reaching either from a page the agent was told to visit hands out
# credentials.
_METADATA_HOSTS = {"169.254.169.254", "169.254.170.2", "metadata.google.internal"}


class NavigationPolicy:
    """Decides what a grip browser may open.

    Fail-closed by default: http(s) to public addresses only. Callers that
    genuinely drive a local dev server or read local files opt in per-Browser.
    A default-open policy makes every "summarize this URL" feature an SSRF plus
    a local-file read.

    Two residual gaps, stated plainly rather than implied away:

    * A DNS name is resolved inside Chrome, so this policy never sees the
      address the request lands on. `internal.corp.example` pointing at
      10.0.0.5 passes. Pinning the resolved IP would mean resolving here and
      forcing Chrome onto that address; that is out of scope.
    * Only the URL handed to open() is checked. A public URL that 302s to
      169.254.169.254 is not caught — redirects happen inside Chrome, same
      blind spot.

    So this closes the direct-navigation hole, not the whole SSRF class.
    """

    def __init__(self, allow_private: bool = False, allow_file: bool = False) -> None:
        self._allow_private = allow_private
        self._allow_file = allow_file

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
        if host in _METADATA_HOSTS:
            return f"{host} is a cloud metadata endpoint"
        if host == "localhost" or host.endswith(".localhost"):
            if not self._allow_private:
                return "localhost is not allowed (pass allow_private=True to permit)"
            return None
        try:
            addr = ipaddress.ip_address(host)
        except ValueError:
            # A DNS name — see the class docstring for why this is a pass.
            return None
        if (addr.is_private or addr.is_loopback or addr.is_link_local) and not self._allow_private:
            return f"{host} is a private or internal address"
        return None
