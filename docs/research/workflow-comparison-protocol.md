# Repeatable workflow and controlled comparison

## Workflow candidate

A developer uses an existing agent harness to fill a multi-step request form, verify visible state, submit once and read its confirmation. Start with a sandbox owned by the developer, containing no real transactions or personal credentials. Required fields: text, checkbox and select; include a same-URL document replacement and a delayed confirmation.

This is a candidate for external use, not evidence of adoption. Existing local Chrome state/navigation/ambiguity regressions establish bounded component behavior. They do not establish that external developers complete this workflow.

## Acceptance criteria before execution

1. Fixture pilot: ten fresh browser sessions produce the expected field values, exactly one recorded submission and matching confirmation ID in 10/10 independently checked runs. Inject a lost response in ten further sessions: zero duplicate submissions, each uncertain outcome explicitly recorded.
2. External onboarding: three independent developers attempt their supplied sandbox workflow; at least two complete without creator intervention, and at least one independently repeats within seven days. Collect actual receipts with consent, not inferred adoption from downloads.
3. Matched comparison: three externally supplied task families, twenty runs per configuration (sixty attempts/tool). Preserve every failed, timed-out and ambiguous attempt in the denominator. Reserve held-out label/layout variations before tuning prompts.
4. Record exact package versions and source commit IDs for Grip, agent-browser, Playwright MCP and Chrome DevTools MCP before execution. Verify published artifacts against official primary sources at run time; never use an unpinned latest configuration. Stagehand/hosted tools require a separately approved provider/service budget.
5. Use the same outer harness, model, prompt, initial browser/profile state, observation limits and timeout/action budgets for equivalent narrow-tool configurations. Record schemas, output-file policy and nested inference. Compare autonomous runners separately.
6. Per attempt, retain independent final-state verdict, explicit termination reason, total model calls, exact reported input/output/cache/thought categories, unknown usage flags, browser/service charges, latency and interventions. Never substitute page-token estimates for model usage. Report completion counts, p50/p95 latency and failed-attempt costs.
7. Paid provider runs, external messages and real transactions require explicit authorization. Preparation creates zero paid calls and sends zero outreach messages.

## Implementation sequence

Obtain one developer-owned sandbox and exact task/outcome contract. Run an unpaid deterministic fixture pilot with the existing SDK. Validate independent success checks before introducing a model. Freeze the corpus and pin versions; review the approved run budget. Execute matched attempts, publish all denominators and limitations, then choose improvements from actual failure traces.

## Non-goals

No superiority headline from historical snapshot sizes, simulated developer adoption, cloud/vendor selection, model changes, production form submission or automatic retries of uncertain mutations.

## Current status

Protocol prepared. External sandbox, developers, current tool pins and paid-run budget not supplied. No external onboarding or current-version comparative result claimed.
