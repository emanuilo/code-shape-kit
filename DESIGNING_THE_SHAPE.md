# Designing the shape

Tools can guard a shape. They can't choose one. This page is the human part: a short,
practical way to decide how a project should be split, and how to turn each decision
into a rule the kit enforces.

## 1. List the concepts

A concept is an idea a change request is about: "reminders", "billing", "Slack support",
"how notes are searched". Write down 8-15 of them. Good sources: the README's feature
list, the nouns in your issue tracker, the last 20 commit messages.

For each concept, ask: **which files would I touch to change it?** The goal is a few files
in one place. If the answer is "six files in five folders", the concept has no home.

## 2. Give every concept one home

A home is a module, or a package when the concept is big. The home owns the concept's
data, rules and storage. Everyone else calls the home's **public interface**: the few
functions and classes it exports from `__init__.py`.

- One concept, one home. Two homes for one concept means edits in two places.
- A home for "things that have nothing in common" (`utils.py`, `helpers.py`, `common.py`)
  is not a home. Name modules after what they own.
- Name files after the thing, not the role: `bot/telegram.py`, not `bot/handlers.py`.

## 3. Pick the layers

Layers say which way dependencies point. A typical stack, top to bottom:

```
entry points   cli.py, web app, bot runners      read input, call features, print output
features       reminders/, billing/, search/     the use cases: rules + orchestration
adapters       storage/, llm/, telegram/         talk to the outside world (DB, SDKs, network)
core           domain models, pure functions     no I/O at all
config         settings                          imports nothing from the project
```

Rule: a module may import from lower layers only. A feature never imports the CLI; the
config never imports a feature. When a lower layer needs something from a higher one,
pass it in (a function argument or a small protocol) instead of importing it.

Features in the same layer should be **independent**: reminders doesn't import billing.
If they must cooperate, a higher layer (an entry point or a coordinator) wires them.

## 4. Put every outside thing behind an adapter

Each external system gets exactly one adapter module: the database, each SDK (OpenAI,
Slack, Stripe), the file system layout, the environment variables. Only the adapter
imports the SDK. The rest of the code calls the adapter's functions.

Why: replacing the SDK, adding retries, faking it in tests, or logging all calls becomes
a one-file change. Environment variables are the most common leak: read them in
`config.py` only, and pass values down.

## 5. When to split

Split a **file** when any of these is true:

- it passes ~500 lines, or a class passes ~300;
- it has two groups of functions that don't call each other;
- you'd describe it with "and" ("parses the input *and* talks to the API");
- two different kinds of change keep landing in it (it is a hotspot in the report);
- its tests need unrelated fixtures.

Split a **package** when:

- it has more than ~12 modules, or more than ~4,000 lines;
- a subgroup of its modules mostly imports each other: that subgroup is a sub-package;
- concepts inside it start getting prefixes (`slack_*.py`, `whatsapp_*.py`): make
  `slack/` and `whatsapp/` packages.

**Don't** split when the pieces would always change together anyway, when it creates
one-function modules that only forward calls, or when it makes the tree deeper than
3-4 levels. A split is real if each new piece can be explained in one sentence and
tested on its own.

## 6. Check locality before you commit to a shape

Take the five most likely future changes ("add a Discord bot", "switch embeddings
provider", "add a new setting") and list the files each would touch in the proposed
shape. Aim for **three files or fewer, in one area**. If a change needs more, move
code until it doesn't. This one exercise catches most shape problems early.

## 7. Encode each decision as a rule

| Decision | Rule | Where |
|---|---|---|
| Layers and their order | `layers` contract, `exhaustive = true` | `[tool.importlinter]` |
| Features don't import each other | `independence` contract | `[tool.importlinter]` |
| A package's internals are private | `protected` contract, or name them `_private.py` + `private_modules` contract | `[tool.importlinter]` |
| An SDK only in its adapter | `protected` contract on the SDK package, or `banned_api` with `allowed` | either |
| Env vars only in config | `config_modules` (on by default) | `[tool.shape]` |
| Sizes and complexity | `[tool.shape.limits]` (defaults are sensible) | `[tool.shape]` |
| Where each concept lives | `[tool.shape.concepts]` with a `home` | `[tool.shape]` (tracked) |
| Tests mirror the source | follow `tests/<path>/test_<module>.py` | tracked |

Write `broken_contract_guidance` in each contract: it is what an agent reads when it
breaks the rule.

## 8. Example

A chat assistant with three chat apps, two AI providers, and memory. A shape where each
likely change stays local:

```
assistant/
  cli.py                    entry point: parse args, pick a platform, run it
  config.py                 all settings; the only reader of env vars
  agent/                    feature: one conversation turn (context, prompt, tools)
    __init__.py             public: Agent
    prompts.py              the system prompt text
    tools/                  one module per tool group: schema + implementation together
  memory/                   feature: notes, index, search, consolidation
    __init__.py             public: Memory (save, search, consolidate)
    notes.py  index.py  search.py  consolidation.py
  reminders/                feature
  platforms/                adapters for chat apps
    __init__.py             registry: name -> run(config)
    inbound.py              shared: voice -> text, links -> summaries, build the agent prompt
    telegram.py  slack.py  whatsapp.py    only receive / download / send
  llm/                      adapters for AI providers, behind one protocol
    base.py  anthropic.py  openai.py
```

"Add Discord" = one new file in `platforms/` plus one registry line. "Swap the
transcription model" = `inbound.py` only. "Add a tool" = one file in `agent/tools/`.

## 9. What only a human can judge

The tools measure size, direction and spread. They can't tell whether:

- a name says what the module does;
- an interface is the *right* one (small, hard to misuse), not just small;
- a split followed a real seam or just cut a file in half;
- an abstraction earns its keep, or is a layer of forwarding calls.

Review these by reading the module list and each package's `__init__.py`, not every line.
That is a 10-minute review even on a big project.
