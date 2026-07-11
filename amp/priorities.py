"""Market priority scoring.

Priorities are inferred from factor evidence, never asserted. Because factors are
shared across priorities (by design — the same characteristic can serve multiple
market objectives), we also publish the overlap matrix so nobody mistakes
correlated diagnoses for independent ones.
"""
import numpy as np
import pandas as pd

PRIORITY_MAP = {
    "Cash generation": ["fcf_yield", "free_cash_flow_margin", "operating_margin"],
    "Balance sheet strength": ["debt_to_equity_inv", "interest_coverage", "fcf_yield"],
    "Growth scarcity": ["revenue_growth", "eps_revision", "momentum_6m", "roe"],
    "Valuation discipline": ["earnings_yield", "ev_ebitda_inv", "fcf_yield"],
    "Risk avoidance": ["low_volatility", "low_beta", "debt_to_equity_inv", "dividend_yield"],
    "Inflation protection": ["gross_margin", "operating_margin", "revenue_growth",
                             "commodity_sensitivity"],
    "Capital discipline": ["fcf_yield", "shares_dilution_inv", "roe"],
}


def score_priorities(rolled_scores, factors_present):
    """Priority score = mean rolling IC of member factors present, per date.

    Also carries mean rolling spread, the count of members with evidence, and
    a cross-priority z-score per date for relative comparison.
    """
    fs = rolled_scores.set_index(["date", "factor"])
    rows = []
    for dt in rolled_scores["date"].unique():
        for prio, members in PRIORITY_MAP.items():
            present = [m for m in members if m in factors_present]
            ics, spreads, strengths = [], [], []
            for m in present:
                try:
                    r = fs.loc[(dt, m)]
                except KeyError:
                    continue
                if pd.notna(r["rolling_ic"]):
                    ics.append(r["rolling_ic"])
                    spreads.append(r["rolling_spread"])
                    strengths.append(r["strengthening_4p"])
            if not ics:
                continue
            rows.append({
                "date": dt, "priority": prio,
                "priority_score": float(np.mean(ics)),
                "priority_spread": float(np.nanmean(spreads)),
                "strengthening": (float(np.nanmean(strengths))
                                  if any(pd.notna(x) for x in strengths) else np.nan),
                "n_members_scored": len(ics),
                "n_members_defined": len(members),
            })
    ps = pd.DataFrame(rows)
    if ps.empty:
        return ps
    ps["priority_z"] = ps.groupby("date")["priority_score"].transform(
        lambda s: (s - s.mean()) / s.std() if s.std() > 0 else s * 0)
    return ps.sort_values(["date", "priority_score"], ascending=[True, False])


def overlap_matrix(factors_present):
    """Jaccard overlap of member-factor sets between priorities (evidence sharing)."""
    prios = list(PRIORITY_MAP.keys())
    sets = {p: set(m for m in PRIORITY_MAP[p] if m in factors_present) for p in prios}
    mat = pd.DataFrame(index=prios, columns=prios, dtype=float)
    for a in prios:
        for b in prios:
            u = sets[a] | sets[b]
            mat.loc[a, b] = (len(sets[a] & sets[b]) / len(u)) if u else np.nan
    return mat


WEIGHT_SMOOTHING_PERIODS = 4


def composite_stock_ranks(panel, priority_scores, factors_present, top_n=20, as_of_date=None,
                          weight_smoothing_periods=WEIGHT_SMOOTHING_PERIODS):
    """Rank stocks under the inferred priorities as of `as_of_date` (default:
    the latest date in `panel`).

    Weights = positive part of the trailing mean of priority scores over the
    last `weight_smoothing_periods` dates (default 4 quarters) up to and
    including the ranking date, normalized. A stock's composite = weighted
    mean of its member-factor ranks per priority. Downstream of diagnosis,
    by design.

    Weight smoothing (2026-07-11, see docs/DECISIONS.md): using only the
    single latest snapshot let one hot quarter's IC -- e.g. a momentum-driven
    spike in Growth scarcity -- dominate portfolio weight, which then
    re-ranks even more heavily by trailing momentum next quarter
    (a self-reinforcing "chasing" loop). Averaging over several trailing
    quarters is standard practice for damping single-period noise in a
    weighting scheme and only ever looks backward from the ranking date, so
    it stays trailing-only / leakage-free like the rest of this module.

    Passing an explicit `as_of_date` supports walk-forward evaluation
    (amp/walkforward.py): ranking stocks using only the priority scores
    available at that historical date. Unlike the default (latest) path,
    an explicit date that has no matching priority_scores row returns empty
    rather than falling back to priority_scores' own max date -- silently
    substituting a *different* date here would leak future information into
    a historical evaluation.
    """
    is_explicit = as_of_date is not None
    latest_date = as_of_date if is_explicit else panel["date"].max()
    latest_ps = priority_scores[priority_scores["date"] == latest_date]
    weight_anchor_date = latest_date
    if latest_ps.empty:
        if is_explicit:
            return pd.DataFrame(), pd.Series(dtype=float), latest_date
        weight_anchor_date = priority_scores["date"].max()
        latest_ps = priority_scores[priority_scores["date"] == weight_anchor_date]

    trailing_dates = sorted(d for d in priority_scores["date"].unique() if d <= weight_anchor_date)
    window_dates = trailing_dates[-weight_smoothing_periods:]
    window_ps = priority_scores[priority_scores["date"].isin(window_dates)]
    weights = window_ps.groupby("priority")["priority_score"].mean().clip(lower=0)
    if weights.sum() <= 0:
        weights = pd.Series(1.0, index=latest_ps["priority"])
    weights = weights / weights.sum()

    g = panel[panel["date"] == latest_date].set_index("ticker")
    comp = pd.Series(0.0, index=g.index)
    contrib = {}
    for prio, w in weights.items():
        members = [m + "_rank" for m in PRIORITY_MAP[prio]
                   if m in factors_present and (m + "_rank") in g.columns]
        if not members:
            continue
        prio_rank = g[members].mean(axis=1, skipna=True)
        comp = comp.add(w * prio_rank, fill_value=0)
        contrib[prio] = prio_rank
    out = pd.DataFrame({"composite_score": comp}).dropna()
    for prio, s in contrib.items():
        out[f"score__{prio.replace(' ', '_').lower()}"] = s
    out = out.sort_values("composite_score", ascending=False)
    out["rank"] = np.arange(1, len(out) + 1)
    out["as_of_date"] = latest_date
    return out.head(top_n).reset_index(), weights, latest_date
