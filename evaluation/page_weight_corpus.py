"""URLs for the page-weight evaluation.

`docs/research/proxy-pricing.md` measured 0.50 MB/page and built the whole
proxy-cost conclusion on it — but that figure came from a developer-documentation
corpus assembled for the reach evaluation, never validated as representative of
what a real user of this tool would fetch. This corpus exists to check that.

Five categories, ~10 URLs each, picked to cover the actual spread of pages a
retrieval tool gets pointed at, not just the docs corpus this project already had:

  docs        — developer documentation (the inherited, unvalidated assumption)
  news        — news / media homepages, generally JS- and ad-heavy
  ecommerce   — product pages and category/home pages, images + anti-bot heavy
  blog        — long-form articles, text-heavy, few widgets
  reference   — Wikipedia, arXiv, government/standards docs, mostly static text

All URLs were checked with a plain `curl` before being added (2026-08-06); a
network-level check does not guarantee a browser succeeds (anti-bot walls
routinely pass real-Chrome UAs and reject curl's TLS fingerprint, or vice
versa) — `run_page_weight.py` records real pass/fail per URL and excludes
non-loads from the category means, it does not trust this pre-check.
"""

CORPUS: list[tuple[str, str]] = [
    # ── docs: developer documentation ──────────────────────────────────────────
    ("docs", "https://docs.python.org/3/library/asyncio.html"),
    ("docs", "https://developer.mozilla.org/en-US/docs/Web/API/Fetch_API"),
    ("docs", "https://react.dev/learn"),
    ("docs", "https://vuejs.org/guide/introduction.html"),
    ("docs", "https://nodejs.org/api/fs.html"),
    ("docs", "https://kubernetes.io/docs/concepts/overview/"),
    ("docs", "https://docs.docker.com/get-started/introduction/"),
    ("docs", "https://pkg.go.dev/fmt"),
    ("docs", "https://doc.rust-lang.org/book/ch01-00-getting-started.html"),
    ("docs", "https://tailwindcss.com/docs/installation"),

    # ── news: media homepages ────────────────────────────────────────────────
    ("news", "https://www.bbc.com/news"),
    ("news", "https://www.cnn.com"),
    ("news", "https://www.nytimes.com"),
    ("news", "https://www.theguardian.com/international"),
    ("news", "https://apnews.com"),
    ("news", "https://www.npr.org"),
    ("news", "https://www.aljazeera.com"),
    ("news", "https://techcrunch.com"),
    ("news", "https://www.forbes.com/"),
    ("news", "https://www.usatoday.com/"),

    # ── ecommerce: product / category pages, image + anti-bot heavy ─────────────
    ("ecommerce", "https://www.amazon.com/dp/B0BSHF7WHW"),
    ("ecommerce", "https://www.target.com/"),
    ("ecommerce", "https://www.walmart.com/"),
    ("ecommerce", "https://www.costco.com/"),
    ("ecommerce", "https://www.etsy.com/listing/1502896997"),
    ("ecommerce", "https://www.ebay.com/itm/166432958505"),
    ("ecommerce", "https://www.newegg.com/p/N82E16824012019"),
    ("ecommerce", "https://www.zappos.com/p/nike-air-force-1-07-white-white/product/7132478/color/2"),
    ("ecommerce", "https://www.homedepot.com/p/100136456"),
    ("ecommerce", "https://www.ikea.com/us/en/p/malm-bed-frame-high-white-00447678/"),

    # ── blog: long-form articles, text-heavy ─────────────────────────────────
    ("blog", "https://overreacted.io/writing-resilient-components/"),
    ("blog", "https://paulgraham.com/greatwork.html"),
    ("blog", "https://martinfowler.com/articles/patterns-of-distributed-systems/"),
    ("blog", "https://blog.cloudflare.com/"),
    ("blog", "https://seths.blog/"),
    ("blog", "https://waitbutwhy.com/2015/01/artificial-intelligence-revolution-1.html"),
    ("blog", "https://www.joelonsoftware.com/2000/04/06/things-you-should-never-do-part-i/"),
    ("blog", "https://danluu.com/keyboard-latency/"),
    ("blog", "https://jvns.ca/"),
    ("blog", "https://blog.pragmaticengineer.com/software-engineering-salaries-in-the-netherlands-and-europe/"),

    # ── reference: encyclopedic, academic, government / standards ────────────
    ("reference", "https://en.wikipedia.org/wiki/Python_(programming_language)"),
    ("reference", "https://en.wikipedia.org/wiki/Large_language_model"),
    ("reference", "https://arxiv.org/abs/1706.03762"),
    ("reference", "https://arxiv.org/abs/2005.11401"),
    ("reference", "https://www.w3.org/TR/html52/"),
    ("reference", "https://www.rfc-editor.org/rfc/rfc9110"),
    ("reference", "https://www.irs.gov/forms-pubs/about-form-1040"),
    ("reference", "https://www.usa.gov/"),
    ("reference", "https://www.congress.gov/bill/118th-congress/house-bill/1"),
    ("reference", "https://www.gpo.gov/"),
]
