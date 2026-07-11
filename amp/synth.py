"""Synthetic market generator with PLANTED signals — the engine's control test.

Ground truth planted:
1. fcf_yield: positive payoff whose strength SCALES WITH credit spread stress
   (the 'internally funded businesses win when external capital is expensive' story).
2. revenue_growth: steady positive payoff, macro-independent.
3. Everything else: pure noise.

A trustworthy engine must recover (1) and (2) — and, within FDR tolerance,
nothing else. Recovery is checked automatically in the report.
"""
import json
import os

import numpy as np
import pandas as pd

SECTORS = ["Energy", "Financials", "Industrials", "Technology", "Healthcare", "Materials"]

GROUND_TRUTH = {
    "planted_effects": [
        {"factor": "fcf_yield", "type": "conditional",
         "conditioning_macro": "credit_spread_z",
         "base_quarterly_alpha_per_sd": 0.012, "macro_scaling": 0.018,
         "story": "FCF yield payoff strengthens when credit spreads are elevated"},
        {"factor": "revenue_growth", "type": "unconditional",
         "base_quarterly_alpha_per_sd": 0.018,
         "story": "Revenue growth carries a steady positive payoff"},
    ],
    "noise_factors": "all other fundamentals are AR(1) noise with zero return effect",
}


def _ar1(rng, n, mean, sd, phi=0.85):
    x = np.empty(n)
    x[0] = mean + rng.normal(0, sd)
    for i in range(1, n):
        x[i] = mean + phi * (x[i - 1] - mean) + rng.normal(0, sd * np.sqrt(1 - phi**2))
    return x


