from code_shape import baseline as bl
from code_shape.model import Finding, GroupResult

GATES = ["file-lines", "import-contracts"]


def results(*findings: Finding, ok: bool = True) -> list[GroupResult]:
    return [GroupResult("sizes", list(findings), error="" if ok else "crashed")]


def big(lines: int) -> Finding:
    return Finding("file-lines", "app/big.py", value=lines, limit=500)


def test_known_debt_passes_and_growth_fails() -> None:
    base = bl.record(results(big(700)), GATES)
    assert not bl.compare(results(big(700)), GATES, base).new
    worse = bl.compare(results(big(710)), GATES, base).worse
    assert worse and worse[0][1] == 700


def test_improvement_must_be_locked_in() -> None:
    base = bl.record(results(big(700)), GATES)
    assert bl.compare(results(big(650)), GATES, base).improved
    tightened = bl.tighten(results(big(650)), GATES, base)
    assert tightened["sizes"]["file-lines|app/big.py|"] == 650
    assert bl.compare(results(big(700)), GATES, tightened).worse  # can't slide back


def test_tighten_never_adds_and_keeps_groups_that_did_not_run() -> None:
    base = bl.record(results(big(700)), GATES)
    new = Finding("file-lines", "app/other.py", value=900, limit=500)
    assert "file-lines|app/other.py|" not in bl.tighten(results(big(700), new), GATES, base)["sizes"]
    assert bl.tighten(results(ok=False), GATES, base) == base


def test_contracts_are_never_baselined() -> None:
    broken = Finding("import-contracts", "pyproject.toml", "Layers")
    assert bl.record(results(broken), GATES) == {}
    assert bl.compare(results(broken), GATES, {}).new == [broken]


def test_findings_sharing_a_key_count_the_worst_in_any_order() -> None:
    # A property's getter and setter are both `Knob.level`: same key, two numbers.
    getter = Finding("file-lines", "app/big.py", value=700, limit=500)
    setter = Finding("file-lines", "app/big.py", value=600, limit=500)
    for listed in ((getter, setter), (setter, getter)):
        base = bl.record(results(*listed), GATES)
        assert base == {"sizes": {"file-lines|app/big.py|": 700}}
        for again in ((getter, setter), (setter, getter)):
            comparison = bl.compare(results(*again), GATES, base)
            assert not (comparison.new or comparison.worse or comparison.improved)


def test_rebaseline_keeps_groups_that_did_not_run() -> None:
    # e.g. `code-shape baseline --only sizes`, or mypy crashed: the other groups' debt must stay recorded
    base = {"sizes": {"file-lines|app/big.py|": 700}, "mypy": {"type-errors|app/x.py|": 3}}
    assert bl.rebaseline(results(big(650)), GATES, base) == {
        "sizes": {"file-lines|app/big.py|": 650},
        "mypy": {"type-errors|app/x.py|": 3},
    }
    assert bl.rebaseline(results(ok=False), GATES, base) == base


def test_a_known_copy_with_one_more_copy_is_new_not_fixed() -> None:
    pair = Finding("duplicate-code", "app/a.py", "same code as app/b.py", 12, 10)
    three = Finding("duplicate-code", "app/a.py", "same code as app/b.py + app/c.py", 12, 10)
    gone = Finding("file-lines", "app/big.py", value=700, limit=500)
    gates = [*GATES, "duplicate-code"]
    base = bl.record([GroupResult("pylint", [pair]), GroupResult("sizes", [gone])], gates)
    comparison = bl.compare([GroupResult("pylint", [three]), GroupResult("sizes", [])], gates, base)
    assert comparison.new == [three]
    assert comparison.improved == ["file-lines|app/big.py| is fixed"]  # other fixed entries still show


def test_a_known_copy_left_in_fewer_files_is_improved_not_new() -> None:
    three = Finding("duplicate-code", "app/a.py", "same code as app/b.py + app/c.py", 12, 10)
    two = Finding("duplicate-code", "app/b.py", "same code as app/c.py", 12, 10)
    gates = [*GATES, "duplicate-code"]
    base = bl.record([GroupResult("pylint", [three])], gates)
    comparison = bl.compare([GroupResult("pylint", [two])], gates, base)
    assert not comparison.new and not comparison.worse
    assert comparison.improved == [f"{three.key} is now only {two.key}"]

    tightened = bl.tighten([GroupResult("pylint", [two])], gates, base)
    assert tightened == {"pylint": {two.key: 12}}
    assert not bl.compare([GroupResult("pylint", [two])], gates, tightened).improved
    assert bl.compare([GroupResult("pylint", [three])], gates, tightened).new == [three]  # can't come back

    # one copy left is no copy at all: just fixed
    assert bl.compare([GroupResult("pylint", [])], gates, base).improved == [f"{three.key} is fixed"]


def test_a_known_copy_in_fewer_files_but_longer_is_new() -> None:
    three = Finding("duplicate-code", "app/a.py", "same code as app/b.py + app/c.py", 12, 10)
    longer = Finding("duplicate-code", "app/b.py", "same code as app/c.py", 20, 10)
    other = Finding("duplicate-code", "app/b.py", "same code as app/d.py", 12, 10)
    gates = [*GATES, "duplicate-code"]
    base = bl.record([GroupResult("pylint", [three])], gates)
    assert bl.compare([GroupResult("pylint", [longer])], gates, base).new == [longer]
    assert bl.compare([GroupResult("pylint", [other])], gates, base).new == [other]  # not a subset
    # the old copies are all still there: a pair inside them is another block, so new
    pair = Finding("duplicate-code", "app/b.py", "same code as app/c.py", 11, 10)
    assert bl.compare([GroupResult("pylint", [three, pair])], gates, base).new == [pair]
    assert bl.tighten([GroupResult("pylint", [longer])], gates, base) == {}
