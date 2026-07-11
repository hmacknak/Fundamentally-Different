import urllib.error

import pytest

import data_adapters


def test_build_fundamentals_csv_raises_clear_error_when_every_ticker_fails(monkeypatch, tmp_path):
    def fake_urlopen(url, timeout=30):
        raise urllib.error.HTTPError(url, 403, "Forbidden", hdrs=None, fp=None)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    with pytest.raises(RuntimeError, match="FMP returned no usable data"):
        data_adapters.build_fundamentals_csv(
            ["AAPL", "MSFT"], api_key="fake-key",
            out_path=str(tmp_path / "fundamentals.csv"),
        )
