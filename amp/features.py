"""Panel construction with point-in-time discipline.

Rules enforced here:
- Fundamentals only enter a rebalance date after `fundamental_lag_days` (reporting lag).
- Macro states use expanding z-scores (no full-sample look-ahead).
- Forward returns are benchmark-relative (excess) by default.
"""
import numpy as np
import pandas as pd

from .stats_utils import expanding_zscore, pct_rank, winsorize_series

TRADING_DAYS_3M = 63
TRADING_DAYS_6M = 126
TRADING_DAYS_1Y = 252

# factors where "lower is better" get inverted at construction
FACTOR_COLUMNS = [
    "fcf_yield", "free_cash_flow_margin", "operating_margin", "gross_margin",
    "debt_to_equity_inv", "interest_coverage", "roe", "revenue_growth",
    "eps_revision", "shares_dilution_inv", "earnings_yield", "ev_ebitda_inv",
    "dividend_yield", "momentum_6m", "low_volatility", "low_beta",
    "commodity_sensitivity",
]

MACRO_STATE_COLUMNS = [
    "credit_spread_z", "rate_10y_z", "rate_10y_chg_3m", "curve_z",
    "cpi_yoy_z", "vix_z", "bench_trend_6m", "wti_chg_6m",
]


def build_price_matrix(prices):
    px = prices.pivot(index="date", columns="ticker", values="adj_close").sort_index()
    return px


def compute_price_features(px, bench, rebalance_dates, holding_days):
    """Momentum, vol, beta, forward returns (raw + excess) at each rebalance date."""
    rets = px.pct_change()
    bench_rets = bench.pct_change()
    idx = px.index
    rows = []
    for dt in rebalance_dates:
        i = idx.get_indexer([dt])[0]
        j = i + holding_days
        if i < TRADING_DAYS_1Y or j >= len(idx):
            continue
        window_1y = rets.iloc[i - TRADING_DAYS_1Y:i]
        bwin_1y = bench_rets.iloc[i - TRADING_DAYS_1Y:i]
        bvar = bwin_1y.var()
        p_now = px.iloc[i]
        p_back6 = px.iloc[i - TRADING_DAYS_6M]
        p_fwd = px.iloc[j]
        b_fwd_ret = bench.iloc[j] / bench.iloc[i] - 1.0
        mom = p_now / p_back6 - 1.0
        vol = window_1y.iloc[-TRADING_DAYS_6M:].std() * np.sqrt(252)
        beta = window_1y.apply(lambda c: c.cov(bwin_1y)) / bvar if bvar > 0 else pd.Series(np.nan, index=px.columns)
        fwd = p_fwd / p_now - 1.0
        df = pd.DataFrame({
            "ticker": px.columns,
            "momentum_6m": mom.values,
            "low_volatility": (-vol).values,
            "low_beta": (-beta).values,
            "forward_return": fwd.values,
            "forward_excess_return": (fwd - b_fwd_ret).values,
        })
        df["date"] = dt
        df["benchmark_forward_return"] = b_fwd_ret
        rows.append(df)
    return pd.concat(rows, ignore_index=True)


def compute_commodity_sensitivity(px, wti_monthly, rebalance_dates):
    """Rolling 12m correlation of monthly stock returns with WTI monthly changes."""
    mpx = px.resample("ME").last()
    mrets = mpx.pct_change()
    wchg = wti_monthly.pct_change()
    out = []
    for dt in rebalance_dates:
        window = mrets.loc[:dt].tail(12)
        wwin = wchg.reindex(window.index)
        if len(window) < 10 or wwin.notna().sum() < 10:
            continue
        corr = window.corrwith(wwin)
        df = pd.DataFrame({"ticker": corr.index, "commodity_sensitivity": corr.values})
        df["date"] = dt
        out.append(df)
    if not out:
        return pd.DataFrame(columns=["date", "ticker", "commodity_sensitivity"])
    return pd.concat(out, ignore_index=True)


def derive_fundamental_factors(f):
    f = f.copy()
    f["debt_to_equity_inv"] = -f["debt_to_equity"]
    f["earnings_yield"] = np.where(f["pe"] > 0, 1.0 / f["pe"], np.nan)
    f["ev_ebitda_inv"] = np.where(f["ev_ebitda"] > 0, 1.0 / f["ev_ebitda"], np.nan)
    if "shares_dilution" in f.columns:
        f["shares_dilution_inv"] = -f["shares_dilution"]
    return f


def asof_merge_fundamentals(panel, fundamentals, lag_days):
    """Point-in-time merge: at rebalance date t, use latest fundamentals dated <= t - lag."""
    panel = panel.copy()
    panel["asof_cutoff"] = panel["date"] - pd.Timedelta(days=lag_days)
    f = fundamentals.sort_values("date")
    panel = panel.sort_values("asof_cutoff")
    merged = pd.merge_asof(
        panel, f, left_on="asof_cutoff", right_on="date",
        by="ticker", suffixes=("", "_fund"),
    )
    merged["fundamental_date"] = merged["date_fund"]
    merged = merged.drop(columns=["date_fund", "asof_cutoff"])
    return merged.sort_values(["date", "ticker"]).reset_index(drop=True)


def build_macro_states(macro):
    """Expanding z-scores and changes — every state uses only history up to that date."""
    m = macro.sort_values("date").set_index("date")
    out = pd.DataFrame(index=m.index)
    if "credit_spread" in m:
        out["credit_spread_z"] = expanding_zscore(m["credit_spread"])
    if "rate_10y" in m:
        out["rate_10y_z"] = expanding_zscore(m["rate_10y"])
        out["rate_10y_chg_3m"] = m["rate_10y"].diff(3)
    if {"rate_10y", "rate_2y"}.issubset(m.columns):
        out["curve_z"] = expanding_zscore(m["rate_10y"] - m["rate_2y"])
    if "cpi_yoy" in m:
        out["cpi_yoy_z"] = expanding_zscore(m["cpi_yoy"])
    if "vix" in m:
        out["vix_z"] = expanding_zscore(m["vix"])
    if "benchmark_adj_close" in m:
        out["bench_trend_6m"] = m["benchmark_adj_close"].pct_change(6)
    if "wti_oil" in m:
        out["wti_chg_6m"] = m["wti_oil"].pct_change(6)
    return out.reset_index()


def attach_macro(panel, macro_states):
    ms = macro_states.sort_values("date")
    panel = panel.sort_values("date")
    return pd.merge_asof(panel, ms, on="date")


def rank_factors(panel, factors, sector_neutral=False):
    """Winsorize then percentile-rank each factor cross-sectionally per date."""
    panel = panel.copy()
    group_keys = ["date", "sector"] if (sector_neutral and "sector" in panel.columns) else ["date"]
    for fac in factors:
        if fac not in panel.columns:
            continue
        w = panel.groupby("date")[fac].transform(lambda s: winsorize_series(s))
        panel[fac + "_w"] = w
        panel[fac + "_rank"] = panel.groupby(group_keys)[fac + "_w"].transform(pct_rank)
    return panel


def available_factors(panel, min_coverage=0.4):
    """Factors with enough non-missing data to test."""
    out = []
    for fac in FACTOR_COLUMNS:
        col = fac + "_rank"
        if col in panel.columns and panel[col].notna().mean() >= min_coverage:
            out.append(fac)
    return out
