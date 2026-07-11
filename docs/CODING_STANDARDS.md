# Coding Standards

- Python 3.11+
- Type hints for public functions
- `pytest` for tests
- `ruff` for linting and formatting
- No core production logic in notebooks
- No hard-coded API keys, paths, universes, or provider-specific constants
- Structured logs with run identifiers
- Deterministic random seeds in tests
- Explicit exceptions for data-quality failures
- Small modules with clear data contracts
- Research behavior changes require tests and documentation
