from tidy_app.config import load_settings


def test_reads_notes_path(monkeypatch):
    monkeypatch.setenv("TIDY_NOTES", "x.json")
    assert load_settings().notes_file.name == "x.json"
