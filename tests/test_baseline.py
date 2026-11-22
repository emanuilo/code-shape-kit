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
