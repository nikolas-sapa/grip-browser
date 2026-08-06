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
scoping what actions an agent is allowed to take autonomously.

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
