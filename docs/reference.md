# Reference

Everything the kit does, in detail. For the short version, see the [README](../README.md).
For an agent setting the kit up or working under it, see [agents.md](agents.md). For
deciding a project's layers and modules, see [designing-the-shape.md](designing-the-shape.md).

- [Words used here](#words-used-here)
- [Install](#install)
- [Commands](#commands)
- [What `init` writes](#what-init-writes)
- [The checks](#the-checks)
- [Settings](#settings)
- [The baseline and the ratchet](#the-baseline-and-the-ratchet)
- [Suppression comments](#suppression-comments)
- [Architecture contracts](#architecture-contracts)
- [Rules loosened (`--base REF`)](#rules-loosened---base-ref)
- [CI and CODEOWNERS](#ci-and-codeowners)
- [False positives in dead code](#false-positives-in-dead-code)
- [Error boundaries](#error-boundaries)
- [Upgrade notes](#upgrade-notes)
- [Deliberately left out](#deliberately-left-out)
- [The kit's own code](#the-kits-own-code)

## Words used here

| Word | Meaning |
|---|---|
| module | one `.py` file |
| package | a folder of modules (with `__init__.py`) |
| layer | a group of modules at the same level, e.g. "entry points", "features", "storage". Higher layers may use lower ones, never the reverse |
| coupling | how much one piece of code depends on another. Low is good: you can change one without the other |
| fan-in / fan-out | how many modules import this one / how many this one imports |
| adapter | the one module that talks to an outside thing (a database, an SDK, the environment), so the rest of the code doesn't have to |
| cyclomatic complexity | the number of paths through a function (each `if`, `for`, `and`... adds one) |
| cognitive complexity | how hard a function is to read; nesting costs extra |
| change coupling | files that keep being changed in the same commits |
| gate | a check that fails CI |
| tracked metric | a number in the report that you watch, but that never fails CI |
| baseline | a file listing the problems a project already has, so only new ones fail |
| ratchet | `tighten` only shrinks the baseline, and a fixed problem fails if it comes back. Growing the baseline takes `code-shape baseline`, which shows in the PR diff and in the rules-loosened warning |
| suppression | a comment that silences a tool on one line, e.g. `# noqa`, `# type: ignore`, `# pylint: disable` |

## Install

Needs Python 3.11.4 or newer (import-linter and grimp, which the kit drives, require 3.11;
the trend extracts old commits with a safety filter added in 3.11.4).

```bash
# the kit + the pinned tool versions it drives
pip install "code-shape-kit[tools] @ git+https://github.com/emanuilo/code-shape-kit"

# in CI, pin a tag (or a commit sha) so the gates only change when you bump it
pip install "code-shape-kit[tools] @ git+https://github.com/emanuilo/code-shape-kit@v0.3.0"
```

`pip install git+https://github.com/emanuilo/code-shape-kit` alone installs only the
`code-shape` command; the `[tools]` extra adds ruff, pylint, mypy and the rest. Leave it
out only if your environment already provides those tools.

Tools are pinned exactly (see the kit's `pyproject.toml`): a gate must not start failing
because CI installed a newer linter. The project itself must be installed in the same
environment (mypy and deptry need its dependencies).

Tool versions verified November 2026: ruff 0.17.6, complexipy 9.0.0, pylint 4.1.4,
import-linter 2.17 (grimp 3.20), vulture 2.16, deptry 0.25.1, mypy 2.4.1.

## Commands

```bash
code-shape init                # set the kit up here: best guesses for you to review
code-shape init --dry-run      # ...only show what it would write
code-shape report              # run everything, write code-shape-report.md, never fail
code-shape report --trend 8    # ...plus the same numbers for 8 past commits
code-shape check               # CI gate: fail on NEW or WORSE violations
code-shape baseline            # record today's violations (existing projects)
code-shape tighten             # lock in improvements (only ever shrinks the baseline)
code-shape check --base origin/main   # ...and warn about every rule loosened since origin/main
```

| Option | Works with | Meaning |
|---|---|---|
| `--root DIR` | all | project folder (default: the current folder) |
| `--config FILE` | all but init | a TOML file with `[tool.shape]`, if it is not in `pyproject.toml` |
| `--baseline FILE` | check, baseline, tighten | baseline file (default: `[tool.shape] baseline`, else `.code-shape-baseline.json`) |
| `--out FILE` | report | report file (default: `<root>/code-shape-report.md`) |
| `--trend N` | report | also re-run the fast checks (sizes, ruff, complexipy) on N past commits |
| `--only GROUPS` | all but init | comma-separated check groups to run, e.g. `sizes,ruff` |
| `--base REF` | check, report | also list the rules loosened since this git ref (a warning only) |
| `--summary FILE` | with `--base` | append that list as markdown to FILE, e.g. `$GITHUB_STEP_SUMMARY` |
| `--dry-run` | init | show what would be written, change nothing |

`init` takes only `--root` and `--dry-run`.

The check groups (for `--only` and `skip`) are: `sizes`, `ruff`, `complexipy`, `pylint`,
`import-linter`, `graph`, `vulture`, `deptry`, `mypy`, `suppressions`, `history`, `concepts`,
`tests`. An unknown name is an error. `check`, `baseline` and `tighten` run only the groups
that produce a gated check.

`check` exits with 1 when something is new, worse, or improved but not locked in, or when a
check could not run. It ends with a reminder that the fix is in the code, not in the
baseline, a suppression comment or the config.

[`code_shape/templates/code-shape.mk`](../code_shape/templates/code-shape.mk) has the same as
`make shape-report`, `make shape-check` (`BASE=origin/main` adds `--base`), `make shape-baseline`
and `make shape-tighten`. Include it from your Makefile.

## What `init` writes

It never prompts and never overwrites: a section or file that is already there is left
alone, and the summary says so.

- `[tool.shape]` and `[tool.importlinter]`, appended to `pyproject.toml` as text (your own
  comments and formatting stay). They are the kit's templates with the guesses filled in:
  the package (and the `src/` layout), the `config_modules` (only the obvious settings
  module: one named `config.py`, `settings.py`, `conf.py` or `env.py`, else the one with
  clearly the most `os.environ` / `os.getenv` reads; with none obvious, a commented
  example), and a layers contract drafted from today's imports between the modules directly
  inside the package. A module that imports another sits above it; modules that don't import
  each other share a layer (`orders | inventory`). Imports in a cycle can't be layered: init
  picks an order and lists the imports that go against it under `ignore_imports`, so you can
  see them and fix them. With no code yet, the contract is the template's example, each name
  optional until the module exists.
- `.github/workflows/code-shape.yml` (installs this version of the kit from GitHub, on the
  lowest Python your `requires-python` allows, 3.11 or newer; 3.12 without one) and
  `.github/CODEOWNERS` (replace `@your-org/architects` with your reviewers). If the project
  already has a `CODEOWNERS` or `docs/CODEOWNERS`, init leaves it alone and tells you to add
  the template's lines to it.

Other modules that read the environment are not listed: `code-shape check` flags them
(`banned-api`), and the summary names them. Move each read into the settings module, or
baseline it on purpose. Without a package yet, init writes a placeholder name (your
`[project]` name) into `packages`; `code-shape check` stops with an error naming the missing
folder until you create the package.

When `[tool.shape]` is already there, the contract is drafted for the `src` and `packages`
it names. Without a `pyproject.toml` it stops: create one for your project first. The
guesses are a draft. The layer order shows what the code does today, not what it should do:
review it.

To set up by hand instead: paste [`shape.toml`](../code_shape/templates/shape.toml) and
[`importlinter.toml`](../code_shape/templates/importlinter.toml) into `pyproject.toml` and
fill in the placeholders; copy [`github/code-shape.yml`](../code_shape/templates/github/code-shape.yml)
to `.github/workflows/` and [`CODEOWNERS`](../code_shape/templates/CODEOWNERS) to `.github/`.

## The checks

Gate = fails `code-shape check`. Tracked = report only. The id in brackets is what
failure messages, `gates` and the baseline use.

| Area | Check | Protects against | Tool | Default |
|---|---|---|---|---|
| Size | File too long (500 lines) `[file-lines]` | one file doing two jobs | custom | gate |
| | Class too long (300 lines) `[class-lines]` | "god classes" every feature edits | custom | gate |
| | Folder has too many modules (12) `[package-files]` | flat folders where nothing is grouped | custom | gate |
| | Folder holds too much code (4000 lines) `[package-lines]` | a hidden sub-system with no boundary | custom | gate |
| | Folders nested too deep (4) `[package-depth]` | code hidden in deep trees | custom | gate |
| Functions | Too many paths (cyclomatic 10) `[function-complexity]` | functions with too many cases to test | ruff C901 | gate |
| | Hard to read (cognitive 15) `[cognitive-complexity]` | tangled, deeply nested logic | complexipy | gate |
| | Too long (50 statements), too many arguments (6), positional (5), branches (12), returns (6) `[too-many-*]` | functions doing several jobs | ruff PLR09xx | gate |
| | Nested too deep (4) `[nesting]`, too many variables (15) `[too-many-locals]`, complicated conditions (5) `[bool-expressions]` | code a reader can't hold in their head | pylint | gate |
| Classes | Too much state (12 attributes) `[class-attributes]`, too many public methods (20) `[public-methods]` | classes with many responsibilities | pylint | gate |
| Hidden coupling | Global variables changed in functions `[global-state]` | invisible links between distant code | ruff PLW0603 | gate |
| | Restricted API used outside its home `[banned-api]` | env vars read everywhere; an SDK used all over | ruff TID251 | gate |
| | Private member (`obj._name`) used from outside its class `[private-access]` | code coupled to another class's internals | ruff SLF001 | gate |
| | Copy-pasted code (10+ lines) `[duplicate-code]` | fixes that must be made in every copy | pylint duplicate-code | gate |
| Structure | Architecture rules (layers, independence, public interfaces, private modules, SDK only in its adapter, no cycles) `[import-contracts]` | the design you decided on eroding | import-linter | gate, no baseline |
| | Modules importing each other in a circle `[import-cycles]` | code that can't be understood or tested alone | custom (grimp) | gate |
| | Module imports too many others (12) `[fan-out]` | modules that break when anything changes | custom (grimp) | gate |
| Hygiene | Unused code `[dead-code]` | dead code that misleads readers and agents | vulture | gate |
| | Dependencies out of sync with imports `[dependencies]` | broken installs, bloat | deptry | gate |
| | Type errors, also in functions without annotations; `# type: ignore` without an error code, or no longer needed `[type-errors]` | interfaces between modules drifting apart | mypy | gate |
| Silenced checks | Suppression comments (`# noqa`, `# type: ignore`, `# pylint: disable`, `# pragma: no cover`, `# complexipy: ignore`, `# nosec`), counted per function and kind `[inline-suppression]` | problems hidden instead of fixed, and the habit copied | custom (tokenize) | gate |
| | Suppression without an error code (bare `# noqa`, `# type: ignore`) `[blanket-suppression]` | every rule silenced on the line, also future ones | ruff PGH003, PGH004 | gate |
| Risky habits | Errors swallowed or caught too broadly `[swallowed-errors]` (bare `except:`, `except Exception`, an except that only passes, continues or re-raises; see below) | failures hidden; bugs show up far from their cause | ruff E722, BLE001, S110, S112, TRY203 | gate |
| | Commented-out code `[commented-out-code]` | stale code that gets copied back in | ruff ERA001 | gate |
| | `print()` outside the entry point (`cli.py`, `__main__.py`, or `output_modules`) `[print-call]` | leftover debugging; output mixed into library code | ruff T201, T203 | gate |
| | Mutable or computed default argument `[mutable-default]` | one call changing what the next one gets | ruff B006, B008 | gate |
| | Wildcard import (`from x import *`) `[wildcard-import]` | names nobody can trace | ruff F403, F405 | gate |
| | `shell=True`, SQL built from strings, hard-coded passwords, `eval`/`exec` `[security-risk]` | injection and leaked secrets | ruff S602, S604, S608, S105-S107, S307, S102 | gate |
| | `True`/`False` passed by position `[boolean-flag-args]` | calls that don't say what they mean; functions doing two jobs | ruff FBT001, FBT002 | gate |
| Locality of change | Commit spread: how many files and areas a typical commit touches | features that need edits all over | custom (git) | tracked |
| | Change coupling: distant files that always change together `[change-coupling]` | one concept split across far-apart files | custom (git) | tracked |
| | Hotspots: big files that change often | where shape problems cost the most | custom (git) | tracked |
| | Concept spread: how many files mention each concept you name `[concept-spread]` | concepts with no single home | custom | tracked |
| Tests | Test file mirrors each module (`tests/a/test_b.py` for `pkg/a/b.py`) `[test-mirror]` | not knowing where tests live or which are missing | custom | tracked |
| Trend | The fast checks re-run on N past commits (`report --trend N`) | slow decay nobody notices | custom (git archive) | report |

`swallowed-errors` lets `except Exception` through when it logs the traceback with
`logger.exception(...)` (or `exc_info=True`), for `logging`, loguru and the loggers in
`logger_objects`. Reviewed catch-alls go in [`error_boundaries`](#error-boundaries).

Every failure message says what is wrong, why it matters, and what to do instead, so an
agent can fix it without asking. The text comes from
[`code_shape/catalog.toml`](../code_shape/catalog.toml), one entry per check.

The checks look at the `packages` you list. The tests folder isn't linted (only the
test-mirror report looks at it): test code has other needs, and keeping one rule set
keeps the kit simple. Lint your tests with your normal ruff setup.

## Settings

All settings live under `[tool.shape]` in `pyproject.toml` (or in the file given with
`--config`). [`code_shape/templates/shape.toml`](../code_shape/templates/shape.toml) has every
one, commented, with the reason for each default limit. A typo (an unknown setting, limit or
check id) is an error, so no rule is switched off by accident. Paths and globs are relative
to the project root: with the `src/` layout, write `src/myapp/config.py`.

| Key | Default | Meaning |
|---|---|---|
| `packages` | the one package found | the top-level package(s) to check. Several candidates and no setting is an error |
| `src` | `src` if it exists, else the root | where the packages are |
| `tests` | `tests` | the tests folder (only used by the test-mirror report) |
| `config_modules` | `[]` | the only modules that may read `os.environ`, `os.getenv`, `os.putenv` |
| `output_modules` | `["*/cli.py", "*/__main__.py"]` | the only modules that may `print()` |
| `logger_objects` | `[]` (loguru's `logger` is always included) | your own logger objects, as import paths (`"myapp.log.logger"`), whose `logger.exception(...)` passes `swallowed-errors` |
| `gates` | every static check | check ids that fail `check`. History checks and test-mirror are never gates by default |
| `skip` | `[]` | check groups to switch off entirely, e.g. `["mypy"]` |
| `exclude` | `[]` | globs left out of every check, e.g. `["myapp/generated/*"]` |
| `baseline` | `.code-shape-baseline.json` | where the baseline lives (`--baseline` overrides it) |
| `dead_code_whitelist` | `[]` | vulture whitelist files ([details](#false-positives-in-dead-code)) |
| `[tool.shape.limits]` | see below | the numbers the gates use |
| `[tool.shape.banned_api]` | the `os.environ` rules | APIs only one place may use (adapters) |
| `[tool.shape.concepts]` | none | named concepts for the concept-spread report |
| `[tool.shape.error_boundaries]` | none | reviewed functions that may catch every error ([details](#error-boundaries)) |
| `[tool.shape.extra_args]` | none | extra command-line arguments per tool |

### Limits

Only set a limit where the default is wrong for the project, not to make today's code
pass: the baseline is for that. For every limit except `max_changeset_files` and
`history_days`, a higher number lets more through.

| Limit | Default | Check |
|---|---|---|
| `file_lines` | 500 | file-lines |
| `class_lines` | 300 | class-lines |
| `package_files` | 12 | package-files |
| `package_lines` | 4000 | package-lines |
| `package_depth` | 4 | package-depth |
| `cyclomatic` | 10 | function-complexity |
| `cognitive` | 15 | cognitive-complexity |
| `args` | 6 | too-many-args |
| `positional_args` | 5 | too-many-positional |
| `branches` | 12 | too-many-branches |
| `returns` | 6 | too-many-returns |
| `statements` | 50 | too-many-statements |
| `nesting` | 4 | nesting |
| `locals` | 15 | too-many-locals |
| `bool_expressions` | 5 | bool-expressions |
| `class_attributes` | 12 | class-attributes |
| `public_methods` | 20 | public-methods |
| `duplicate_lines` | 10 | duplicate-code |
| `fan_out` | 12 | fan-out |
| `dead_code_confidence` | 60 | dead-code (60 also finds unused functions and classes; 90 only imports) |
| `concept_files` | 5 | concept-spread (tracked) |
| `concept_areas` | 3 | concept-spread (tracked) |
| `coupling_percent` | 50 | change-coupling (tracked) |
| `coupling_min_shared` | 3 | change-coupling (tracked) |
| `max_changeset_files` | 30 | change-coupling: bigger commits are ignored |
| `history_days` | 365 | how far back the history checks read |

### Restricted APIs (`banned_api`)

An adapter is the one module that may use an outside system. List each one:

```toml
[tool.shape.banned_api]
"stripe" = { msg = "Call Stripe only through myapp/stripe_client.py.", allowed = ["myapp/stripe_client.py"] }
"sqlalchemy" = { msg = "Only myapp/db/ talks to the database.", allowed = ["myapp/db/*"] }
```

`msg` is what a failure says to do instead; `allowed` is the files or globs that may use
it (a string or a list). A plain string value is taken as `msg` with nothing allowed. The
rules for `os.environ`, `os.getenv` and `os.putenv` are always there, with `config_modules`
as their `allowed` list.

### Concepts

```toml
[tool.shape.concepts]
"billing" = { terms = ["invoice", "BillingService"], home = "myapp/billing/service.py" }
"users" = ["User\\b", "account"]
```

Terms are case-insensitive regular expressions; `home` (optional) is the file or folder
that should own the concept, and it must exist. The report shows how many files and areas
mention each concept.

### Extra tool arguments

```toml
[tool.shape.extra_args]
vulture = ["--ignore-decorators", "@app.route,@cli.command"]
deptry = ["--optional-dependencies-dev-groups", "dev"]
```

Keys are the tools' command names: `ruff`, `complexipy`, `pylint`, `lint-imports`
(import-linter), `vulture`, `deptry`, `mypy`. Adding arguments is listed as a rule loosened.

### The tools' own settings

The kit runs ruff and pylint without the project's own config for them, with its own
rules and limits, so a project's ignore settings don't hide shape problems. It does read
`[tool.vulture]`, `[tool.deptry]` and `[tool.mypy]` (changes there that hide problems are
listed as [rules loosened](#rules-loosened---base-ref)). The kit's mypy run reads the project's `[tool.mypy]`
(plugins, `python_version`, stricter flags) but drops the settings that take code out of the
check, also in `[[tool.mypy.overrides]]`: `ignore_errors`, `disable_error_code`,
`follow_imports`, `follow_imports_for_stubs`, `check_untyped_defs`, `warn_unused_ignores` and
`exclude` (use `[tool.shape] exclude` for generated code). A `mypy.ini` or `setup.cfg` is not
read.

## The baseline and the ratchet

`.code-shape-baseline.json` lists known problems by place (file + function name, no line
numbers, so unrelated edits don't disturb it) and by size (e.g. "orders.py: 640 lines").
`check` then fails when:

- a problem is **new** (not in the baseline);
- a known problem got **worse** (640 -> 660 lines);
- a known problem got **better** but the baseline wasn't updated. Run `code-shape tighten`
  and commit. That is the ratchet: once orders.py is down to 560 lines, 600 fails.

`code-shape baseline` records everything as it is today, so it can also grow the
baseline. Use it once, at the start, or when a human has decided to accept a problem. Every
entry it adds shows in the PR diff and in the [rules-loosened](#rules-loosened---base-ref)
warning. `code-shape tighten` only removes or lowers entries, never adds.

If a check group could not run, `baseline` and `tighten` keep that group's entries as they
were and exit with 1.

The baseline file sits in the project root by default. To keep it elsewhere, set a path
relative to the project root, e.g. `baseline = ".code-shape/baseline.json"` under
`[tool.shape]`; `baseline` and `tighten` create the folder if needed. `--baseline FILE`
overrides the setting.

A new project needs no baseline: every violation fails from day one.

## Suppression comments

ruff's `# noqa` and complexipy's ignore comments are ignored by the shape checks on purpose.
The baseline is the one visible place for exceptions, and every addition to it shows up in
the PR diff. pylint, vulture and mypy can't be told to ignore their inline comments, so
`# pylint: disable=...`, `# noqa` (vulture) and `# type: ignore` still silence those checks.

That is why the `inline-suppression` check counts every such comment per function and kind:
a new one fails as NEW, one more of the same kind in the same function fails as WORSE. A
suppression a human accepted goes into the baseline like any other exception. mypy also
runs with `--warn-unused-ignores` and `--enable-error-code ignore-without-code`, so an
ignore must name its error and still be needed.

## Architecture contracts

Layers, independent features, private modules and "this SDK only in its adapter" are
import-linter contracts in `[tool.importlinter]`.
[`code_shape/templates/importlinter.toml`](../code_shape/templates/importlinter.toml) has a
commented template for each kind, and [designing-the-shape.md](designing-the-shape.md)
explains how to choose them.

Contracts are never baselined by the kit: a broken contract always fails. For imports that
break a contract today, use import-linter's own `ignore_imports` list in the contract. Write
`broken_contract_guidance` in each contract: it is what an agent reads when it breaks the
rule, so say what to do instead.

## Rules loosened (`--base REF`)

The baseline and the config are files in the repo, so an agent can edit them to get a
check green. `code-shape check --base origin/main` (also `report --base`) compares them with
the given git ref and lists, under "RULES LOOSENED since origin/main - needs human
approval", every change that makes the gates easier to pass:

- baseline entries added, or their numbers raised;
- limits raised, gates removed, `skip` or `exclude` grown, `packages` shrunk, `extra_args` added;
- `config_modules`, `output_modules` or a `banned_api` `allowed` list widened, a banned API
  dropped, a logger added to `logger_objects`, or a function added to `error_boundaries`;
- the dead-code whitelist grown (the setting or the file), `[tool.vulture]` ignores or
  excludes added, `[tool.deptry]` ignores, excludes or `known_first_party` added;
- `[tool.mypy]` `ignore_missing_imports` switched on or given more modules, or `strict`
  switched off;
- import-linter contracts removed, `ignore_imports` or `allowed_importers` grown, modules
  dropped, layers reordered, merged or split (so an import they forbade is allowed; a layer
  that gains a module is fine), `exhaustive` switched off, or a contract's type changed;
- suppression comments added in the files that changed.

It looks like this:

```text
RULES LOOSENED since main - needs human approval (a warning; it does not fail the check):
  - baseline: new entry `inline-suppression|tidy_app/inventory/service.py|type: ignore in Inventory.remove` (1)
  - [tool.shape.limits] `file_lines` raised from 20 to 60
  - tidy_app/inventory/service.py: 1 more `# type: ignore`
```

It is a warning: it never changes the exit code, because some of these changes are right
(a human decided). If the ref is missing or the folder isn't a git repository, it says so
and the check goes on. `--summary FILE` appends the list as markdown to FILE; the CI
template passes `$GITHUB_STEP_SUMMARY`, so it shows at the top of the run's summary page.
Contracts in a separate `.importlinter` (INI) file are not compared; CODEOWNERS covers them.

## CI and CODEOWNERS

[`code_shape/templates/github/code-shape.yml`](../code_shape/templates/github/code-shape.yml)
(written by `init` as `.github/workflows/code-shape.yml`) does two jobs:

- on every pull request and push to main: `code-shape check`, with `--base` and `--summary`
  on a pull request, so the rules-loosened list is at the top of the run's summary page;
- weekly and on demand: `code-shape report --trend 8`, uploaded as an artifact and shown in
  the run summary.

It checks out the full history (`fetch-depth: 0`), which `--base` and the history checks
need, and installs the project too (mypy and deptry need its dependencies).

To make human approval required, copy
[`code_shape/templates/CODEOWNERS`](../code_shape/templates/CODEOWNERS) to `.github/CODEOWNERS`
(`init` does it), replace `@your-org/architects` with your reviewers, and turn on "Require
review from Code Owners" in the branch protection rules. It puts the config, the baseline,
the whitelist, the contracts and the CI workflow under code-owner review. Adjust the paths
if you moved a file (for example a custom `baseline` path).

## False positives in dead code

vulture reads the code, not the running program, so it reports names that a framework
uses by reflection, e.g. uvicorn setting `Server.should_exit`. Before you call something
a false positive, make sure nothing could call it; dead code is usually really dead.
For the real exceptions, write a vulture whitelist: a `.py` file that mentions each name
(it is only parsed, never run), and list it in `[tool.shape]`:

```python
# vulture_whitelist.py: names used by frameworks, not by our code
Server.should_exit  # uvicorn sets it to stop the server
```

```toml
[tool.shape]
dead_code_whitelist = ["vulture_whitelist.py"]   # paths relative to the project root
```

Keep the file outside your packages, so the other checks don't lint it. To start one,
`vulture myapp --min-confidence 60 --make-whitelist > vulture_whitelist.py` lists
everything the kit reports today; delete the lines for code that is really dead.
For whole families of names, vulture's own `[tool.vulture] ignore_names = ["on_*"]` in
pyproject.toml also works, and decorators go in
`[tool.shape.extra_args] vulture = ["--ignore-decorators", "@app.route"]`.
Like the baseline, every exception is a line in a file that shows up in the PR diff and in
the rules-loosened warning. Agents: first check whether something uses the code by name at
runtime (a router, a decorator, `getattr` or a registry, an entry point). If nothing does,
delete it; if something does, ask a human before adding it to the whitelist.

## Error boundaries

`swallowed-errors` fails a bare `except:` or `except Exception` that doesn't keep the
traceback. Almost always the fix is in the code: catch the specific errors you expect,
re-raise, or log with `logger.exception(...)`. A few functions are deliberate boundaries
where none of that is right: a background retry loop that is offline every minute (a
traceback each time is noise), a markdown-to-plain-text fallback, a health probe that
reports the failure to the user. List those, one function each, with the reason:

```toml
[tool.shape.error_boundaries]
"myapp/sync.py:Syncer._loop" = "Runs every minute while offline; the status bar shows the error."
"myapp/doctor.py:check_api" = "A health probe: the failure is the result, shown to the user."
"myapp/bot.py:send.fallback" = "Nested function: plain text if markdown fails; the error is shown."
```

- The key is `path:qualname`, the path relative to the project root (with the src/ layout,
  `src/myapp/...`). It names one function or method; a nested one is `outer.inner`. A whole
  file or class can't be listed, and a catch-all in a function nested inside a listed one
  needs its own entry.
- Only the catch-alls are accepted there: E722 (bare `except:`), BLE001 (`except Exception`
  / `BaseException`), S110 and S112 (such an except that only passes or continues; ruff
  reports these for catch-alls only). TRY203 (an except that only re-raises) still counts:
  it isn't a boundary, just a useless clause. Every other finding in the function
  (complexity, `print`, ...) and catch-alls in every other function still count.
- The reason is required. A key that isn't `path.py:name`, a missing file, a function that
  doesn't exist, a class, or a function that no longer catches everything (a stale entry)
  is a config error: `code-shape` stops with a message naming the entry, so `check` fails.
- `check` prints the accepted boundaries, and the report lists them (function, reason, how
  many catch-alls each accepted) in their own section. `--base` lists every added entry as
  a rule loosened.

This is for intentional boundaries (loops that must keep running, errors shown to the
user), not for debt: existing catch-alls you mean to fix go in the baseline. The setting
lives in pyproject.toml, which the CODEOWNERS template puts under code-owner review, so a
human approves every entry. Agents: don't add one; fix the code or ask.

## Upgrade notes

Pin the kit's version in CI. When you bump it, run `code-shape check` with the new version
first and read what moved before you re-record anything.

**0.3.0.** New command `code-shape init` (see [above](#what-init-writes)). The templates
moved to `code_shape/templates/` (they ship with the package, for `code-shape init`): a
Makefile that includes `tools/code-shape-kit/templates/code-shape.mk` needs the new path.
With the `src/` layout, deptry used to report the project's own package as an undeclared
dependency (`DEP003`); baselined entries for it now show as IMPROVED: run `code-shape
tighten`. A `packages` entry with no folder on disk is now a config error that names the
folder (it used to fail inside the tools). The README was shortened; the detail moved to
`docs/` (this file, [agents.md](agents.md), and `DESIGNING_THE_SHAPE.md`, now
[designing-the-shape.md](designing-the-shape.md)).

**0.2.2.** New setting `[tool.shape.error_boundaries]` (see [Error
boundaries](#error-boundaries)): a reviewed list of functions that may catch every error.
Nothing changes for a project that doesn't use it. For a catch-all that is in the baseline
today and is a deliberate boundary, list the function (with its reason), then run
`code-shape tighten` (its baseline entry now shows as IMPROVED) and commit both.

**0.2.1.** The kit runs ruff without the project's ruff config, so `swallowed-errors` used
to flag the deliberate `except Exception: logger.exception(...)` when the logger was
loguru's. loguru's `logger` is now recognised like `logging`'s: logging the traceback with
`logger.exception(...)` (or `exc_info=True`) passes, while `logger.error(f"... {e}")` still
fails. A project's own logger object goes in `[tool.shape] logger_objects =
["myapp.log.logger"]` (added to loguru's; adding one is listed by `--base` as a rule
loosened). Baselined `swallowed-errors` entries that this fixes show up as IMPROVED: run
`code-shape baseline --only ruff` and commit it.

**0.2.0.** pylint lists only two files for a block copied into three or more, so a further
copy of a baselined block used to pass. The kit now names every file that holds the block,
so such entries get a longer key (`same code as a.py + b.py`) and show up once as NEW and
IMPROVED. Upgrade the same way as for 0.1.3. Also new: a typo in `[tool.shape]` (an unknown
setting, limit or gate) or in `--only`/`skip` is an error, and `exclude` now applies to every
check, not only the size checks. Type errors are recorded per function and mypy error code
instead of per file (so fixing one error while adding another no longer passes): re-record
them with `code-shape baseline --only mypy` and check that the diff touches only
`type-errors` lines.

New gates arrived with 0.2.0: suppression comments (`inline-suppression`), swallowed errors,
bare suppressions, commented-out code, `print()` outside the entry point, mutable defaults,
wildcard imports, risky code (`shell=True`, SQL from strings, hard-coded passwords,
`eval`/`exec`) and boolean flag arguments; mypy now also checks functions without
annotations, reports unused or code-less `# type: ignore`, and leaves out the `[tool.mypy]`
settings that hide errors (see [The tools' own settings](#the-tools-own-settings)). An
existing project will see them as NEW on the first check. Run `code-shape baseline` once
with the new version, review the diff (it should only add entries for the new checks and
`type-errors`), and commit it. If a module other than `cli.py` / `__main__.py` is meant to
print, list it in `[tool.shape] output_modules` instead.

**0.1.3.** Copy-pasted code is now measured the same way on every OS (before, a block
copied into three or more files could be reported for different pairs of files on macOS
and Linux). The `duplicate-code` entries keep their shape, but for such blocks the file pair
or the number of lines in the baseline can change, so the first check may show them as NEW
and IMPROVED. To upgrade safely, run `code-shape check` with the new version and confirm
that only `duplicate-code` entries moved and that no copied block got bigger (`code-shape
report --only pylint` lists them all). Then run `code-shape baseline`, check that its diff
touches only `duplicate-code` lines, and commit it.

## Deliberately left out

| Tool / idea | Why not |
|---|---|
| radon, xenon, wily | Last releases in 2023 (unmaintained). ruff C901 + complexipy cover complexity; the kit's `--trend` covers history. |
| Tach (0.35, maintained) | Good tool, but it overlaps import-linter, which now covers layers, independence, public interfaces (`protected`), private modules and cycles. One boundary tool is enough. |
| pytestarch | Architecture rules written as tests. import-linter does the same in config, with less code. |
| pydeps, emerge | Pictures of the import graph. Useful for humans; not gates. Run them by hand when designing. |
| jscpd | Needs Node; pylint's duplicate-code is Python-native and enough for a Python project. |
| ty, pyright | ty is still 0.0.x (beta) and pyright needs Node. mypy is the stable reference; swap in `skip = ["mypy"]` plus your own step if you prefer another. |
| ruff preview rules (PLR0904, PLR0914, PLR1702, PLR0916, PLC2701) | Preview rules can change between ruff versions. pylint has stable versions of the same checks. |
| lizard | Maintained and multi-language, but duplicates ruff + complexipy for Python. |
| code-maat, CodeScene | Java tool / commercial service. The kit's history check does the parts that matter (~100 lines). |
| History checks as gates | Git history is noisy (squash merges, bulk renames), and a PR can't fix the past. They are trends to watch, not rules. |
| Test coverage % | Says how much code runs under tests, not whether the shape is right. Use pytest-cov separately if you want it. |

## The kit's own code

```
code-shape-kit/
  README.md                  what the kit is for, quick start
  docs/
    agents.md                for a coding agent: set the kit up, work under it
    reference.md             this file
    designing-the-shape.md   the human part: deciding layers, modules, boundaries
    images/                  pictures used by the README
  Makefile                   the kit's own tasks (test, self-check)
  pyproject.toml             the kit as a package; pinned tool versions; its own shape rules
  code_shape/
    catalog.toml             every check in plain language (title, why, fix) - data, not code
    cli.py                   the `code-shape` command: report | check | baseline | tighten | init
    loosening.py             --base REF: lists the rules loosened since a git ref (a warning)
    settings.py              reads [tool.shape]; default limits
    model.py                 Finding / GroupResult data
    source.py                file discovery, "which function is on line N"
    baseline.py              baseline + ratchet
    report.py                markdown report
    trend.py                 re-runs fast checks on past commits (git archive, read-only)
    init/                    `code-shape init`: guesses (package, config modules, layers), fills the templates
    checks/
      linters/               runs the established tools, one module per tool family:
        running.py           runs a tool from a scratch folder; shared output helpers
        rules.py             ruff, complexipy
        pylint_checks.py     pylint (incl. copy-pasted code)
        contracts.py         import-linter
        program.py           vulture, deptry, mypy
      sizes.py               file/class/folder size and depth
      graph.py               import cycles, fan-in, fan-out
      history.py             commit spread, change coupling, hotspots
      concepts.py            where each named concept lives
      tests_mirror.py        tests mirror the source tree
      suppressions.py        counts the comments that silence a tool
    templates/               shipped with the package; `init` fills them in
      shape.toml             [tool.shape] with every default limit and why
      importlinter.toml      contract templates: layers, independence, interfaces, adapters, cycles
      github/code-shape.yml  CI: gate on PRs (with the rules-loosened warning), weekly report with trends
      CODEOWNERS             human review for the config, baseline, whitelist and contracts
      code-shape.mk          make targets for projects
  examples/tidy_app/         a tiny, well-shaped stock-count CLI; the tests break it on purpose
  tests/test_gates.py        proof that each gate fails with a clear message, and the ratchet holds
  tests/test_loosening.py    the rules-loosened warning against a git ref
  tests/test_init.py         `code-shape init`: guesses, never overwriting, dry run
  tests/test_*.py            baseline rules, config validation, reading tool output, suppressions
  .github/workflows/ci.yml   the kit's own CI: tests + `code-shape check` on itself
```

To prove the gates work:

```bash
make install && make test      # inject a violation, expect a clear failure, revert; ratchet; baseline rules; rules-loosened warning
make self-check                # the kit passes its own gates with an empty baseline
```
