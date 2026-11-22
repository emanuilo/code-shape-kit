from tidy_app.notes import NoteService


def test_add_trims_and_deduplicates(tmp_path):
    service = NoteService.open(tmp_path / "notes.json")
    service.add(" milk ")
    service.add("milk")
    assert service.all() == ["milk"]
