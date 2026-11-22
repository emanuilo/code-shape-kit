"""Settings. The only module that reads the environment."""

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    stock_file: Path


def load_settings() -> Settings:
    return Settings(stock_file=Path(os.environ.get("TIDY_STOCK_FILE", "stock.json")))
