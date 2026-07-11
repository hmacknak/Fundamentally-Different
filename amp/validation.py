"""Data validation — fail loudly on critical issues, report everything else.

Audit-trail mindset: every input gets a quality report before it touches the model.
"""
import hashlib
import os

import pandas as pd

REQUIRED = {
    "prices": ["date", "ticker", "adj_close", "volume"],
    "fundamentals": ["date", "ticker", "fcf_yield", "debt_to_equity", "roe",
                     "revenue_growth", "pe", "ev_ebitda", "dividend_yield"],
    "macro": ["date"],
}

OPTIONAL_FUND = ["interest_coverage", "gross_margin", "operating_margin",
                 "free_cash_flow_margin", "eps_revision", "shares_dilution", "sector"]


class DataValidationError(Exception):
    pass


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _check(df, name, issues, criticals):
    req = REQUIRED[name]
    missing = [c for c in req if c not in df.columns]
    if missing:
        criticals.append(f"{name}.csv missing required columns: {missing}")
        return
    if df.empty:
        criticals.append(f"{name}.csv is empty")
        return
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    n_bad_dates = int(df["date"].isna().sum())
    if n_bad_dates:
        issues.append(f"{name}: {n_bad_dates} unparseable dates (rows dropped)")
        df.dropna(subset=["date"], inplace=True)

    if "ticker" in df.columns:
        dupes = int(df.duplicated(subset=["date", "ticker"]).sum())
        if dupes:
            issues.append(f"{name}: {dupes} duplicate (date, ticker) rows — keeping last")
            df.drop_duplicates(subset=["date", "ticker"], keep="last", inplace=True)
    else:
        dupes = int(df.duplicated(subset=["date"]).sum())
        if dupes:
            issues.append(f"{name}: {dupes} duplicate dates — keeping last")
            df.drop_duplicates(subset=["date"], keep="last", inplace=True)

    # missingness per column
    for c in df.columns:
        pct = df[c].isna().mean()
        if pct > 0.5:
            issues.append(f"{name}.{c}: {pct:.0%} missing (over half — treat results with caution)")
        elif pct > 0.15:
            issues.append(f"{name}.{c}: {pct:.0%} missing")

    if name == "prices":
        n_nonpos = int((df["adj_close"] <= 0).sum())
        if n_nonpos:
            issues.append(f"prices: {n_nonpos} non-positive adj_close rows dropped")
            df.drop(df.index[df["adj_close"] <= 0], inplace=True)


def validate_inputs(prices_path, fundamentals_path, macro_path, output_dir):
    """Load, validate, and report. Returns (prices, fundamentals, macro, audit_dict)."""
    issues, criticals = [], []
    frames = {}
    paths = {"prices": prices_path, "fundamentals": fundamentals_path, "macro": macro_path}
    for name, path in paths.items():
        if not os.path.exists(path):
            raise DataValidationError(f"Input file not found: {path}")
        df = pd.read_csv(path)
        df.columns = [c.strip().lower() for c in df.columns]
        _check(df, name, issues, criticals)
        frames[name] = df

    if criticals:
        raise DataValidationError("Critical data problems:\n- " + "\n- ".join(criticals))

    p, f, m = frames["prices"], frames["fundamentals"], frames["macro"]

    # coverage stats
    px_tickers = set(p["ticker"].unique())
    fd_tickers = set(f["ticker"].unique())
    only_px = sorted(px_tickers - fd_tickers)
    only_fd = sorted(fd_tickers - px_tickers)
    if only_px:
        issues.append(f"{len(only_px)} tickers have prices but no fundamentals (excluded): "
                      f"{only_px[:8]}{'...' if len(only_px) > 8 else ''}")
    if only_fd:
        issues.append(f"{len(only_fd)} tickers have fundamentals but no prices (excluded)")

    # staleness: median gap between fundamental observations per ticker
    gaps = (f.sort_values(["ticker", "date"]).groupby("ticker")["date"]
            .diff().dt.days.dropna())
    if len(gaps) and gaps.median() > 130:
        issues.append(f"fundamentals: median reporting gap {gaps.median():.0f} days "
                      f"(> quarterly) — check data frequency")

    audit = {
        "input_hashes": {k: file_sha256(v) for k, v in paths.items()},
        "row_counts": {k: int(len(frames[k])) for k in frames},
        "ticker_counts": {"prices": len(px_tickers), "fundamentals": len(fd_tickers),
                          "overlap": len(px_tickers & fd_tickers)},
        "date_ranges": {k: [str(frames[k]["date"].min().date()),
                            str(frames[k]["date"].max().date())] for k in frames},
        "issues": issues,
    }

    os.makedirs(output_dir, exist_ok=True)
    lines = ["# Data Quality Report", ""]
    lines.append(f"- Prices: {audit['row_counts']['prices']:,} rows, "
                 f"{audit['ticker_counts']['prices']} tickers, "
                 f"{audit['date_ranges']['prices'][0]} to {audit['date_ranges']['prices'][1]}")
    lines.append(f"- Fundamentals: {audit['row_counts']['fundamentals']:,} rows, "
                 f"{audit['ticker_counts']['fundamentals']} tickers")
    lines.append(f"- Macro: {audit['row_counts']['macro']:,} rows, "
                 f"{audit['date_ranges']['macro'][0]} to {audit['date_ranges']['macro'][1]}")
    lines.append(f"- Usable universe (price+fundamental overlap): "
                 f"{audit['ticker_counts']['overlap']} tickers")
    lines.append("")
    if issues:
        lines.append("## Issues found (non-critical)")
        lines += [f"- {i}" for i in issues]
    else:
        lines.append("No data quality issues detected.")
    with open(os.path.join(output_dir, "data_quality_report.md"), "w") as fh:
        fh.write("\n".join(lines) + "\n")

    return p, f, m, audit
