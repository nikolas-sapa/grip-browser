# Proxy pricing — does it break the cost model?

**Headline: no, and the reason is not the one anybody expected. Bandwidth per page
was measured, not assumed, and this project's own content pages load 0.50 MB each —
roughly five times lighter than the median web page. At that weight, pay-as-you-go
residential proxies at $4/GB add $0.016/query, taking the total from $0.025 to
$0.041, still under Tavily's $0.049. The conclusion survives at ~$4/GB and below.**

**But it survives conditionally, and the condition is the corpus.** Substitute the
median page on the open web (2.41 MB, HTTP Archive) and the same $4/GB residential
proxy costs $0.075/query, total $0.100 — twice Tavily. The cost model is not robust
to what it fetches. It holds for a developer-documentation retrieval product and
fails for a general-web one. `04-cost-latency.md` itself said the proxy question
"cannot be phrased sharply until ticket 02 establishes which sites actually get
fetched" — that is still true, and **this document resolves the open question in the
favourable direction by inheriting a dev-docs corpus. That inherited, unvalidated
assumption is the single input that swings the answer by 6x in either direction.**

There is also a tier that looks like it makes the whole question go away: **ISP
proxies billed per IP rather than per GB.** Oxylabs sells 10 ISP IPs for $16/month
with a 50 GB/IP/month fair-use allowance — 500 GB for $16, or $0.032/GB, which is
$0.0001/query. Two orders of magnitude below the cheapest metered residential rate.
That figure is a **bandwidth-side floor only**: on 10 IPs it implies ~4,200 page
fetches per IP per day, and this project has already measured Bing degrading after
~30 requests from one IP. Requests-per-IP, not GB-per-IP, is likely the binding
constraint, and it is unpriced. See §5.

The honest caveat that outranks all the arithmetic: **the tier that is cheap is the
tier that gets blocked, and the tier that is expensive does not reliably solve
blocking either.** See "What proxies actually buy" below.

---

## 1. The critical number: bandwidth per page fetch

This is the one input the whole question turns on, so it was **measured, not
estimated**.

### Method

A scratchpad script drove this project's own CDP engine (`grip/cdp/engine.py`,
`grip/cdp/launcher.py` — no Playwright involved), enabled the `Network` domain, and
summed `Network.loadingFinished.encodedDataLength` across every request of a page
load. That field is bytes on the wire including headers, which is exactly what a
proxy meters. `ChromeLauncher` already allocates a fresh temp `--user-data-dir` per
launch, so every measurement is a cold cache — the correct assumption for a rotating
proxy, where a new IP has no cache to reuse. One Chrome launch per URL per arm.
5-second settle after `Page.navigate`. Two full runs, 2026-08-05.

The blocking arm used `Fetch.enable` at `requestStage: "Request"` and failed every
request whose `resourceType` was `Image`, `Font`, `Media` or `Stylesheet` with
`BlockedByClient`. **JavaScript was deliberately not blocked** — the reach evaluation
established that content ships in the initial HTML, so blocking JS turns this into a
static fetcher and deletes the differentiator entirely. Script bytes stay in every
figure below.

Corpus: 8 URLs matching the mix in `04-cost-latency.md` (static docs, a heavy wiki
page, two SPAs, a news site, an aggregator, a Cloudflare-protected page). Not the
identical bench list — that script was not in the tree — so this is a comparable set,
not the same one.

### Measured — bytes on the wire, MB

| URL | full | blocked |
|---|---|---|
| example.com | 0.000 | 0.000 |
| en.wikipedia.org/wiki/Python_(programming_language) | 0.649 | 0.443 |
| docs.python.org/3/library/asyncio.html | 0.032 | 0.020 |
| react.dev/learn | 1.010 | 0.748 |
| vuejs.org/guide/introduction.html | 0.374 | 0.124 |
| news.ycombinator.com | 0.011 | 0.009 |
| www.bbc.com/news | 0.884 / 0.975 | 0.866 / 0.936 |
| stackoverflow.com/questions/tagged/python | 0.311 / 0.135 | 0.142 / 0.199 |
| **total, 8 pages** | **3.27 / 3.19** | **2.35 / 2.48** |
| **mean per page, all 8** | **0.40** | **0.30** |
| **mean per page, content pages only (6)** | **0.50** | **0.37** |

