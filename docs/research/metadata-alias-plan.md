# Metadata address aliases

## Acceptance tests before implementation

1. Both metadata IPv4 addresses, each in dotted IPv4-mapped IPv6 and hexadecimal IPv4-mapped IPv6, over HTTP and HTTPS with allow_private either false or true: 16 refusals, zero permitted URLs.
2. Typed enforcement for each mapped address raises NAVIGATION_REFUSED before any browser command.
3. Existing public and opt-in private mapped-address behavior retains its contract; existing policy tests have zero regressions.
4. Real local Chrome loads mapped loopback aliases via an IPv4 server, establishing that these forms identify reachable IPv4 endpoints. Zero actual metadata requests.

5. Three metadata hosts with one DNS root dot across HTTP/HTTPS and both private-address modes: 12 refusals. Two localhost aliases refuse by default and permit only with private opt-in. Real Chrome default localhost-dot vulnerability reproduced with one local GET before fix.

## Implementation

Normalize parsed IPv4-mapped IPv6 addresses to their embedded IPv4 before metadata and private-address checks. Keep metadata denial independent of allow_private. Remove one DNS root dot before canonical IPv4/metadata/localhost checks, matching verified Chrome-equivalent names.

## Non-goals

No DNS rebinding resolution, proxy/firewall changes, WebSocket coverage claim, new dependencies or actual cloud metadata requests.
