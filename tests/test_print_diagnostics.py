import os

import print_diagnostics
from adaptive_market_priority_engine import main as run_engine


def test_print_diagnostics_shows_non_surviving_pairs(tmp_path, capsys):
    out = str(tmp_path / "out")
    rc = run_engine(["--synthetic", "--seed", "42", "--output", out])
    assert rc == 0

    print_diagnostics.main(["--output", out])
    captured = capsys.readouterr().out

    # the known-planted, FDR-surviving pair is present
    assert "fcf_yield" in captured
    assert "credit_spread_z" in captured
    # and so are non-surviving pairs -- the whole point is showing everything
    assert "False" in captured  # some rows have significant_fdr == False
    assert "Latest per-factor rolling stats" in captured


def test_print_diagnostics_handles_missing_output_gracefully(tmp_path):
    empty_dir = str(tmp_path / "empty")
    os.makedirs(empty_dir)
    rc = print_diagnostics.main(["--output", empty_dir])
    assert rc == 0
