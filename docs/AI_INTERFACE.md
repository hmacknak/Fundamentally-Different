# AI Interface Contract

## Supported intents
- Run latest Market Priority Report
- Explain current priorities
- Compare current versus prior rebalance
- Explain a ticker ranking
- Show factor contribution and uncertainty
- Report data-quality limitations

## Required API outputs
- `report_id`
- `as_of_date`
- `status`
- `data_freshness`
- `priority_scores`
- `factor_scores`
- `interaction_survivors`
- `top_ranked_securities`
- `changes_since_prior`
- `warnings`
- `audit_reference`

## Guardrails
- The AI must distinguish stored calculation results from narrative interpretation.
- It must not imply causation.
- It must surface stale or incomplete data before discussing rankings.
- It must never claim that a report is live unless the underlying run completed successfully.
