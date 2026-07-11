import pandas as pd

from service.providers.prices import map_yfinance_chunk_to_prices_schema


def _fake_yfinance_download(tickers_to_frames: dict) -> pd.DataFrame:
    """Build a frame shaped like yfinance's group_by='ticker' output."""
    combined = pd.concat(tickers_to_frames, axis=1)
    combined.index.name = "Date"  # matches yfinance's actual index name
    return combined


def test_map_yfinance_chunk_renames_and_stacks_tickers():
    idx = pd.date_range("2020-01-01", periods=3, freq="D")
    aaa = pd.DataFrame({"Close": [10.0, 11.0, 12.0], "Volume": [100, 110, 120]}, index=idx)
    bbb = pd.DataFrame({"Close": [20.0, 21.0, 22.0], "Volume": [200, 210, 220]}, index=idx)
    raw = _fake_yfinance_download({"AAA": aaa, "BBB": bbb})

    out = map_yfinance_chunk_to_prices_schema(raw, ["AAA", "BBB"])

    assert list(out.columns) == ["date", "ticker", "adj_close", "volume"]
    assert set(out["ticker"]) == {"AAA", "BBB"}
    assert out[out["ticker"] == "AAA"]["adj_close"].tolist() == [10.0, 11.0, 12.0]


def test_map_yfinance_chunk_skips_ticker_with_no_data():
    idx = pd.date_range("2020-01-01", periods=3, freq="D")
    aaa = pd.DataFrame({"Close": [10.0, 11.0, 12.0], "Volume": [100, 110, 120]}, index=idx)
    raw = _fake_yfinance_download({"AAA": aaa})

    out = map_yfinance_chunk_to_prices_schema(raw, ["AAA", "MISSING"])

    assert set(out["ticker"]) == {"AAA"}


def test_map_yfinance_chunk_drops_rows_with_missing_close_or_volume():
    idx = pd.date_range("2020-01-01", periods=3, freq="D")
    aaa = pd.DataFrame({"Close": [10.0, None, 12.0], "Volume": [100, 110, 120]}, index=idx)
    raw = _fake_yfinance_download({"AAA": aaa})

    out = map_yfinance_chunk_to_prices_schema(raw, ["AAA"])

    assert len(out) == 2


def test_map_yfinance_chunk_empty_when_nothing_matches():
    out = map_yfinance_chunk_to_prices_schema(pd.DataFrame(), ["ZZZ"])
    assert out.empty
    assert list(out.columns) == ["date", "ticker", "adj_close", "volume"]
