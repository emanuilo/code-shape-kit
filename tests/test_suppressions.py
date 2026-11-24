from code_shape.checks.suppressions import markers


def test_only_real_comments_count() -> None:
    text = 'NOTE = "# noqa"\nx = 1  # noqa: E501\n"""\n# type: ignore\n"""\n'
    assert markers(text) == [(2, "noqa")]


def test_every_kind_is_found_also_several_in_one_comment() -> None:
    text = (
        "a = 1  # type: ignore[assignment]  # noqa: E501\n"
        "b = 2  # pylint: disable=invalid-name\n"
        "# pylint: disable-next=too-many-locals\n"
        "if b:  # pragma: no cover\n"
        "    pass\n"
        "# ruff: noqa\n"
        "def f():  # complexipy: ignore\n"
        "    eval('1')  # nosec\n"
    )
    kinds = [kind for _, kind in markers(text)]
    assert kinds == [
        "type: ignore",
        "noqa",
        "pylint: disable",
        "pylint: disable",
        "pragma: no cover",
        "noqa",
        "complexipy: ignore",
        "nosec",
    ]


def test_a_comment_that_only_talks_about_a_marker_does_not_count() -> None:
    assert markers("# don't add `# noqa` here; noqa comments hide problems\n") == []