Two values where the runs differed materially. bbc.com varies with its own lazy-load
timing; stackoverflow.com varies because it is serving a Cloudflare interstitial of
varying size, not the page.

**The all-8 mean is not the right number to price against.** `example.com` is a
473-byte control URL carried over from a latency bench, and
`stackoverflow.com/questions/tagged/python` never loaded a page at all — it is a
Cloudflare interstitial, confirmed below. Neither is a page fetch a retrieval product
would pay a proxy for. Excluding both gives **0.501 MB/page full, 0.374 MB/page
blocked** (per-run: 0.493 / 0.509 and 0.368 / 0.380), and that is the figure the
pricing tables use. Excluding `news.ycombinator.com` as well (11 KB, an unusually
light aggregator) pushes the full-arm mean to ~0.60 MB/page, which matters: it moves
Oxylabs' entry $6/GB residential tier from marginal to failing.

Resource-type split of the full arm (run 1, all 8 pages, MB): Script 1.53, Font 0.88,
Document 0.33, Image 0.26, Stylesheet 0.21, XHR 0.03, other 0.03.

### The finding inside the finding

**Resource blocking only saves ~25%** here (all 8 pages: 3.23 → 2.42 MB; content
pages only: 0.501 → 0.374 MB/page), against the 60–70% the
scraping literature advertises. The reason is visible in the type split: this corpus
is *script*-heavy, not *image*-heavy. Images are 8% of bytes. The single largest
blockable item is fonts (0.88 MB, 27%), not images. Blocking is worth doing — it is
free — but on a documentation corpus it is not the lever it is usually sold as.

The two tables also do not reconcile, and the gap is real: blockable types sum to
1.35 MB (fonts 0.88 + images 0.26 + stylesheets 0.21) but realised savings were only
0.85 MB. **Blocking induces compensating fetches** — bbc.com issued *more* requests
with blocking on (43 vs 33), because failed loads trigger retries and fallback paths.
Assume roughly a third of the nominal blockable bytes are clawed back.

### The general web, for contrast (retrieved, not measured here)

HTTP Archive Web Almanac 2025, page-weight chapter: desktop median total **2,412 KB**;
median by type — images 1,058 KB, JS 697 KB, fonts 139 KB, CSS 82 KB, HTML 22 KB.
Mobile median 2,164 KB.
<https://almanac.httparchive.org/en/2025/page-weight> (retrieved 2026-08-05).

Removing images and fonts from the desktop median gives **~1.2 MB/page blocked**.
That is an *estimate*, and a rough one: per-type medians do not sum to the total
median, and the arithmetic ignores that. It is used below only as an order-of-
magnitude upper bound.

**So: 0.50 MB/page measured on this corpus' content pages, 2.41 MB/page published for
the median web page — a ~5x spread. Every conclusion below is stated against both.**

---

## 2. Prices retrieved

All figures retrieved **2026-08-05**. Prices change; re-check before relying on any
of them. Advertised rates are often discounted ("50% off") and the undiscounted rate
is roughly double.

### Residential — metered per GB

