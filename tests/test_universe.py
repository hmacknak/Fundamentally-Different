import re

from service.universe import DEFAULT_UNIVERSE, load_universe


def test_default_universe_has_no_duplicates():
    assert len(DEFAULT_UNIVERSE) == len(set(DEFAULT_UNIVERSE))


def test_default_universe_is_full_sp500_scale():
    assert len(DEFAULT_UNIVERSE) > 490


def test_default_universe_tickers_are_well_formed():
    for ticker in DEFAULT_UNIVERSE:
        assert re.match(r"^[A-Z]+(-[A-Z])?$", ticker), ticker


def test_load_universe_with_no_path_returns_default():
    assert load_universe() == DEFAULT_UNIVERSE


def test_load_universe_from_file_overrides_default(tmp_path):
    f = tmp_path / "universe.txt"
    f.write_text("aapl\n# comment\nmsft\n\n")
    assert load_universe(str(f)) == ["AAPL", "MSFT"]
