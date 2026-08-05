"""URLs for the silent-failure evaluation.

Every page here returns HTTP 200 (or, where noted, a status a naive pipeline would
still treat as "fine"). The question is not whether the fetch succeeded at the
transport level — it did — but whether the *content* is what it appears to be.

Categories:
  consent_wall  — a cookie/consent interstitial served instead of the page.
  js_shell      — an app shell that renders nothing without JS. Static fetch gets
                  the skeleton, not the content.
  soft_404      — a client-routed app that returns 200 + its homepage/app-shell
                  for a path that does not exist, instead of a real 404.
  anti_bot      — a bot-detection page swapped in for the real content.
  control       — genuinely good pages. Included so the benchmark can produce
                  false positives: grip must NOT flag these as failed.

`expect_failure` is the ground truth, set by hand after inspecting each page's
actual extracted text (see the eval's console output) — not inferred from the
category label alone.
"""

CORPUS: list[tuple[str, str, bool]] = [
    # ── consent / interstitial walls: 200, plausible-length text, wrong content ──
    ("consent_wall", "https://www.google.com/search?q=cdp+protocol", True),
    ("consent_wall", "https://www.linkedin.com/pulse/topics/home/", True),

    # ── JS-required shells: 200, near-empty without a renderer ───────────────────
    ("js_shell", "https://excalidraw.com/", True),
    ("js_shell", "https://web.telegram.org/a/", True),

    # ── soft 404: client router returns 200 + app shell for a nonexistent path ──
    ("soft_404", "https://angular.dev/some-totally-fake-page-xyz", True),
    ("soft_404", "https://linear.app/some-totally-fake-page-xyz", True),

    # ── anti-bot: bot-check page swapped in for the real one ────────────────────
    ("anti_bot", "https://www.reddit.com/r/Python/", True),

    # ── control: real pages, real content, should not be flagged ────────────────
    ("control", "https://en.wikipedia.org/wiki/Retrieval-augmented_generation", False),
    ("control", "https://docs.python.org/3/library/dataclasses.html", False),
    ("control", "https://peps.python.org/pep-0008/", False),
    ("control", "https://developer.mozilla.org/en-US/docs/Web/API/Fetch_API", False),
    ("control", "https://angular.dev/overview", False),
]
