"""Command line: `tidy-app add <item> [count]` and `tidy-app list`."""

import argparse

from tidy_app.config import load_settings
from tidy_app.inventory import Inventory


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="tidy-app")
    parser.add_argument("command", choices=["add", "list"])
    parser.add_argument("item", nargs="?", default="")
    parser.add_argument("count", nargs="?", type=int, default=1)
    args = parser.parse_args(argv)
    inventory = Inventory.open(load_settings().stock_file)
    if args.command == "add":
        inventory.add(args.item, args.count)
    for item, count in inventory.counts().items():
        print(f"{item}: {count}")
