"""Runs a tool from a scratch folder, and the helpers every tool's reader shares."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

from code_shape.model import Finding
from code_shape.settings import Settings

RATIO = re.compile(r"\((\d+)\s*[>/]\s*(\d+)\)")  # "(12 > 10)" or "(17/15)"


class ToolError(Exception):
    pass


@contextmanager
def reading(tool: str) -> Iterator[None]:
    """Output in a shape the kit doesn't expect (e.g. another version of the tool) is a tool error, not a crash."""
    try:
        yield
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ToolError(
            f"{tool} output is not in the format the kit expects ({type(exc).__name__}: {exc}); "
            "is the pinned version installed? (pip install 'code-shape-kit[tools]')"
        ) from exc


def _exe(name: str) -> str:
    found = shutil.which(name, path=str(Path(sys.executable).parent)) or shutil.which(name)
    if not found:
        raise ToolError(f"`{name}` is not installed (pip install 'code-shape-kit[tools]')")
    return found


def run(
    settings: Settings, tmp: Path, cmd: list[str], *, ok_codes=(0, 1), cwd: Path | None = None, failed_if: str = ""
) -> str:
    """Run a tool from a scratch folder (so caches land there, not in the project).

    `failed_if`: text in the output that means the tool could not do its job, for tools
    whose exit code doesn't say so.
    """
    tool = cmd[0]
    cmd = [_exe(tool), *cmd[1:], *settings.tools.extra_args.get(tool, [])]
    env = {
        **os.environ,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": str(settings.src),
        "COLUMNS": "10000",
        "NO_COLOR": "1",
    }
    proc = subprocess.run(cmd, cwd=cwd or tmp, env=env, capture_output=True, text=True, timeout=900, check=False)
    if proc.returncode not in ok_codes or (failed_if and failed_if in proc.stdout + proc.stderr):
        raise ToolError(f"{tool} exited with {proc.returncode}: {(proc.stderr or proc.stdout)[-800:]}")
    return proc.stdout


def pkg_dirs(settings: Settings) -> list[str]:
    return [str(p) for p in settings.package_dirs()]


def merge(findings: list[Finding]) -> list[Finding]:
    """Findings with the same key become one, with their values added up."""
    merged: dict[str, Finding] = {}
    for f in findings:
        old = merged.get(f.key)
        merged[f.key] = f if old is None else replace(old, value=(old.value or 0) + (f.value or 0))
    return list(merged.values())
