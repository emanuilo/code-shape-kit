"""Note rules: trimming, de-duplication. Knows nothing about files."""

from __future__ import annotations

from pathlib import Path

from tidy_app.notes.store import NoteStore


class NoteService:
    def __init__(self, store: NoteStore) -> None:
        self.store = store

    @classmethod
    def open(cls, path: Path) -> NoteService:
        return cls(NoteStore(path))

    def add(self, text: str) -> None:
        text = text.strip()
        notes = self.store.load()
        if text and text not in notes:
            self.store.save([*notes, text])

    def all(self) -> list[str]:
        return self.store.load()
