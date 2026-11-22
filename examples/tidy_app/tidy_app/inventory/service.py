"""Stock rules: clean up item names, add up counts. Knows nothing about files."""

from __future__ import annotations

from pathlib import Path

from tidy_app.inventory.store import StockStore


class Inventory:
    def __init__(self, store: StockStore) -> None:
        self.store = store

    @classmethod
    def open(cls, path: Path) -> Inventory:
        return cls(StockStore(path))

    def add(self, item: str, count: int = 1) -> None:
        name = item.strip().lower()
        stock = self.store.load()
        if name and count > 0:
            stock[name] = stock.get(name, 0) + count
            self.store.save(stock)

    def counts(self) -> dict[str, int]:
        return self.store.load()