| Provider | Rate | Commitment | Source |
|---|---|---|---|
| Bright Data | $4.00/GB PAYG (list $8) | none | [pricing/proxy-network](https://brightdata.com/pricing/proxy-network) |
| Bright Data | $3.50 / $3.00 / $2.50 per GB at $499 / $999 / $1,999 per month | monthly | same |
| Oxylabs | $6/GB (5 GB, $30/mo) → $2.50/GB (1 TB, $2,500/mo) | monthly | [residential-proxy-pool](https://oxylabs.io/products/residential-proxy-pool) |
| Decodo | $3.75/GB (3 GB) → $2.75/GB (100 GB) | monthly | [decodo pricing](https://decodo.com/proxies/residential-proxies/pricing) |
| Decodo | $4.00/GB PAYG on the grid; **$8.50/GB** via Wallet credits per their FAQ | none | same |
| IPRoyal | "from $1.75/GB", traffic never expires | none stated | [iproyal.com/pricing](https://iproyal.com/pricing/) |
| SOAX | Tier-1 countries: $5.00/GB free sandbox, $3.00/GB at $200/mo, $2.20 at $500, $1.50 at $1,500, $0.85 at $3,000 | **hard monthly minimums** | [soax.com/pricing](https://soax.com/pricing) |
| Webshare | $3.50/GB (1 GB) → $2.25/GB (100 GB, $225/mo) → $1.40/GB (3 TB) | monthly | [webshare.io/pricing](https://www.webshare.io/pricing) |

No-commitment options: Bright Data PAYG, Decodo PAYG, IPRoyal, Webshare's small tiers.
SOAX is the outlier — its useful rates are gated behind $200–$3,000/month floors.

Decodo's two conflicting PAYG numbers ($4.00 on the grid, $8.50 in the Wallet FAQ)
are reproduced as found. Both are used below as a range.

### Datacenter

| Provider | Rate | Metering | Source |
|---|---|---|---|
| Webshare | $0.0299/IP/mo (100 IPs = $2.99) → $0.0179/IP at 60k IPs; 10 IPs + 1 GB free forever | **per IP, but bandwidth-capped** — see below | [webshare.io/pricing](https://www.webshare.io/pricing) |
| Oxylabs | shared rotating **$0.59/GB** (20 GB = $11.80/mo), "from $0.44/GB" at volume | per GB | [datacenter-proxies](https://oxylabs.io/products/datacenter-proxies) |
| Oxylabs | dedicated $2.25/IP/mo (3 IPs = $6.75), "from $1.20"; shared $1.20/IP (10 = $12), "from $0.70" | per IP | same |
| Bright Data | $1.80/IP/mo (10 IPs) → $1.30/IP (1,000 IPs) | per IP | [pricing/proxy-network](https://brightdata.com/pricing/proxy-network) |
| IPRoyal | "from $1.39/proxy", "unlimited bandwidth" | per IP | [iproyal.com/pricing](https://iproyal.com/pricing/) |

**Webshare's per-IP datacenter pricing is not unmetered by default.** Their Fair Usage
Policy states unlimited-bandwidth plans carry "a guaranteed minimum threshold of
10 TB", scaling at 1 TB per $10 of subscription up to $1,000 and 1 TB per $20 above
it, with throttling from ~100 Mbps down to as low as 2 Mbps past the threshold. Search
results indicate unlimited bandwidth requires 1,000 premium / 100 private / 75
dedicated proxies. <https://help.webshare.io/en/articles/10599445-fair-usage-policy>
(retrieved 2026-08-05). **The exact bandwidth included on a $2.99 100-IP plan was not
confirmed from a primary source — treat the $2.99 figure as unverified for
bandwidth-heavy use.**

### ISP / static residential — the middle tier

| Provider | Rate | Bandwidth | Source |
|---|---|---|---|
| **Oxylabs** | $16/mo for 10 IPs ($1.60/IP) → $130 for 100 → $600 for 500 | **"unlimited with fair usage": 100 concurrent sessions per IP up to 50 GB/IP/month, then 10 concurrent sessions for the rest of the cycle** | [isp-proxies](https://oxylabs.io/products/isp-proxies) |
| Bright Data | $1.40/IP/mo (10 IPs) → $0.90/IP (1,000) | not stated on the pricing page | [pricing/proxy-network](https://brightdata.com/pricing/proxy-network) |
| Webshare | $0.30/IP/mo (20 IPs = $6) → $0.255/IP (2,000 = $510) | "unlimited bandwidth available" | [webshare.io/pricing](https://www.webshare.io/pricing) |
| IPRoyal | "from $1.80/proxy" | not stated | [iproyal.com/pricing](https://iproyal.com/pricing/) |

Oxylabs' ISP tier is the one number with a **stated, primary-source bandwidth
allowance**, which is why the arithmetic below leans on it rather than on Webshare's
cheaper but unspecified plans.

Oxylabs' front pricing page lists ISP as "starts from $16" with no unit — the product
page resolves that as $16/month for 10 IPs. Their "Web Unblocker from $9.4" carries no
resolvable unit and is not used here.

---

## 3. The arithmetic

Baseline from `04-cost-latency.md`: grip $0.025/query, Tavily $0.049/query.

**Headroom to parity: $0.049 − $0.025 = $0.024/query**, which at 8 pages/query is
**$0.003/page**.

Break-even bandwidth = ($0.003 ÷ price-per-GB) × 1024 MB/GB:

| Rate | Break-even MB/page | Measured 0.50 MB/page | Web median 2.41 MB/page |
|---|---|---|---|
| $8.50/GB (Decodo Wallet PAYG) | 0.36 | **fails** | fails |
| $6.00/GB (Oxylabs 5 GB) | 0.51 | **at break-even** (0.501 vs 0.512) | fails |
| $4.00/GB (Bright Data PAYG) | 0.77 | passes | fails |
| $2.75/GB (Decodo 100 GB) | 1.12 | passes | fails |
| $2.00/GB (Decodo 1 TB) | 1.54 | passes | fails |
| $1.75/GB (IPRoyal) | 1.76 | passes | fails |
| $0.59/GB (Oxylabs shared DC) | 5.21 | passes | **passes** |

The $6/GB row is the interesting one: it clears by 2%, which is inside the noise of a
two-run measurement. Drop `news.ycombinator.com` from the corpus and it fails. Treat
$6/GB residential as break-even, not headroom.

Per-query proxy cost, 8 pages, at the four bandwidth assumptions:

| Rate | grip corpus full (4.01 MB) | grip corpus blocked (2.99 MB) | web median full (19.3 MB) | web median blocked (~9.7 MB, est.) |
|---|---|---|---|---|
| $8.50/GB | $0.0333 | $0.0248 | $0.1602 | $0.0807 |
| $6.00/GB | $0.0235 | $0.0175 | $0.1131 | $0.0570 |
| $4.00/GB | $0.0157 | $0.0117 | $0.0754 | $0.0380 |
| $2.75/GB | $0.0108 | $0.0080 | $0.0518 | $0.0261 |
| $1.75/GB | $0.0069 | $0.0051 | $0.0330 | $0.0166 |
| $0.59/GB (DC) | $0.0023 | $0.0017 | $0.0111 | $0.0056 |
| Oxylabs ISP per-IP | **$0.0001** | $0.0001 | $0.0006 | $0.0003 |

Worked example for the ISP line: $16/month buys 10 IPs × 50 GB fair-use = 500 GB.
At 4.01 MB/query that is 500 × 1024 ÷ 4.01 ≈ **128,000 queries/month**, so
$16 ÷ 128,000 = **$0.0001/query**. It is a *volume* argument — at 1,000 queries/month
the same $16 is $0.016/query and the tier is pointless — and, per §5, a bandwidth-side
floor that a request-rate ceiling may dominate.

**Every metered figure above is a nominal rate, and understates the bill.** Bandwidth
spent on a request that gets blocked is still billed, so effective cost = nominal ÷
success rate. At 80% success that is a 1.25x multiplier; at 40% (the rate vendors
claim for datacenter IPs on protected sites) it is 2.5x, which is enough on its own to
move the cheap datacenter tier out of the money. **No success rate was measured here,
so no multiplier is applied in the tables — but the true cost is above every number in
them.**

### Totals, added to the $0.025 model

| Configuration | proxy | total | vs Tavily $0.049 |
|---|---|---|---|
| No proxy (current claim) | $0 | $0.025 | 0.51x |
| Oxylabs ISP per-IP, at ≥100k queries/mo | $0.0001 | $0.0251 | 0.51x |
| Datacenter metered $0.59/GB, blocked | $0.0017 | $0.0267 | 0.54x |
| IPRoyal residential $1.75/GB, blocked | $0.0051 | $0.0301 | 0.61x |
| Decodo residential $2.75/GB, full | $0.0108 | $0.0358 | 0.73x |
| Bright Data residential $4/GB PAYG, full | $0.0157 | $0.0407 | 0.83x |
| Oxylabs residential $6/GB entry tier, full | $0.0235 | $0.0485 | **0.99x — break-even** |
| Decodo Wallet PAYG $8.50/GB, full | $0.0333 | $0.0583 | **1.19x — breaks** |
| **Web-median pages**, $4/GB residential, full | $0.0754 | $0.1004 | **2.05x — breaks** |
| **Web-median pages**, $4/GB residential, blocked | $0.0380 | $0.0630 | **1.29x — breaks** |
| **Web-median pages**, $2/GB residential, blocked | $0.0190 | $0.0440 | 0.90x — survives |

---

## 4. What proxies actually buy — the part the arithmetic cannot price

This is where the cost model stops being the binding constraint.

**Measured in this project, and re-confirmed today:** a request to
`stackoverflow.com/questions/tagged/python` **from a residential IP** returns
Cloudflare's `Just a moment...` interstitial. Reproduced 2026-08-05 during this
research — `page_error` now correctly reports `ANTI_BOT_BLOCK` at confidence 0.88 with
`ROTATE_IDENTITY` recovery, so ticket 06's classifier fix has landed. Brave and
Startpage blocked on request 1. Bing degraded to bouncing every request after ~30
requests from one IP.

Two different failure modes are hiding in that list, and only one of them is a proxy
problem:

1. **Rate limiting** (Bing after ~30 requests). IP rotation genuinely fixes this, and
   fixing it does not require *good* IPs, only *many* IPs. The cheap per-IP tiers are
   sufficient.
2. **Anti-bot walls** (Cloudflare on StackOverflow, Brave, Startpage). These fired on
   a clean residential IP. Residential *proxy* IPs are shared, recycled across many
   customers, and typically carry *worse* reputation than an untouched home
   connection. **Nothing in this project's evidence supports the belief that paying
   $4/GB for residential proxies unblocks the pages that are actually blocked.** The
   reach evaluation reached the same place from the other direction: all four
   protected pages beat both the browser and static-fetch arms.

If that reading holds, the expensive tier is being priced for a job it does not do,
and the model should carry cheap rotation for rate limits and simply record hard
blocks as failures — which is what a correct `page_error` is for.

**Vendor claims about datacenter viability, labelled as such.** Massive (a proxy
vendor) publishes residential IPs succeeding on protected sites "around 85 to 99%" of
the time against "roughly 20 to 40%" for datacenter, and explicitly annotates it
"Massive vendor benchmark, not independent research" —
<https://www.joinmassive.com/blog/why-ai-agents-get-blocked-on-datacenter-ips-and-how-to-fix-it>,
published 2026-06-04, retrieved 2026-08-05. Similar block-rate figures circulate
across several proxy vendors' blogs. **All of it is marketing from parties who profit
from the conclusion, and none of it was independently verified here.** Cloudflare's
own bot-score documentation
(<https://developers.cloudflare.com/bots/concepts/bot-score/>, retrieved 2026-08-05)
describes only "request features (headers, session characteristics, and browser
signals)" and does **not** publicly enumerate ASN or hosting-provider reputation as a
signal. So the widely-repeated claim that datacenter IPs are detected by ASN is
plausible and universally asserted, but is not established by any primary source
cited here.

Proxyway's PMR 2026 benchmark reports residential *infrastructure* success rates of
99.93% (Oxylabs) and 99.92% (Decodo), lowest 95.28% (NetNut) —
<https://proxyway.com/best/residential-proxies> (retrieved 2026-08-05). That measures
whether the proxy network delivers the request, **not** whether Cloudflare lets it
through, and should not be read as an anti-bot success rate.

---

## 5. Answers

**Does "cheaper than Tavily" survive residential proxies?**
On this project's measured corpus, **yes at ~$4/GB and below** — pay-as-you-go
$4/GB takes $0.025 → $0.041 against Tavily's $0.049. It is at break-even at Oxylabs'
$6/GB entry tier ($0.0485) and **fails** at Decodo's $8.50/GB Wallet rate ($0.058).
On general-web page weights it **fails** at every residential rate above ~$2/GB even
with resource blocking.

**Break-even point.** $0.003/page of headroom. At $4/GB that is **0.77 MB/page**;
measured is 0.50 MB/page, so roughly 1.5x of headroom on this corpus. At $6/GB
break-even is 0.51 MB/page against a measured 0.50 — no headroom at all. At $8.50/GB
break-even is 0.36 MB/page, comfortably exceeded.

**Does it survive datacenter proxies?** On cost, comfortably — $0.0014–0.0019/query
metered, effectively zero per-IP. On *function*, unproven and probably not, for the
targets that matter. Datacenter IPs are the cheapest tier and the most likely to be
blocked, and this project has no measurement of its own on that question.

**Is there a configuration where the economics work?** Yes, and it is not the one the
task suggested. Ranked:

1. **ISP/static-residential billed per IP** (Oxylabs $16/mo, 10 IPs, 50 GB/IP/mo
   stated allowance) — $0.0001/query at ≥100k queries/month, residential-grade IP
   reputation, no per-GB metering to optimise against. **This is the answer only if
   request-rate-per-IP holds up.** 128,000 queries/month across 10 IPs is ~4,200 page
   fetches per IP per day, and the one rate-limit fact this project owns is Bing
   bouncing everything after ~30 requests from a single IP. If a target's tolerance is
   in that region, the tier must be priced on *IPs needed to stay under the per-IP
   request ceiling*, not on GB — 100 IPs is $130/month, 500 is $600, and at that point
   per-query cost is set by whatever rate ticket 02 establishes. The bandwidth-side
   figure is a floor, not a forecast.
2. **Resource blocking everywhere** — free, saves ~25% measured here (more on
   image-heavy targets), and costs nothing but a few lines of `Fetch.enable`. Never
   block JS.
3. **Cheap rotation for rate limits, hard failure for anti-bot walls.** Do not buy
   expensive residential bandwidth to defeat Cloudflare; the evidence says it does not
   work, and `page_error` reporting the block honestly is worth more than a proxy bill
   that hides it.
4. Datacenter-with-residential-fallback (the configuration the task asked about)
   *should* work economically — the fallback is only paid on the minority of requests
   that get blocked. But it cannot be priced without a measured block rate per tier,
   which does not exist here. Do not build it on vendor block-rate marketing.

---

## 6. Limitations

- **Every measurement bias here points the same way — toward "survives."** The 5-second
  settle truncates slow pages, `encodedDataLength` understates what a proxy bills,
  blocked-request bandwidth is not costed, and the all-8 mean included a control URL
  and an interstitial. Each of these pushes MB/page down and headroom up. They are not
  four independent caveats; they are one systematic optimistic bias, and the true
  numbers are above every figure in §3. The content-pages-only mean removes the
  largest single component of it; the rest remain.
- **Bandwidth was measured on 8 URLs, two runs, one machine, one residential IP, one
  day.** It is a small, developer-documentation-weighted corpus, deliberately matched
  to `04-cost-latency.md` so the numbers compose. It is explicitly *not*
  representative of the web; the Almanac column exists precisely because of that gap.
- **The bench URL list is comparable to, not identical with, the one used in
  `04-cost-latency.md`** — that script was not in the tree.
- **A 5-second settle truncates slow pages.** bbc.com in particular is still fetching
  lazy-loaded assets past that window, so its figure is a floor. Longer settles would
  push MB/page up and headroom down.
- **`encodedDataLength` is bytes on the wire from Chrome's perspective.** A real proxy
  meters its own accounting, which typically includes CONNECT overhead and TLS
  handshakes and may round up. Assume measured figures understate billed bandwidth by
  some single-digit percentage.
- **Blocked-arm figures for the general web (~1.2 MB/page) are estimated**, by
  subtracting the Almanac's per-type medians from its total median. Per-type medians
  do not sum to the total median. Order of magnitude only.
- **No proxy was purchased, signed up for, or tested.** Every price is from a public
  pricing page; no rate was verified at checkout, and advertised discounts ("50% off")
  may not persist. No claim here rests on a measured proxy success rate, because none
  was measured.
- **Coverage of the requested provider list is incomplete.** Decodo's public pricing
  pages surface residential rates only — no datacenter and no ISP tier was found, so
  those rows are absent rather than omitted. SOAX's pricing page likewise lists only
  residential. Both gaps are gaps in what the vendor publishes, not judgements that
  the products do not exist.
- **The Webshare $2.99/100-IP datacenter figure is not confirmed to include usable
  bandwidth.** If it is metered tightly, the cheapest datacenter line in the table is
  wrong.
- **Block rates by proxy tier are entirely unmeasured.** The one anti-bot data point
  this project owns is that a clean residential IP gets blocked. Everything else about
  which tier survives Cloudflare or Akamai is vendor marketing, flagged as such above.
  **This is the single largest gap, and it is the one that decides whether proxies are
  worth buying at all** — the cost question turns out to be the easy one.
- **The $0.025 baseline itself carries assumptions** — 8 pages/query, 20,400 tokens,
  Haiku 4.5 pricing, $0.12/hr compute — all from `04-cost-latency.md`. Proxy cost is
  added on top of them, not independently verified.

---

*Retrieved and measured 2026-08-05. Measurement script was written to the session
scratchpad, not to this repository.*
