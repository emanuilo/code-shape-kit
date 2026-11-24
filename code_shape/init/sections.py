"""The text `code-shape init` writes: the kit's templates with the guesses filled in.

The templates (code_shape/templates/) stay the one place the settings are explained; this
module only swaps their placeholders. Each template starts with a paragraph on how to use
it by hand, which is left out here.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from itertools import pairwise
from pathlib import Path

from code_shape import __version__
from code_shape.init.guess import Project
from code_shape.init.layers import Draft

TEMPLATES = Path(__file__).parents[1] / "templates"
CONTRACT = "[[tool.importlinter.contracts]]"
INSTALL = f'pip install -e . "code-shape-kit[tools] @ git+https://github.com/emanuilo/code-shape-kit@v{__version__}"'
HEADER = f"""\
# ---------------------------------------------------------------------------
# Added by `code-shape init` (code-shape-kit {__version__}). The packages, config modules
# and layers below are best guesses from today's code: review them.
# ---------------------------------------------------------------------------
"""


class TemplateError(RuntimeError):
    """A template no longer has a line init fills in (the template changed, init didn't)."""


def template(name: str) -> str:
    return (TEMPLATES / name).read_text(encoding="utf-8")


def shape(project: Project) -> str:
    text = _without_intro(template("shape.toml"))
    names = ", ".join(f'"{name}"' for name in project.packages)
    why = "found in the project" if project.found else "PLACEHOLDER: no package found yet; use your package's name"
    text = _swap(text, r"^packages = .*$", f"packages = [{names}]  # {why}")
    if project.src != project.root:
        text = _swap(text, r"^# src = .*$", f'src = "{project.rel(project.src)}"  # the src/ layout was found')
    text = _swap(text, r"^config_modules = .*$", _config_modules(project))
    # The examples' paths are relative to the root, so with the src/ layout they start with src/.
    text = text.replace('"myapp/', f'"{project.rel(project.src / project.packages[0])}/')
    return text.replace("myapp", project.packages[0])


def _config_modules(project: Project) -> str:
    if project.config_module:
        why = project.config_why + (
            ": other modules that read the environment are flagged" if project.other_env_readers else ""
        )
        return f'config_modules = ["{project.config_module}"]  # {why}'
    example = f"{project.rel(project.src / project.packages[0])}/config.py"
    return f'# config_modules = ["{example}"]  # no obvious settings module found: list yours'


def importlinter(project: Project) -> str:
    head, contracts = _split_contracts(_without_intro(template("importlinter.toml")))
    if len(project.packages) == 1:
        root = f'root_package = "{project.packages[0]}"'
    else:
        root = "root_packages = [" + ", ".join(f'"{name}"' for name in project.packages) + "]"
    parts = [_swap(head, r'^root_package = "myapp"$', root).rstrip("\n") + "\n"]
    layers = next(c for c in contracts if 'id = "layers"' in c)
    drafts = {d.package: d for d in project.drafts}
    for name in project.packages:
        found = drafts.get(name)
        contract = _drafted(layers, found) if found and found.layers else _skeleton(layers)
        contract = contract.replace("myapp", name)
        if len(project.packages) > 1:
            contract = _swap(contract, r'^id = "layers"$', f'id = "layers-{name}"')
        parts.append(contract)
    parts.append(
        "# More contract types from the kit's template, switched off: uncomment the ones\n"
        "# you want and replace the placeholder names.\n"
    )
    parts += [_commented(c) for c in contracts if c is not layers]
    return "\n".join(parts)


def _drafted(contract: str, found: Draft) -> str:
    contract = _swap(contract, r"^name = .*$", f'name = "Layers: {found.describe()}"')
    layers = "".join(f'    "{" | ".join(layer)}",\n' for layer in found.layers)
    note = (
        "# Drafted by `code-shape init` from today's imports: each layer imports only the layers\n"
        "# below it. It shows what the code does now; reorder it to what it should do.\n"
    )
    contract = _swap(contract, r"^layers = \[\n(?:.*\n)*?\]\n", note + f"layers = [\n{layers}]\n")
    if found.against:
        ignores = "".join(f'    "{line}",\n' for line in found.against)
        ignored = (
            "# Today's imports that go against the order above (import cycles). Fix them, then\n"
            "# delete each line (a line that no longer matches an import is an error).\n"
            f"ignore_imports = [\n{ignores}]\n"
        )
        contract = _swap(contract, r"^exhaustive = .*\n", lambda m: m.group(0) + ignored)
    return contract


def _skeleton(contract: str) -> str:
    """The template's example layers, each optional (in parentheses) until the module exists."""
    note = (
        "# No code yet, so these are the template's example names. Replace them with your own\n"
        "# layers (DESIGNING_THE_SHAPE.md). A name in parentheses is optional: drop the\n"
        "# parentheses once the module exists.\n"
    )
    contract = _swap(contract, r"^layers = \[$", note + "layers = [")
    return re.sub(r'^(    ")([^"]+)(",)', _optional, contract, flags=re.MULTILINE)


def _optional(match: re.Match[str]) -> str:
    names = " | ".join(f"({name.strip()})" for name in match.group(2).split("|"))
    return match.group(1) + names + match.group(3)


def workflow(project: Project) -> str:
    text = _without_intro(template("github/code-shape.yml"))
    text = _swap_all(text, r'^( *python-version: )"3\.12"$', rf'\1"{project.python}"')
    text = re.sub(r"^ *# KIT: .*\n(?: *#.*\n)*? *#   pip install .*\n", "", text, flags=re.MULTILINE)
    text = re.sub(r"^( *)env:\n *KIT: .*\n *run: pip install .*$", rf"\1run: {INSTALL}", text, flags=re.MULTILINE)
    if "KIT" in text:
        raise TemplateError("init: the CI template's install step changed; update code_shape/init/sections.py")
    return text


def codeowners() -> str:
    """The template without its "Copy to .github/CODEOWNERS": init has done that."""
    return _swap(
        template("CODEOWNERS"),
        r"\A# Copy to \.github/CODEOWNERS \(and turn on (.*)\n# (.*)\)\.",
        lambda m: f"# Turn on {m.group(1)}\n# {m.group(2)}.",
    )


def _without_intro(text: str) -> str:
    """Drops the template's first paragraph: how to paste it by hand."""
    return text.split("\n\n", 1)[1]


def _split_contracts(text: str) -> tuple[str, list[str]]:
    """The text before the first contract, and each contract with the comments above it."""
    lines = text.splitlines(keepends=True)
    starts = [i for i, line in enumerate(lines) if line.strip() == CONTRACT]
    for n, start in enumerate(starts):
        while start > 0 and lines[start - 1].startswith("#"):
            start -= 1
        starts[n] = start
    bounds = [*starts, len(lines)]
    contracts = ["".join(lines[a:b]).rstrip("\n") + "\n" for a, b in pairwise(bounds)]
    return "".join(lines[: starts[0]]), contracts


def _commented(contract: str) -> str:
    """Switches a contract off: its TOML lines become comments, its own comments stay as they are."""
    lines = contract.splitlines(keepends=True)
    return "".join(line if line.startswith("#") or not line.strip() else "# " + line for line in lines)


def _swap_all(text: str, pattern: str, new: str) -> str:
    """Replaces every match of `pattern`; at least one must be there."""
    replaced, count = re.subn(pattern, new, text, flags=re.MULTILINE)
    if not count:
        raise TemplateError(f"init: a template no longer matches `{pattern}`; update code_shape/init/sections.py")
    return replaced


def _swap(text: str, pattern: str, new: str | Callable[[re.Match[str]], str]) -> str:
    """Replaces the one match of `pattern`; a template without it is an error, not a silent skip."""
    replace = new if callable(new) else lambda _: new  # a string is used as is (no \1 escapes)
    replaced, count = re.subn(pattern, replace, text, count=1, flags=re.MULTILINE)
    if count != 1:
        raise TemplateError(f"init: a template no longer matches `{pattern}`; update code_shape/init/sections.py")
    return replaced
