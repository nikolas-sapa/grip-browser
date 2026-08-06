"""Resource types an agent never reads.

An agent works from text and interactive elements; images, video and webfonts
are pure download cost. Blocking them is standard practice for automated
fetching, and the saving is not marginal — measured across 50 real pages, it
cuts a documentation page from 0.64 MB to 0.27 MB and a blog from 1.00 MB to
0.31 MB. Where bandwidth is billed (proxies), that is the difference between a
cost model that works and one that does not.

Not blocked: CSS and XHR/fetch. Layout affects which elements count as visible,
and content routinely arrives over XHR — blocking either would change what the
page *is*, not just what it weighs.
"""

BLOCKED_RESOURCE_PATTERNS: tuple[str, ...] = (
    # images
    "*.png", "*.jpg", "*.jpeg", "*.gif", "*.webp", "*.avif", "*.ico", "*.bmp",
    "*.svg",
    # fonts
    "*.woff", "*.woff2", "*.ttf", "*.otf", "*.eot",
    # media
    "*.mp4", "*.webm", "*.ogg", "*.mp3", "*.wav", "*.avi", "*.mov", "*.m4a",
)
