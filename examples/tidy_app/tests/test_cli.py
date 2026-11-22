from tidy_app.cli import main


def test_add_then_list(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TIDY_NOTES", str(tmp_path / "n.json"))
    main(["add", "hello"])
    assert "hello" in capsys.readouterr().out
