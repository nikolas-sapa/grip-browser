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

grip is pre-1.0 and evolving quickly. Security fixes target the latest
released version on PyPI. Older versions are not backported.

| Version | Supported |
| ------- | --------- |
| latest  | yes       |
| < latest| no        |

## Threat Model: Prompt-Injection Guard

grip's `InjectionDetector` (`grip/security/injection.py`) scans text pulled
from a live web page — page content that an untrusted third party (the site
owner, or anyone who can post content the agent will read) controls — before
it reaches the LLM. It looks for patterns commonly used to smuggle fake
conversation turns or override instructions into that content (e.g. fake
`system:` / `assistant:` turns, "ignore previous instructions", `[INST]`
markers) and strips the offending sentences from what gets passed to the
model.

This is a best-effort mitigation, not a guarantee. It reduces the risk of a
malicious page hijacking your agent's instructions via its visible text, but
it is pattern-based and can be bypassed by injections it doesn't recognize.
Do not treat it as a substitute for treating all page content as untrusted
input, and for scoping what actions an agent is allowed to take
autonomously.
