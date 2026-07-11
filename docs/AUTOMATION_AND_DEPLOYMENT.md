# Automation and Deployment

## User experience goal
The owner performs no recurring technical work.

## MVP deployment
- GitHub repository for code and version control
- GitHub Actions for tests and scheduled orchestration
- Managed database or durable object storage
- Serverless job or low-cost container for heavier research runs
- Secrets stored in GitHub Actions or cloud secret management

## Schedules
- Daily: price and macro refresh; check for new filings
- Weekly: data-quality and freshness audit
- Quarterly: full rebalance and publish report
- On demand: authenticated endpoint or manual GitHub workflow trigger

## Failure behavior
- Never overwrite the last valid published report with a failed run.
- Publish a failure summary containing missing data, stale series, and failing checks.
- Retry transient provider errors with bounded backoff.
- Alert only when action is required.

## AI integration
The calculation service should expose a stable JSON result and report artifact. ChatGPT or Claude can explain that output, but the service remains the source of truth.

## Cost target
MVP infrastructure should be designed for low usage and remain roughly within tens of dollars per month excluding premium fundamental data.
