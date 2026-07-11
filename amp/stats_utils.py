"""Statistical utilities — deterministic, auditable, no black boxes."""
import numpy as np
from scipy import stats as sps


def ols_with_tstats(X, y):
    """OLS with intercept. Returns dict of beta, se, t, p (incl. intercept at idx 0)."""
    X = np.asarray(X, dtype=float)
    y = np.asarray(y, dtype=float)
    if X.ndim == 1:
        X = X.reshape(-1, 1)
    mask = np.isfinite(y) & np.all(np.isfinite(X), axis=1)
    X, y = X[mask], y[mask]
    n, k = X.shape
    dof = n - (k + 1)
    if dof < 3:
        return None
    X1 = np.column_stack([np.ones(n), X])
    XtX = X1.T @ X1
    try:
        XtX_inv = np.linalg.inv(XtX)
    except np.linalg.LinAlgError:
        return None
    beta = XtX_inv @ X1.T @ y
    resid = y - X1 @ beta
    s2 = float(resid @ resid) / dof
    cov = s2 * XtX_inv
    se = np.sqrt(np.diag(cov))
    with np.errstate(divide="ignore", invalid="ignore"):
        t = np.where(se > 0, beta / se, np.nan)
    p = 2.0 * sps.t.sf(np.abs(t), dof)
    return {"beta": beta, "se": se, "t": t, "p": p, "n": n, "dof": dof}


def bh_fdr(pvals):
    """Benjamini-Hochberg q-values. NaNs pass through as NaN."""
    p = np.asarray(pvals, dtype=float)
    q = np.full_like(p, np.nan)
    valid = np.isfinite(p)
    pv = p[valid]
    n = len(pv)
    if n == 0:
        return q
    order = np.argsort(pv)
    ranked = pv[order] * n / (np.arange(n) + 1)
    # enforce monotonicity from the largest p down
    ranked = np.minimum.accumulate(ranked[::-1])[::-1]
    qv = np.empty(n)
    qv[order] = np.clip(ranked, 0, 1)
    q[valid] = qv
    return q


def winsorize_series(s, lo=0.01, hi=0.99):
    """Clip a pandas Series at cross-sectional quantiles."""
    if s.notna().sum() < 5:
        return s
    lo_v, hi_v = s.quantile(lo), s.quantile(hi)
    return s.clip(lower=lo_v, upper=hi_v)


def pct_rank(s):
    """Percentile rank in [0, 1]."""
    return s.rank(pct=True)


def spearman_ic(factor_vals, fwd_returns, min_n=10):
    """Spearman rank IC. Returns (ic, n) or (nan, n)."""
    import pandas as pd
    df = pd.DataFrame({"f": factor_vals, "r": fwd_returns}).dropna()
    n = len(df)
    if n < min_n:
        return np.nan, n
    ic, _ = sps.spearmanr(df["f"], df["r"])
    return float(ic), n


def quintile_spread(factor_vals, fwd_returns, min_n=15):
    """Top-quintile mean forward return minus bottom-quintile mean."""
    import pandas as pd
    df = pd.DataFrame({"f": factor_vals, "r": fwd_returns}).dropna()
    n = len(df)
    if n < min_n:
        return np.nan
    ranks = df["f"].rank(pct=True)
    top = df.loc[ranks >= 0.8, "r"].mean()
    bot = df.loc[ranks <= 0.2, "r"].mean()
    return float(top - bot)


def expanding_zscore(s, min_periods=8):
    """Z-score of each obs vs its own expanding history (no look-ahead)."""
    mu = s.expanding(min_periods=min_periods).mean()
    sd = s.expanding(min_periods=min_periods).std()
    return (s - mu) / sd
