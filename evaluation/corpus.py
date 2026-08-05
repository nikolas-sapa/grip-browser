"""URLs for the reach evaluation.

Chosen to be *unfavourable* as often as favourable. If the corpus were only
JavaScript-heavy sites the result would be rigged, and a rigged benchmark is worth
less than none: the first person to check would find it and stop believing anything
else on the page.

Categories:
  static      — server-rendered HTML. Static fetch should win or tie. Included so
                the benchmark can lose.
  spa         — client-rendered. The hypothesis says static fetch fails here.
  hybrid      — server-rendered shell, meaningful content hydrated client-side.
  protected   — anti-bot or consent walls. Neither arm may succeed; measured anyway
                because pretending they do not exist would inflate the result.
"""

CORPUS: list[tuple[str, str]] = [
    # ── static: server-rendered, static fetch should do fine ──────────────────
    ("static", "https://en.wikipedia.org/wiki/Retrieval-augmented_generation"),
    ("static", "https://en.wikipedia.org/wiki/Headless_browser"),
    ("static", "https://docs.python.org/3/library/asyncio-task.html"),
    ("static", "https://docs.python.org/3/library/dataclasses.html"),
    ("static", "https://arxiv.org/abs/2005.11401"),
    ("static", "https://arxiv.org/abs/1706.03762"),
    ("static", "https://peps.python.org/pep-0008/"),
    ("static", "https://news.ycombinator.com"),
    ("static", "https://lwn.net/"),
    ("static", "https://developer.mozilla.org/en-US/docs/Web/API/Fetch_API"),
    ("static", "https://www.gnu.org/software/bash/manual/bash.html"),
    ("static", "https://textual.textualize.io/"),

    # ── spa: client-rendered ──────────────────────────────────────────────────
    ("spa", "https://react.dev/learn"),
    ("spa", "https://react.dev/reference/react/useEffect"),
    ("spa", "https://vuejs.org/guide/introduction.html"),
    ("spa", "https://angular.dev/overview"),
    ("spa", "https://svelte.dev/docs/svelte/what-are-runes"),
    ("spa", "https://zustand.docs.pmnd.rs/getting-started/introduction"),
    ("spa", "https://ui.shadcn.com/docs"),
    ("spa", "https://tanstack.com/query/latest/docs/framework/react/overview"),
    ("spa", "https://www.chromatic.com/"),

    # ── hybrid: server shell, client-hydrated content ─────────────────────────
    ("hybrid", "https://nextjs.org/docs/app/getting-started/installation"),
    ("hybrid", "https://vercel.com/docs/functions"),
    ("hybrid", "https://www.bbc.com/news"),
    ("hybrid", "https://github.com/python/cpython"),
    ("hybrid", "https://github.com/microsoft/playwright/blob/main/README.md"),
    ("hybrid", "https://pypi.org/project/requests/"),
    ("hybrid", "https://stackoverflow.blog/"),
    ("hybrid", "https://www.reddit.com/r/Python/"),

    # ── protected: anti-bot / consent walls ───────────────────────────────────
    ("protected", "https://stackoverflow.com/questions/tagged/python"),
    ("protected", "https://www.google.com/search?q=cdp+protocol"),
    ("protected", "https://search.brave.com/search?q=cdp+protocol"),
    ("protected", "https://www.linkedin.com/pulse/topics/home/"),
]
