# code-shape-kit

Checks that keep the **shape** of a Python project good: how the code is split
into files and folders, how big things get, and who depends on whom.
It does not hunt for bugs. Bugs are for code review; this is for structure.

Agents write most code now, and nobody reads every line. So the shape has to be
guarded by machines. This kit wires established tools (ruff, pylint, complexipy,
import-linter, vulture, deptry, mypy) plus a few small custom checks into one
command, with one report and one CI gate.

## The workflow

```
1. Decide the shape    (humans)   -> DESIGNING_THE_SHAPE.md
2. Encode it as rules  (config)   -> pyproject.toml: [tool.shape], [tool.importlinter]
3. Tools guard it      (CI)       -> code-shape check, on every pull request
```

Step 1 is judgement: which layers, which modules, where each concept lives.
Steps 2 and 3 are mechanical: once a decision is written as a rule, no agent can
quietly break it.

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
| ratchet | the baseline can only shrink: fixed problems can't come back |

## What each check protects

Gate = fails `code-shape check`. Tracked = report only.

| Area | Check | Protects against | Tool | Default |
|---|---|---|---|---|
| Size | File too long (500 lines) | one file doing two jobs | custom | gate |
| | Class too long (300 lines) | "god classes" every feature edits | custom | gate |
| | Folder has too many modules (12) | flat folders where nothing is grouped | custom | gate |
| | Folder holds too much code (4000 lines) | a hidden sub-system with no boundary | custom | gate |
| | Folders nested too deep (4) | code hidden in deep trees | custom | gate |
| Functions | Too many paths (cyclomatic 10) | functions with too many cases to test | ruff C901 | gate |
| | Hard to read (cognitive 15) | tangled, deeply nested logic | complexipy | gate |
| | Too long (50 statements), too many arguments (6), positional (5), branches (12), returns (6) | functions doing several jobs | ruff PLR09xx | gate |
| | Nested too deep (4), too many variables (15), complicated conditions (5) | code a reader can't hold in their head | pylint | gate |
| Classes | Too much state (12 attributes), too many public methods (20) | classes with many responsibilities | pylint | gate |
| Hidden coupling | Global variables changed in functions | invisible links between distant code | ruff PLW0603 | gate |
| | Restricted API used outside its home | env vars read everywhere; an SDK used all over | ruff TID251 | gate |
| | Private member (`obj._name`) used from outside its class | code coupled to another class's internals | ruff SLF001 | gate |
| | Copy-pasted code (10+ lines) | fixes that must be made in every copy | pylint duplicate-code | gate |
| Structure | Architecture rules (layers, independence, public interfaces, private modules, SDK only in its adapter, no cycles) | the design you decided on eroding | import-linter | gate, no baseline |
| | Modules importing each other in a circle | code that can't be understood or tested alone | custom (grimp) | gate |
| | Module imports too many others (12) | modules that break when anything changes | custom (grimp) | gate |
| Hygiene | Unused code | dead code that misleads readers and agents | vulture | gate |
| | Dependencies out of sync with imports | broken installs, bloat | deptry | gate |
| | Type errors | interfaces between modules drifting apart | mypy | gate |
| Locality of change | Commit spread: how many files and areas a typical commit touches | features that need edits all over | custom (git) | tracked |
| | Change coupling: distant files that always change together | one concept split across far-apart files | custom (git) | tracked |
| | Hotspots: big files that change often | where shape problems cost the most | custom (git) | tracked |
| | Concept spread: how many files mention each concept you name | concepts with no single home | custom | tracked |
| Tests | Test file mirrors each module (`tests/a/test_b.py` for `pkg/a/b.py`) | not knowing where tests live or which are missing | custom | tracked |
| Trend | The fast checks re-run on N past commits | slow decay nobody notices | custom (git archive) | report |

Every failure message says what is wrong, why it matters, and what to do instead,
so an agent can fix it without asking.

## Install

Needs Python 3.11 or newer (import-linter and grimp, which the kit drives, require it).

```bash
# the kit + the pinned tool versions it drives
pip install "code-shape-kit[tools] @ git+https://github.com/emanuilo/code-shape-kit"

# in CI, pin a tag (or a commit sha) so the gates only change when you bump it
pip install "code-shape-kit[tools] @ git+https://github.com/emanuilo/code-shape-kit@v0.1.3"
```

`pip install git+https://github.com/emanuilo/code-shape-kit` alone installs only the
`code-shape` command; the `[tools]` extra adds ruff, pylint, mypy and the rest. Leave it
out only if your environment already provides those tools.

Tools are pinned exactly (see `pyproject.toml`): a gate must not start failing because CI
installed a newer linter. The project itself must be installed in the same environment
(mypy and deptry need its dependencies).

## The commands

```bash
code-shape report              # run everything, write code-shape-report.md, never fail
code-shape report --trend 8    # ...plus the same numbers for 8 past commits
code-shape check               # CI gate: fail on NEW or WORSE violations
code-shape baseline            # record today's violations (existing projects)
code-shape tighten             # lock in improvements (only ever shrinks the baseline)
```

Options: `--root DIR` (project folder), `--config FILE` (a TOML with `[tool.shape]`, if not
in pyproject.toml), `--baseline FILE`, `--out FILE`, `--only sizes,ruff,...` (run some
check groups). `templates/code-shape.mk` has the same as `make shape-report`,
`make shape-check`, `make shape-baseline`, `make shape-tighten`.

