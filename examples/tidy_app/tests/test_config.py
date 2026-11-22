from tidy_app.config import load_settings


def test_reads_stock_file_path(monkeypatch):
    monkeypatch.setenv("TIDY_STOCK_FILE", "x.json")
    assert load_settings().stock_file.name == "x.json"
