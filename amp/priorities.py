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


def composite_stock_ranks(panel, priority_scores, factors_present, top_n=20):
    """Rank stocks under the latest inferred priorities.

    Weights = positive part of latest priority scores, normalized. A stock's
    composite = weighted mean of its member-factor ranks per priority.
    Downstream of diagnosis, by design.
    """
    latest_date = panel["date"].max()
    latest_ps = priority_scores[priority_scores["date"] == latest_date]
    if latest_ps.empty:
        latest_date_ps = priority_scores["date"].max()
        latest_ps = priority_scores[priority_scores["date"] == latest_date_ps]
    weights = latest_ps.set_index("priority")["priority_score"].clip(lower=0)
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