**How the baseline works.** `.code-shape-baseline.json` lists known problems by place
(file + function name, no line numbers, so unrelated edits don't disturb it) and by size
(e.g. "orders.py: 640 lines"). `check` then fails when:

- a problem is **new** (not in the baseline);
- a known problem got **worse** (640 -> 660 lines);
- a known problem got **better** but the baseline wasn't updated. Run `code-shape tighten`
  and commit. That is the ratchet: once orders.py is down to 560 lines, 600 fails.

The baseline file sits in the project root by default. To keep it elsewhere, set a path
relative to the project root, e.g. `baseline = ".code-shape/baseline.json"` under
`[tool.shape]`; `baseline` and `tighten` create the folder if needed. `--baseline FILE`
overrides the setting.

Inline suppressions (`# noqa`) are ignored by the shape checks on purpose. The baseline
is the one visible place for exceptions, and every addition to it shows up in the PR diff.
Architecture contracts are never baselined by the kit: use import-linter's own
`ignore_imports` list for existing violations (see `templates/importlinter.toml`).

**Upgrading to 0.1.3.** Copy-pasted code is now measured the same way on every OS
(before, a block copied into three or more files could be reported for different pairs of
files on macOS and Linux). The `duplicate-code` entries keep their shape, but for such
blocks the file pair or the number of lines in the baseline can change, so the first check
may show them as NEW and IMPROVED. To upgrade safely, run `code-shape check` with the new
version and confirm that only `duplicate-code` entries moved and that no copied block got
bigger (`code-shape report --only pylint` lists them all). Then run `code-shape baseline`,
check that its diff touches only `duplicate-code` lines, and commit it.

## New project

1. Read `DESIGNING_THE_SHAPE.md`. Write down your concepts and layers before the code exists.
2. Paste `templates/shape.toml` and `templates/importlinter.toml` into `pyproject.toml`.
   Fill in your package name, layers, adapters (`banned_api`) and concepts.
3. Copy `templates/github/code-shape.yml` to `.github/workflows/`.
4. No baseline needed: every violation fails from day one, so the shape never decays.
5. Tell your agents (CLAUDE.md / AGENTS.md): "Run `code-shape check` before you finish.
   Fix what it reports; never add to the baseline or weaken a limit without asking."

## Existing project

1. Run `code-shape report --trend 8`. Read the summary, the worst offenders and the
   concept table.
2. Decide the target shape (`DESIGNING_THE_SHAPE.md`) and write the import-linter contracts.
   For imports that break them today, list them under `ignore_imports`.
3. Adjust limits only where the default is wrong for the project, not to make today's code pass.
   The baseline is for that.
4. Run `code-shape baseline`, commit `.code-shape-baseline.json`, add the CI workflow.
   From now on nothing gets worse.
5. Pay debt down hotspot by hotspot (the report lists them). After each fix, `code-shape tighten`.

## When a check fails (for agents)

- Read the `fix:` line and do that. Split the file, extract the function, move the import.
- Don't rename or move code just to dodge a check: a moved problem is a new problem.
- Don't edit the baseline by hand, add `# noqa`, or raise a limit. If you believe the
  rule is wrong here, stop and ask a human.

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
Like the baseline, every exception is a line in a file that shows up in the PR diff.
Agents: ask a human before adding to the whitelist.

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

## Layout

```
code-shape-kit/
  README.md                  this file
  DESIGNING_THE_SHAPE.md     the human part: deciding layers, modules, boundaries
  Makefile                   the kit's own tasks (test, self-check)
  pyproject.toml             the kit as a package; pinned tool versions; its own shape rules
  code_shape/
    catalog.toml             every check in plain language (title, why, fix) - data, not code
    cli.py                   the `code-shape` command: report | check | baseline | tighten
    settings.py              reads [tool.shape]; default limits
    model.py                 Finding / GroupResult data
    source.py                file discovery, "which function is on line N"
    baseline.py              baseline + ratchet
    report.py                markdown report
    trend.py                 re-runs fast checks on past commits (git archive, read-only)
    checks/
      linters.py             runs ruff, complexipy, pylint, import-linter, vulture, deptry, mypy
      sizes.py               file/class/folder size and depth
      graph.py               import cycles, fan-in, fan-out
      history.py             commit spread, change coupling, hotspots
      concepts.py            where each named concept lives
      tests_mirror.py        tests mirror the source tree
  templates/
    shape.toml               [tool.shape] with every default limit and why
    importlinter.toml        contract templates: layers, independence, interfaces, adapters, cycles
    github/code-shape.yml    CI: gate on PRs, weekly report with trends
    code-shape.mk            make targets for projects
  examples/tidy_app/         a tiny, well-shaped stock-count CLI; the tests break it on purpose
  tests/test_gates.py        proof that each gate fails with a clear message, and the ratchet holds
  .github/workflows/ci.yml   the kit's own CI: tests + `code-shape check` on itself
```

## Proof the gates work

```bash
make install && make test      # 23 tests: inject a violation, expect a clear failure, revert; ratchet; baseline rules
make self-check                # the kit passes its own gates with an empty baseline
```

Tool versions verified November 2026: ruff 0.17.6, complexipy 9.0.0, pylint 4.1.4,
import-linter 2.17 (grimp 3.20), vulture 2.16, deptry 0.25.1, mypy 2.4.1.
