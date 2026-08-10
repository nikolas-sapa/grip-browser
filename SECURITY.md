# Security Policy

## Reporting a Vulnerability

Report suspected vulnerabilities privately to **niksapa150@gmail.com**. Do
not open a public GitHub issue for security reports — this gives us time to
investigate and ship a fix before the issue is public.

Include, where possible:

- A description of the vulnerability and its impact
- Steps to reproduce, or a minimal proof of concept
- The grip version and environment (Python version, Chrome/Chromium version)

We aim to acknowledge reports within a few days and will keep you updated as
we work on a fix.

## Supported Versions

This project ships two PyPI packages, `grip-browser` and `grip-search`
(which depends on `grip-browser`). Both are pre-1.0 and evolving quickly.
Security fixes target the latest released version of each on PyPI. Older
versions are not backported.

| Package      | Version | Supported |
| ------------ | ------- | --------- |
| grip-browser | latest  | yes       |
| grip-browser | < latest| no        |
| grip-search  | latest  | yes       |
| grip-search  | < latest| no        |

## Threat Model

grip drives a real Chrome/Chromium instance and executes real JavaScript on
real pages. Any page it navigates to is, by construction, untrusted input:
it can run arbitrary script in its own page context, and its text content is
read back by your agent and can end up in front of an LLM. grip mitigates
specific parts of that surface (below); it does not sandbox the page beyond
what Chrome itself does, and it is not a substitute for running the browser
process with whatever OS-level isolation (containers, restricted user,
network egress rules) is appropriate for what your agent is allowed to do.

### Prompt-injection guard

`InjectionDetector` (`grip/security/injection.py`) is wired into
`page.read()` and snapshot text extraction (`grip/page.py`), so it runs
automatically on text pulled from the page before that text is handed back
to the caller. It looks for patterns commonly used to smuggle fake
conversation turns or override instructions into page content (e.g. fake
`system:` / `assistant:` turns, "ignore previous instructions", `[INST]`
markers) and strips the offending sentences from what it returns.

This is a best-effort mitigation, not a guarantee. It reduces the risk of a
malicious page hijacking your agent's instructions via its visible text, but
it is pattern-based, only covers the text paths above (not raw HTML,
screenshots, or anything you extract from the page yourself outside those
APIs), and can be bypassed by injections it doesn't recognize. Do not treat
it as a substitute for treating all page content as untrusted input, and for
scoping what actions an agent is allowed to take autonomously. See
[Residual risk](#residual-risk) for what the guard does and does not buy you.

### Sessions and cookies

`Browser.save_session(path)` writes every cookie from the browser instance
to `path` as plaintext JSON (`grip/browser.py`); `load_session(path)`
restores them. Cookies are session credentials — treat that file exactly
like you'd treat a saved auth token: don't commit it, don't share it, and
set your own filesystem permissions on it if the process umask isn't
restrictive enough for your environment, since grip does not narrow
permissions on the file it writes.

### `stealth=True`

`Browser(stealth=True)` (opt-in, off by default) removes two automation
tells: it clears `navigator.webdriver` and swaps out the `HeadlessChrome`
user-agent string (`grip/cdp/launcher.py`). It is deliberately not a full
evasion suite — it does not spoof canvas/WebGL fingerprints, timing
signals, or anything else sites use for more sophisticated bot detection.
Do not rely on it to bypass anti-bot systems; use it only where you have a
legitimate reason to reduce automation fingerprinting (e.g. testing your
own site's behavior) and the operator's terms of service permit automated
access.

**Measured once, 2026-08-10** (`evaluation/stealth_measurement.py`, single
run): reported tells fell from 10 to 4 on bot.sannysoft.com and from 3 to 0
on CreepJS. Those probes count the signals they choose to report, so this is
not evidence of being undetectable — a detector that scores rather than lists
may weigh signals those pages never surface. It was **not** run against any
live anti-bot system (no reCAPTCHA, no Cloudflare challenge, no commercial
bot manager), it is one machine / one Chrome build / one IP with unknown
run-to-run variance, and it says nothing about TLS/JA3. Fewer tells also does
not mean a site will admit you: IP reputation usually decides that and
neither flag affects it. (The competitor result that made detection *easier*
concerned page-world init-script shims, a different mechanism from these two
launch flags.)

### Challenge solving

`page.solve_challenge()` interacts with the challenge widget on the page
using pointer events grip dispatches itself. It calls no third-party
solving service and sends no page content anywhere. It reports `"solved"`
only when it can verify the outcome (a response token is present, or the
widget has left the DOM); an unverifiable attempt returns `"timeout"`, so
a caller is never told a challenge was cleared when it was not.

Solving a challenge on a site you do not operate may breach that site's
terms of service. That is your call to make, not grip's, and grip does not
make it for you: `solve_challenge()` is an explicit call that never runs
on its own, and it is blocked under `Browser(safe=True)` along with the
rest of the interaction surface (`click_at`, `drag`).

### Residual risk

These are limitations, not features. They are listed because knowing where the
guarantees stop is more useful than a list of what is defended.

**The DevTools endpoint is a same-user trust boundary.** grip launches Chrome
with its debugging port bound to loopback on a random port, with no
authentication, because CDP has none to offer. Any process running as the same
user can find that port, attach to the browser, read every cookie via
`Storage.getCookies`, and evaluate script in any tab. That is inherent to the
protocol and cannot be fixed inside the library. If the browser holds credentials
for something valuable, run it in a container or under a dedicated user rather
than alongside code you do not control.

**`NavigationPolicy` cannot see where a DNS name resolves.** Resolution happens
inside Chrome, after the policy check. The policy blocks non-http(s) schemes and
literal private, loopback and cloud-metadata addresses, which stops the direct
form of SSRF through an agent. It does not stop a hostname that resolves to one
of those addresses, because it never sees the resolved IP. Pinning resolved IPs
is out of scope and is not implemented. Treat the policy as a guard against a
model being talked into typing `http://169.254.169.254`, not as a network
boundary; enforce that at the network layer.

**The injection guard is a keyword filter, not a control.** It normalises
Unicode confusables, zero-width characters and irregular whitespace before
matching, which closed nine measured bypasses that previously walked straight
through. It still matches known phrasings. A novel phrasing gets past it, and no
amount of pattern work changes that. The real defense is the untrusted-data
framing the runner puts around page content in the prompt, which does not depend
on enumerating attacks in advance. Design your agent as though the filter were
absent: scope what actions it may take without a human, and assume any text from
a page is hostile.

**A `SIGKILL`ed process strands its temp profile directory.** grip removes the
profile on shutdown from `terminate()`, and a normal exit, exception or
`SIGTERM` all reach it. `SIGKILL` does not — the process never gets control, and
the directory is left behind for the OS or you to clean up.

### Boundary

TLS/JA3 fingerprints and full headless fingerprint parity are below the
DevTools Protocol and unreachable from a Python client driving stock
Chromium. grip does not attempt them and does not claim them. A block based
on IP reputation is an egress problem: route through a residential or mobile
proxy with `Browser(proxy=...)`, and match your locale and timezone to that
egress yourself.
