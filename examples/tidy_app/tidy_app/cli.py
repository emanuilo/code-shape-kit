"""Command line: `tidy-app add <text>` and `tidy-app list`."""

import argparse

from tidy_app.config import load_settings
from tidy_app.notes import NoteService


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="tidy-app")
    parser.add_argument("command", choices=["add", "list"])
    parser.add_argument("text", nargs="?", default="")
    args = parser.parse_args(argv)
    service = NoteService.open(load_settings().notes_file)
    if args.command == "add":
        service.add(args.text)
    for note in service.all():
        print(note)
