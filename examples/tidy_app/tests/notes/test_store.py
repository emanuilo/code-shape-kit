from tidy_app.notes.store import NoteStore


def test_missing_file_is_empty(tmp_path):
    assert NoteStore(tmp_path / "none.json").load() == []
