"""What `code-shape init` tells the user: what it guessed, wrote and left alone, and what to do next."""

from __future__ import annotations

from code_shape import __version__
from code_shape.init import CODEOWNERS, WORKFLOW, Plan, Write
from code_shape.init.guess import Project


def describe(plan: Plan, *, dry_run: bool) -> str:
    lines = [f"code-shape init in {plan.root}" + (" (dry run: nothing written)" if dry_run else ""), ""]
    lines += _section("Guesses:", _guesses(plan))
    lines += _section("Would write:" if dry_run else "Wrote:", [_written(w, plan.project) for w in plan.writes])
    lines += _section("Left alone:", [f"  {line}" for line in plan.skipped])
    if not plan.writes:
        return "\n".join([*lines, "Nothing to add: the kit is set up here. Run `code-shape check`.\n"])
    lines += _section("Next:", [f"  {n}. {step}" for n, step in enumerate(_next_steps(plan), 1)])
    lines.append("These are guesses: review them (and the comments next to them) before you commit.")
    return "\n".join(lines) + "\n"


def _section(title: str, lines: list[str]) -> list[str]:
    return [title, *lines, ""] if lines else []


def _guesses(plan: Plan) -> list[str]:
    """The guesses behind what is written (none for a section that was already there)."""
    written = " ".join(w.what for w in plan.writes)
    guesses = _shape_guesses(plan.project) if "[tool.shape]" in written else []
    return guesses + (_layer_guesses(plan.project) if "[tool.importlinter]" in written else [])


def _written(write: Write, project: Project) -> str:
    action = f"added {write.what}" if write.append else write.what
    notes = {
        WORKFLOW: f"Python {project.python}, {project.python_why}; installs code-shape-kit v{__version__} from GitHub",
        CODEOWNERS: "replace @your-org/architects with the people who approve rule changes",
    }
    note = f" ({notes[write.path]})" if write.path in notes else ""
    return f"  {write.path}: {action}{note}"


def preview(plan: Plan) -> str:
    """The exact text each write adds, for --dry-run."""
    parts = []
    for w in plan.writes:
        how = "appended to the end" if w.append else "new file"
        parts.append(f"----- {w.path} ({how}) -----\n{w.text}")
    return "\n".join(parts)


def _shape_guesses(project: Project) -> list[str]:
    names = ", ".join(project.packages)
    if not project.found:
        package = f"{names} (a PLACEHOLDER: no package found)"
    else:
        package = names + (f" (in {project.rel(project.src)}/)" if project.src != project.root else "")
    return [f"  packages:        {package}", *_config_guesses(project)]


def _config_guesses(project: Project) -> list[str]:
    others = project.other_env_readers
    if project.config_module:
        lines = [f"  config modules:  {project.config_module} ({project.config_why})"]
    elif others:
        lines = ["  config modules:  none picked: no obvious settings module (config_modules is a commented example)"]
    else:
        return ["  config modules:  none yet (no module reads os.environ / os.getenv); config_modules is an example"]
    if others:
        lines.append(f"    other modules that read the environment ({len(others)}): `code-shape check` flags them")
        lines.append("    (banned-api): move each read into the settings module, or baseline it deliberately:")
        lines += [f"      {path} ({project.env_reads[path]} read(s))" for path in others]
    return lines


def _layer_guesses(project: Project) -> list[str]:
    drafts = {d.package: d for d in project.drafts if d.layers}
    lines = []
    for name in project.packages:
        found = drafts.get(name)
        if not found:
            why = f"could not read the imports: {project.graph_error}" if project.graph_error else "no modules yet"
            lines.append(f"  layers in {name}: a starter skeleton with example names ({why})")
            continue
        lines.append(f"  layers in {name}: {found.describe()}")
        if found.against:
            count = len(found.against)
            lines.append(f"    import cycles: {count} import(s) go against that order, listed under ignore_imports:")
            lines += [f"      {line}" for line in found.against]
    return lines


def _next_steps(plan: Plan) -> list[str]:
    project = plan.project
    steps = ["Review the guesses in pyproject.toml: the layer order is what the code does today."]
    if not project.found:
        init_file = project.rel(project.src / project.packages[0] / "__init__.py")
        steps.append(
            f"Create the package `{project.packages[0]}` ({init_file}), or put your package's name in "
            "`packages`: `code-shape check` stops until it exists."
        )
    if project.has_code:
        steps.append("Run `code-shape check`. It lists today's violations.")
        steps.append(
            "To start from today's code, run `code-shape baseline` once and commit .code-shape-baseline.json: "
            "from then on only new or worse problems fail."
        )
    elif any("[tool.importlinter]" in w.what for w in plan.writes):
        steps.append("Replace the example layer names with your own, then run `code-shape check`.")
        steps.append("No baseline needed: with no code yet, every violation fails from day one.")
    else:
        steps.append("Run `code-shape check`.")
    if any(w.path == CODEOWNERS for w in plan.writes):
        steps.append("On GitHub, turn on 'Require review from Code Owners' in the branch protection rules.")
    return steps
