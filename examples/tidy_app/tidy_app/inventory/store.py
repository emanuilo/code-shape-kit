"""Storage adapter: the only code that knows the stock lives in a JSON file."""

import json
from pathlib import Path


class StockStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> dict[str, int]:
        if not self.path.exists():
            return {}
        return dict(json.loads(self.path.read_text(encoding="utf-8")))

    def save(self, stock: dict[str, int]) -> None:
        self.path.write_text(json.dumps(stock, indent=2, sort_keys=True), encoding="utf-8")
