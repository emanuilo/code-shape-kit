"""Settings. The only module that reads the environment."""

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    notes_file: Path


def load_settings() -> Settings:
    return Settings(notes_file=Path(os.environ.get("TIDY_NOTES", "notes.json")))