def generate(output_dir, n_tickers=60, start="2017-01-01", end="2026-01-02", seed=42, null_mode=False):
    rng = np.random.default_rng(seed)
    os.makedirs(output_dir, exist_ok=True)
    days = pd.bdate_range(start, end)
    months = pd.date_range(start, end, freq="ME")
    quarters = pd.date_range(start, end, freq="QE")
    n_d, n_m, n_q = len(days), len(months), len(quarters)

    # ---- macro (monthly) ----
    credit = np.clip(_ar1(rng, n_m, 1.6, 0.45, phi=0.9), 0.6, None)
    stress_idx = [i for i, d in enumerate(months) if ("2020-03" <= str(d)[:7] <= "2020-06")
                  or ("2018-10" <= str(d)[:7] <= "2018-12") or ("2022-06" <= str(d)[:7] <= "2022-11") or ("2025-03" <= str(d)[:7] <= "2025-06")]
    credit[stress_idx] += rng.uniform(1.2, 2.2, len(stress_idx))
    rate10 = np.clip(1.5 + np.linspace(0, 3.0, n_m) * (0.4 + 0.6 * rng.random())
                     + _ar1(rng, n_m, 0, 0.25, 0.9), 0.4, None)
    rate2 = np.clip(rate10 - _ar1(rng, n_m, 0.6, 0.5, 0.9), 0.05, None)
    cpi = np.clip(_ar1(rng, n_m, 3.2, 1.4, 0.93) + np.where(
        (months >= "2021-06") & (months <= "2022-12"), 3.0, 0.0), 0.2, None)
    vix = np.clip(_ar1(rng, n_m, 19, 5, 0.8), 10, None)
    vix[stress_idx] += rng.uniform(8, 22, len(stress_idx))
    wti = np.clip(65 * np.exp(np.cumsum(rng.normal(0.001, 0.07, n_m))), 20, None)
    gold = 1800 * np.exp(np.cumsum(rng.normal(0.004, 0.035, n_m)))
    cadusd = np.clip(_ar1(rng, n_m, 0.74, 0.02, 0.95), 0.6, 0.9)

    # ---- benchmark (daily) ----
    b_drift, b_vol = 0.07 / 252, 0.17 / np.sqrt(252)
    b_rets = rng.normal(b_drift, b_vol, n_d)
    m_of_day = pd.Series(days).dt.to_period("M")
    stress_months = set(str(months[i])[:7] for i in stress_idx)
    b_rets[np.array([str(p) in stress_months for p in m_of_day])] -= 0.0035
    bench = 4000 * np.exp(np.cumsum(b_rets))
    bench_m = pd.Series(bench, index=days).resample("ME").last().reindex(months).ffill().values

    macro = pd.DataFrame({"date": months, "benchmark_adj_close": bench_m,
                          "rate_10y": rate10, "rate_2y": rate2, "cpi_yoy": cpi,
                          "wti_oil": wti, "vix": vix, "credit_spread": credit,
                          "cadusd": cadusd, "gold": gold})

    # credit z for planting (expanding, mirrors what the engine will compute)
    cs = pd.Series(credit, index=months)
    cz = ((cs - cs.expanding(8).mean()) / cs.expanding(8).std()).fillna(0.0)

    # ---- fundamentals (quarterly, AR(1) around ticker-specific means) ----
    tickers = [f"SYN{i:03d}" for i in range(1, n_tickers + 1)]
    sectors = rng.choice(SECTORS, n_tickers)
    fund_rows = []
    fund_store = {}
    specs = {
        "fcf_yield": (0.05, 0.030, 0.012), "debt_to_equity": (0.8, 0.5, 0.08),
        "roe": (0.14, 0.08, 0.02), "revenue_growth": (0.08, 0.09, 0.04),
        "pe": (19, 8, 2.0), "ev_ebitda": (11, 4, 1.0), "dividend_yield": (0.02, 0.015, 0.003),
        "interest_coverage": (9, 5, 1.2), "gross_margin": (0.42, 0.12, 0.015),
        "operating_margin": (0.16, 0.07, 0.012), "free_cash_flow_margin": (0.09, 0.05, 0.012),
        "eps_revision": (0.0, 0.04, 0.03), "shares_dilution": (0.006, 0.012, 0.006),
    }
    for k, (mu, cross_sd, ts_sd) in specs.items():
        means = rng.normal(mu, cross_sd, n_tickers)
        paths = np.stack([_ar1(rng, n_q, m, ts_sd) for m in means])
        if k in ("pe", "ev_ebitda", "interest_coverage"):
            paths = np.clip(paths, 2.0, None)
        if k in ("dividend_yield", "gross_margin", "operating_margin"):
            paths = np.clip(paths, 0.0, None)
        fund_store[k] = paths
    for qi, q in enumerate(quarters):
        for ti, tk in enumerate(tickers):
            row = {"date": q, "ticker": tk, "sector": sectors[ti]}
            for k in specs:
                row[k] = round(float(fund_store[k][ti, qi]), 5)
            fund_rows.append(row)
    fundamentals = pd.DataFrame(fund_rows)

    # ---- stock prices (daily) with planted alpha ----
    betas = rng.normal(1.0, 0.25, n_tickers)
    idio_d = 0.10 / np.sqrt(63)
    # planted alpha per quarter uses PRIOR quarter fundamentals (reporting-lag realistic)
    fcf_z = np.zeros((n_tickers, n_q))
    rev_z = np.zeros((n_tickers, n_q))
    for qi in range(n_q):
        src = max(qi - 1, 0)
        f = fund_store["fcf_yield"][:, src]
        r = fund_store["revenue_growth"][:, src]
        fcf_z[:, qi] = (f - f.mean()) / f.std()
        rev_z[:, qi] = (r - r.mean()) / r.std()
    q_of_month = pd.PeriodIndex(months, freq="Q")
    # conditioning state for quarter q = expanding credit z at the LAST month of q-1
    # (identical information set to the engine's rebalance-date macro state)
    cz_last_of_q = pd.Series(cz.values, index=q_of_month).groupby(level=0).last()
    cz_q = cz_last_of_q.shift(1).fillna(0.0)
    day_q = pd.PeriodIndex(days, freq="Q")
    q_list = pd.PeriodIndex(quarters, freq="Q")
    q_pos = {q: i for i, q in enumerate(q_list)}
    days_in_q = pd.Series(day_q).map(pd.Series(day_q).value_counts()).values

    gt = GROUND_TRUTH["planted_effects"]
    a_fcf_base, a_fcf_scale = gt[0]["base_quarterly_alpha_per_sd"], gt[0]["macro_scaling"]
    a_rev = gt[1]["base_quarterly_alpha_per_sd"]
    if null_mode:
        a_fcf_base = a_fcf_scale = a_rev = 0.0

    prices_rows = []
    for ti, tk in enumerate(tickers):
        alpha_d = np.zeros(n_d)
        for di in range(n_d):
            q = day_q[di]
            qi = q_pos.get(q)
            if qi is None:
                continue
            credit_state = float(cz_q.get(q, 0.0))
            a_q = (a_fcf_base + a_fcf_scale * credit_state) * fcf_z[ti, qi] \
                  + a_rev * rev_z[ti, qi]
            alpha_d[di] = a_q / days_in_q[di]
        r = betas[ti] * b_rets + alpha_d + rng.normal(0, idio_d, n_d)
        px = rng.uniform(15, 220) * np.exp(np.cumsum(r))
        vol = rng.integers(2e5, 6e6, n_d)
        prices_rows.append(pd.DataFrame({"date": days, "ticker": tk,
                                         "adj_close": np.round(px, 4), "volume": vol}))
    prices = pd.concat(prices_rows, ignore_index=True)

    prices.to_csv(os.path.join(output_dir, "prices.csv"), index=False)
    fundamentals.to_csv(os.path.join(output_dir, "fundamentals.csv"), index=False)
    macro.to_csv(os.path.join(output_dir, "macro.csv"), index=False)
    gt_out = dict(GROUND_TRUTH)
    gt_out["null_mode"] = null_mode
    with open(os.path.join(output_dir, "ground_truth.json"), "w") as fh:
        json.dump(gt_out, fh, indent=2)
    return (os.path.join(output_dir, "prices.csv"),
            os.path.join(output_dir, "fundamentals.csv"),
            os.path.join(output_dir, "macro.csv"))
