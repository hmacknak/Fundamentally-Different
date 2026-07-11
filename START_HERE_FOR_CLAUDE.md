# Start Here for Claude Code

1. Read `CLAUDE.md` and all referenced documents.
2. Run the existing synthetic and null controls unchanged.
3. Inspect `data_adapters.py` but assume it has not been live-tested.
4. Create tests that lock down current research behavior.
5. Prepare the first small PR: reproducible installation, tests, configuration, and CI hardening.
6. Do not attempt full cloud deployment or vendor integration in the first PR.

The owner is non-technical. Do not ask them to edit code, terminals, environment files, or databases. Present choices in business terms, recommend a default, and automate setup wherever credentials are not legally or technically unavoidable.
