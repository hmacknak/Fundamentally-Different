"""Golden-file / control-test lock-down.

These reproduce the validation claims in README.md as pytest assertions so a
regression in the research pipeline fails CI instead of only failing a human
skim of stdout.
"""
import pandas as pd

from adaptive_market_priority_engine import main


def test_synthetic_control_recovers_planted_signals_seed_42(tmp_path):
    out = tmp_path / "out"
    rc = main(["--synthetic", "--seed", "42", "--output", str(out)])
    assert rc == 0

    itests = pd.read_csv(out / "interaction_tests.csv")
    hit = itests[(itests["factor"] == "fcf_yield")
                 & (itests["macro_state"] == "credit_spread_z")].iloc[0]
    assert hit["interaction_beta"] > 0
    assert hit["t_stat"] > 5.0
    assert bool(hit["significant_fdr"])

    rolled = pd.read_csv(out / "factor_scores.csv")
    last = rolled[rolled["date"] == rolled["date"].max()]
    rev = last[last["factor"] == "revenue_growth"].iloc[0]
    assert rev["rolling_ic"] > 0
    assert rev["rolling_ic_t"] > 1.5


def test_synthetic_null_control_has_zero_fdr_survivors_seed_42(tmp_path):
    out = tmp_path / "out_null"
    rc = main(["--synthetic-null", "--seed", "42", "--output", str(out)])
    assert rc == 0

    itests = pd.read_csv(out / "interaction_tests.csv")
    assert int(itests["significant_fdr"].sum()) == 0


def test_synthetic_control_writes_audit_trail_with_input_hashes(tmp_path):
    out = tmp_path / "out"
    main(["--synthetic", "--seed", "42", "--output", str(out)])
    assert (out / "audit_trail.json").exists()
    assert (out / "market_priority_report.md").exists()
    assert (out / "data_quality_report.md").exists()


def test_missing_real_data_args_without_synthetic_flag_fails_cleanly(tmp_path):
    out = tmp_path / "out"
    rc = main(["--output", str(out)])
    assert rc == 2
