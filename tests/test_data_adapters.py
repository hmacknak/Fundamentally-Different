import io
import json
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


def test_build_fundamentals_csv_uses_stable_endpoint_with_symbol_query_param(monkeypatch, tmp_path):
    requested_urls = []

    def fake_urlopen(url, timeout=30):
        requested_urls.append(url)
        if "/key-metrics" in url:
            payload = [{"date": "2024-03-31", "freeCashFlowYield": 0.05, "revenuePerShare": 1.0}]
        else:
            payload = [{"date": "2024-03-31", "grossProfitMargin": 0.4}]
        return io.BytesIO(json.dumps(payload).encode())

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    data_adapters.build_fundamentals_csv(
        ["AAPL"], api_key="fake-key", out_path=str(tmp_path / "fundamentals.csv"),
    )

    assert any(u.startswith("https://financialmodelingprep.com/stable/key-metrics?symbol=AAPL")
              for u in requested_urls)
    assert any(u.startswith("https://financialmodelingprep.com/stable/ratios?symbol=AAPL")
              for u in requested_urls)
    assert not any("/api/v3/" in u for u in requested_urls)
