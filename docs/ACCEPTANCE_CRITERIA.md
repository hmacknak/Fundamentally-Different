# Acceptance Criteria

## Phase 0 complete when
- Fresh checkout can install and run synthetic and null controls from documented commands.
- CI passes deterministic tests.
- Existing output files are reproducible within defined tolerances.
- No critical research formula is untested.

## MVP complete when
- A scheduled job obtains real data without manual uploads.
- A full research run produces report, CSV, JSON, audit trail, and data-quality output.
- Failed or stale data blocks publication.
- The latest valid report is retained and queryable.
- A non-technical user can trigger the workflow from one action or one natural-language request.
- Secrets, provider errors, and costs are documented.

## Not considered complete
- A notebook requiring manual execution
- A script that assumes local CSV uploads
- A dashboard that displays synthetic data as live
- A report without reproducible input snapshots
