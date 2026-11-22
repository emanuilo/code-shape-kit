"""Storage adapter: the only code that knows notes live in a JSON file."""

import json
from pathlib import Path


class NoteStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> list[str]:
        if not self.path.exists():
            return []
        return list(json.loads(self.path.read_text(encoding="utf-8")))

    def save(self, notes: list[str]) -> None:
        self.path.write_text(json.dumps(notes, indent=2), encoding="utf-8")
