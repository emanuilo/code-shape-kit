from tidy_app.inventory.store import StockStore


def test_missing_file_is_empty(tmp_path):
    assert StockStore(tmp_path / "none.json").load() == {}
