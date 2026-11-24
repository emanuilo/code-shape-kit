# Designing the shape

Tools can guard a shape. They can't choose one. This page is the human part: a short,
practical way to decide how a project should be split, and how to turn each decision
into a rule the kit enforces.

The **shape** of a project is how its code is split into files and folders, and which
parts may use which. A good shape means most changes touch a few files in one place.

## 1. List the concepts

A **concept** is one thing people ask you to change. In a web shop: "checkout",
"refunds", "stock levels". In a CLI tool: "the config file", "the `sync` command".
In a data pipeline: "loading the CSV files", "removing duplicates", "the weekly report".

Write down 8-15 of them. Good places to look: the feature list in the README, the
words that keep coming up in your issues, the last 20 commit messages.

For each concept, ask: **which files would I touch to change it?** The answer should be
a few files in one folder. If it is "six files in five folders", the concept has no home.

## 2. Give every concept one home

A **home** is the module (one `.py` file), or the package (a folder of modules) when the
concept is big, that owns the concept: its data, its rules, how it is saved.

Other code uses the home only through its **public interface**: the few functions and
classes it offers to the rest of the project, usually the ones listed in its `__init__.py`.
Everything else inside is private and can change freely.

- One concept, one home. Two homes for one concept means every change is made twice.
- `utils.py`, `helpers.py` and `common.py` are not homes. They collect things that have
  nothing in common. Name a module after what it owns.
- Name files after the thing, not the kind of code: `orders/pricing.py`, not
  `orders/logic.py`; `export/csv.py`, not `export/handlers.py`.

## 3. Pick the layers

A **layer** is a group of modules at the same level. Layers decide which way imports
point: a module may import from layers below it, never from layers above.
A common stack, top to bottom:

```
entry points   cli.py, api/ (web routes), worker.py   read input, call features, send output
features       orders/, refunds/, reports/            what the program does: rules and steps
adapters       db/, email.py, stripe_client.py        talk to the outside world
domain         models.py, pure functions              plain data and rules, no I/O
config         config.py                              settings; imports nothing from the project
```

(**I/O** means input and output: reading files, calling the network, using a database.)

So a feature never imports the CLI, and the config never imports a feature. When a
lower layer needs something from a higher one, pass it in as an argument instead of
importing it.

Features in the same layer should be **independent**: `refunds` doesn't import `reports`.
If two features must work together, the code above them (an entry point) connects them.

Small projects can skip layers they don't need. A 500-line CLI may only have
`cli.py`, two feature modules and `config.py`.

## 4. Put every outside thing behind an adapter

An **adapter** is the one module that talks to one outside system, so the rest of the
code doesn't have to. Typical outside systems: the database, a payment service, an email
service, cloud storage (S3), another team's HTTP API, the file layout on disk, and the
environment variables.

Only the adapter imports the third-party package (the SDK). Everyone else calls the
adapter's functions.

Why: swapping the service, adding retries, faking it in tests, or logging every call
becomes a one-file change. Environment variables are the most common leak: read them
in `config.py` only, and pass the values down.

## 5. When to split

Split a **file** when any of these is true:

- it passes ~500 lines, or a class passes ~300;
- it has two groups of functions that don't call each other;
- you describe it with "and" ("parses the order *and* sends the email");
- two different kinds of change keep landing in it (it is a "hotspot" in the report);
- its tests need setup that has nothing to do with each other.

Split a **package** (folder) when:

- it has more than ~12 modules, or more than ~4,000 lines;
- a group of its modules mostly import each other: that group wants its own sub-folder;
- file names start sharing a prefix (`invoice_pdf.py`, `invoice_email.py`,
  `invoice_totals.py`): make an `invoices/` package with `pdf.py`, `email.py`, `totals.py`.

**Don't split** when the pieces would always change together anyway, when it creates
one-function modules that only pass calls along, or when it makes the folders deeper
than 3-4 levels. A split is real if you can explain each new piece in one sentence and
test it on its own.

## 6. Test the shape with likely changes

Before you settle on a shape, take the five changes you expect most often and list the
files each one would touch. For example:

- web shop: "accept PayPal as well as cards", "add a discount code field";
- CLI tool: "add a `--json` output option", "add a new command";
- data pipeline: "read a new source format", "add a column to the report";
- REST service: "add a new endpoint", "move uploaded files from disk to S3".

Aim for **three files or fewer, in one folder**, per change. If a change needs more,
move code until it doesn't. This one exercise catches most shape problems early.

## 7. Turn each decision into a rule

| Decision | Rule | Where |
|---|---|---|
| Layers and their order | `layers` contract, `exhaustive = true` | `[tool.importlinter]` |
| Features don't import each other | `independence` contract | `[tool.importlinter]` |
| A package's insides are private | `protected` contract, or name them `_private.py` + `private_modules` contract | `[tool.importlinter]` |
| A third-party package only in its adapter | `protected` contract on that package, or `banned_api` with `allowed` | either |
| Environment variables only in config | `config_modules` (on by default) | `[tool.shape]` |
| Only entry points print | `output_modules` (default: `cli.py`, `__main__.py`) | `[tool.shape]` |
| Sizes and complexity | `[tool.shape.limits]` (the defaults are sensible) | `[tool.shape]` |
| Where each concept lives | `[tool.shape.concepts]` with a `home` | `[tool.shape]` (tracked) |
| Tests mirror the source | `tests/<path>/test_<module>.py` | tracked |

Write `broken_contract_guidance` in each contract. It is what an agent reads when it
breaks the rule, so say what to do instead.

Changing a rule later is a decision too, and the easiest way for an agent to get a red
check green. In CI, `code-shape check --base origin/main` lists every rule a pull request
loosens (a limit raised, a gate or contract removed, an allowance widened, a baseline entry
or a suppression comment added), and `templates/CODEOWNERS` makes the files that hold the
rules need a human's review. When you approve such a change, you are changing the shape:
check that it is still the one you decided on.

## 8. Two examples

**A web shop backend.** Each feature has a home; each outside service has one adapter.

```
shop/
  api/                  entry point: web routes; parse the request, call a feature, return JSON
  config.py             all settings; the only reader of environment variables
  orders/               feature: cart, checkout, order status
    __init__.py         public: place_order, cancel_order
    pricing.py  checkout.py  status.py
  inventory/            feature: stock levels, reservations
  payments/             feature: charge, refund
    __init__.py         public: charge, refund
    gateway.py          the rules every payment provider follows
    stripe.py           adapter: the only module that imports the stripe package
  db/                   adapter: tables and queries; others call its functions
  email.py              adapter: sends emails
```

"Accept PayPal" = one new `payments/paypal.py` plus one line that registers it.
"Change the tax rule" = `orders/pricing.py` only.

**A data pipeline** that loads files, cleans them and writes a report.

```
pipeline/
  cli.py                entry point: `pipeline run --date 2026-01-31`
  config.py             paths and credentials
  sources/              adapters, one per input: csv.py  excel.py  s3.py
  cleaning/             feature: dedupe.py  dates.py  currencies.py
  report/               feature: build.py (the numbers)  render.py (the HTML)
```

"Read Parquet files too" = one new file in `sources/`. "Fix how dates are parsed" =
`cleaning/dates.py` only.

## 9. What only a human can judge

The tools measure size, direction and spread. They can't tell whether:

- a name says what the module does;
- an interface is the *right* one (small and hard to misuse), not just small;
- a split followed a real seam or just cut a file in half;
- an abstraction earns its keep, or only passes calls along.

Review these by reading the list of modules and each package's `__init__.py`, not
every line. That takes about 10 minutes, even on a big project.
