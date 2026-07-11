# Product Requirements Document

## Primary user
A financially sophisticated, non-technical investor who should not need to maintain code, databases, APIs, or scheduled jobs.

## Primary command
“Run the Market Priority Report.”

## Required behavior
1. Fetch current and historical market, fundamental, and macro data from configured providers.
2. Apply point-in-time availability rules.
3. Validate coverage and freshness.
4. Run the existing diagnosis pipeline.
5. Compare the latest output with the prior published run.
6. Generate Markdown and machine-readable JSON outputs.
7. Store the report and audit metadata.
8. Return a plain-English summary with explicit uncertainty.

## User stories
- As a user, I can request the latest report without uploading files.
- As a user, I can ask what changed since the prior rebalance.
- As a user, I can ask why a ticker ranks highly or poorly.
- As a user, I can see when data is stale, missing, or unreliable.
- As a user, I can reproduce any published report from its stored inputs and configuration.

## MVP scope
- Universe: configurable U.S. large-cap list, initially 50–100 names
- Rebalance: quarterly
- Prices: daily adjusted prices
- Fundamentals: quarterly, with filing/availability dates where provider supports them
- Macro: FRED or equivalent official sources
- One scheduled refresh plus on-demand execution
- Markdown, CSV, and JSON reports

## Out of scope for MVP
- Live trading or order execution
- Intraday signals
- Portfolio optimization
- Claims of causal inference
- Full institutional survivorship-free coverage unless a provider supplies it
