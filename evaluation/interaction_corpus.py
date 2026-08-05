"""URLs for the interaction-to-reveal evaluation.

`page.read(interact=True)` (shipped 0.3.0) clicks "show more"/"load more"/expander
controls, or scrolls, before extracting. This is the last untested hypothesis from
the reach evaluation (see README.md): if rendered-DOM reach is disproven, interaction
is the only place a browser might still see content static fetch cannot.

Corpus design was the hard part. ~25 candidates were probed by hand before this list
was fixed (Wikipedia navboxes, GitHub PR diffs, IMDb, old.reddit, YouTube descriptions,
Discourse forums, native <details> docs pages, SaaS pricing-FAQ accordions...) and
the large majority did **not** gate anything: modern accordions are usually built by
CSS height/max-height animation, not by removing the answer from the DOM, so
`.innerText` (what `read()` reads) already contains the "collapsed" text before any
click happens. Only Stripe's API reference pages ("Show child attributes" on nested
object schemas) were confirmed, by eyeballing the actual added block text, to
genuinely add content to the DOM on click. That imbalance is itself part of the
result, not a corpus-selection artifact — see INTERACTION.md.

Categories:
  api_reference — verified positive: clicking "Show child attributes" expanders adds
                  real DOM nodes with real schema-field text (checked by hand).
  accordion_ui  — pages with visible FAQ/accordion/expander controls that *look* like
                  they should gate content (and get clicked by `_reveal_step`) but do
                  not: the answer text was already present pre-click. These are the
                  false-positive stress test — controls with interactive UI, included
                  specifically because a plain "no interactive elements" control page
                  would be too easy to pass.
  control       — ordinary content pages with no interaction affordance at all.
"""

CORPUS: list[tuple[str, str]] = [
    # ── api_reference: verified — click adds real schema text (see INTERACTION.md) ──
    ("api_reference", "https://docs.stripe.com/api/charges/object"),
    ("api_reference", "https://docs.stripe.com/api/customers/object"),
    ("api_reference", "https://docs.stripe.com/api/payment_intents/object"),
    ("api_reference", "https://docs.stripe.com/api/subscriptions/object"),

    # ── accordion_ui: has expand/FAQ controls, verified NOT to gate content ─────────
    ("accordion_ui", "https://www.notion.com/pricing"),
    ("accordion_ui", "https://slack.com/pricing"),
    ("accordion_ui", "https://github.com/pricing"),
    ("accordion_ui", "https://www.squarespace.com/pricing"),
    ("accordion_ui", "https://www.hubspot.com/pricing/marketing"),

    # ── control: no interactive reveal affordance at all ────────────────────────────
    ("control", "https://en.wikipedia.org/wiki/Barack_Obama"),
    ("control", "https://docs.python.org/3/library/asyncio-task.html"),
    ("control", "https://react.dev/learn"),
    ("control", "https://caniuse.com/"),
    ("control", "https://github.com/sindresorhus/awesome"),
]
