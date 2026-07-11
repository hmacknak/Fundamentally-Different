import os

import run_report


def test_run_report_blocks_and_exits_nonzero_on_empty_database(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/amp.db")
    output_dir = str(tmp_path / "out")

    rc = run_report.main(["--as-of", "2024-01-01", "--output", output_dir])

    assert rc == 1
    assert os.path.exists(os.path.join(output_dir, "data_quality_failure.md"))
