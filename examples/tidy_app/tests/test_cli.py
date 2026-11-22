from tidy_app.cli import main


def test_add_then_list(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TIDY_STOCK_FILE", str(tmp_path / "stock.json"))
    main(["add", "apples", "3"])
    assert "apples: 3" in capsys.readouterr().out
