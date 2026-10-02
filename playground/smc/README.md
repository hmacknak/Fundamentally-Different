# BOS/CHoCH retest backtest (SPY, 1-minute and higher)

Playground code: **not part of the audited AMPE pipeline.** It's isolated in
the same way as the rest of `playground/` (see `playground/README.md`). It
reads its own CSV or Yahoo download, not the AMPE database, and it never
feeds the Market Priority Report.

## Strategy

As specified by the user:

> "Buy when there is a break of structure and change of character, however
> only enter when price comes back to the change of character. Set the stop
> below the previous low and 1:1 RR for take profit. Reverse for shorts."

As implemented in `backtest_smc.py` (long side; shorts mirror it on negated prices):

1. **Swings:** fractal with `swing_n` bars on each side (default 5),
   confirmed `swing_n` bars later, so there is no lookahead.
2. **Bearish context:** last swing high < previous swing high AND last swing low < previous swing low.
3. **CHoCH:** a bar closes above the last (lower) swing high. That price is
   the CHoCH level. The lowest low since that swing high is the
   **origin low**. Each swing high can trigger only one CHoCH.
4. **BOS:** after the CHoCH, a new swing high forms and a bar closes above it.
   The BOS bar must fall between 09:35 and 15:30 ET.
5. **Entry:** limit buy at the CHoCH level, live from the bar after the BOS.
   It is cancelled after `max_armed_bars` (90), at `entry_end` (15:30), or if
   the origin low is broken.
6. **Stop:** origin low - `stop_buffer` ($0.01). **Target:** entry + `rr` x
   risk (1.0). Setups with $ risk outside [`min_risk` 0.10, `max_risk` 3.00]
   are skipped.
7. Only one position is held at a time, and any fill discards pending setups
   on both sides. Open trades are flattened at 15:55 ET. Structure resets
   every session from 1m to 5m. From 15m up it carries across sessions (see below).

## Fill and cost assumptions (conservative)

- If one bar touches both the stop and the target, the stop is assumed to hit first.
- On the fill bar itself, only the stop is checked; the target can't be hit until the next bar.
- Limits and targets fill on touch, and gaps fill at the open.
- Stops and flatten exits pay $0.01/share slippage. Commission is $0.005/share/side.
- Sizing risks 1% of equity per trade, capped at 4x leverage, starting from $100k.
  Because of the leverage cap, very tight stops carry less than 1% risk, so
  `total_net_r` (equal-weighted) and `return_pct` (dollar-weighted) can disagree in sign.
- Only regular hours are used (09:30 <= t < 16:00 ET). Naive timestamps are
  read as ET (`--tz` overrides this), and tz-aware ones are converted, which
  also handles files that span a DST change.
- Bars are assumed to be stamped at their **start**. If a vendor stamps bar
  end, session edges shift by one bar.

## Timeframes

For bars above 1m, `resample` builds them aligned to 09:30, and `params_for_tf` scales the settings:

- `swing_n` becomes `max(2, round(swing_n/sqrt(tf)))`.
- `min_risk` and `max_risk` are multiplied by `sqrt(tf)`.
- `max_armed_bars` becomes `max(3, round(90/tf))`.
- From 15m up, structure carries across sessions.

`--no-scale` turns all of this off. The scaling is a judgment call that
slightly confounds the timeframe comparison, so run both ways.

## Running it

```bash
pip install -r requirements.txt -r playground/requirements.txt
python playground/smc/backtest_smc.py --selftest
python playground/smc/run_spy.py                       # Yahoo, ~30 days of 1m bars
python playground/smc/run_spy.py --csv longer_export.csv
python playground/smc/backtest_smc.py data.csv --compare 1,5,15,30,60
python playground/smc/backtest_smc.py data.csv --timeframe 5 --plot-trades 10
```

Without a local setup, the **SMC backtest** GitHub Actions workflow
(`.github/workflows/smc-backtest.yml`) does the same thing:

- It runs whenever `playground/smc/**` changes, or from the Actions tab.
- The comparison table appears in the job summary.
- Trades, charts and the downloaded CSV are saved in the
  `smc-backtest-results` artifact, together with `data_provenance.json`
  (source and retrieval time).

## Verification

`tests/test_playground_smc.py` runs in the normal CI suite and covers:

- A hand-built long setup and its mirrored short: each gives exactly one
  trade at the expected entry and stop, worth exactly +1.0R gross.
- **Lookahead:** truncating the data and re-running reproduces every trade
  that had already closed, at 1m, 5m and 15m. Keep this test green after any engine change.
- A random walk shows no edge.
- One position at a time, no overnight holds, and correct resampling and CSV
  timezone handling (including across a DST change).

## Caveats before trusting any number

- Yahoo's ~30 days of 1m bars give a few dozen 1m trades and almost none at 15m+.
  That's a smoke test. For a real sample, use a year or more from a broker,
  TradingView, Polygon or Alpaca.
- Spot-check trades visually with `--plot-trades`, since the structure
  definition is the main correctness risk.
- On 1m SPY, stops are often $0.30-0.60, so costs take a large share of 1R.
  Always read gross and net side by side.
- Keep a count of every variant tried, and judge parameters on a later
  holdout period with a deflated-Sharpe-style correction.

## Owner decisions (2026-10-02)

- **Stop:** below the low that started the move (the origin low), as implemented. Confirmed.
- **1m structure:** resets every session, as implemented. Confirmed.
- **BOS/CHoCH definition:** the owner reviewed it and confirmed the logic
  is correct (close-based breaks, 5-bar fractal swings, and a prior
  lower-highs/lower-lows trend required). Confirmed.

The strategy definition is now locked. Next step: run it on a year or more
of 1-minute data, which Yahoo cannot supply.
