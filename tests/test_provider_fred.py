import pandas as pd

from service.providers.fred import fetch_fred_series, parse_fred_csv

SAMPLE_CSV = "observation_date,DGS10\n2020-01-01,1.5\n2020-02-01,1.6\n2020-03-01,.\n"


def test_parse_fred_csv_coerces_dates_and_numerics():
    s = parse_fred_csv(SAMPLE_CSV, "DGS10")
    assert isinstance(s.index, pd.DatetimeIndex)
    assert s.loc[pd.Timestamp("2020-01-01")] == 1.5
    assert s.loc[pd.Timestamp("2020-02-01")] == 1.6


def test_parse_fred_csv_treats_dot_as_missing():
    s = parse_fred_csv(SAMPLE_CSV, "DGS10")
    assert pd.isna(s.loc[pd.Timestamp("2020-03-01")])


def test_fetch_fred_series_uses_injected_http_get_no_network():
    calls = []

    def fake_http_get(url, timeout):
        calls.append((url, timeout))
        return SAMPLE_CSV

    s = fetch_fred_series("DGS10", "2020-01-01", "2020-03-01", http_get=fake_http_get)
    assert len(calls) == 1
    assert "id=DGS10" in calls[0][0]
    assert "cosd=2020-01-01" in calls[0][0]
    assert s.loc[pd.Timestamp("2020-01-01")] == 1.5
