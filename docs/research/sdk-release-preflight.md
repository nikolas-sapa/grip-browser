# SDK release preflight

Test plan before build/publication:

1. Local build yields exactly 1 wheel and 1 sdist for 0.8.5; twine reports 0 metadata errors.
2. Runtime, pyproject, newest changelog and tag versions all equal 0.8.5.
3. Distribution files contain 0 gripsearch, web or test package files; installed wheel imports without optional provider SDKs; CLI prints grip-browser 0.8.5 and exits 0.
4. Unit coverage >=80%; all offline browser/gripsearch tests and Python 3.11-3.14 CI pass; independent Python/security review have 0 blockers.
5. Merge retains reviewed tree. Production deployment is Ready on exact merge commit; canonical URL returns HTTP 200.
6. Existing tag-triggered trusted-publisher workflow completes every job; PyPI reports 0.8.5 and downloadable wheel imports with runtime version 0.8.5. Published wheel Python source matches release commit.

Implementation: bounded patch release through existing workflow after verified fixes; no new publisher, credentials or workflow architecture. Keep all artifacts in session scratch, publish only the reviewed merge commit.

Non-goals: paid provider calls, model/default/dependency changes, gripsearch release, public outreach, deleting branches/tags or replacing published artifacts.
