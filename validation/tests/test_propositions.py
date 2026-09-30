"""One test per validation check (`checks`). A failure prints
the claim, the prediction and what was observed. The report
(`python -m report`, run by `scripts/check_sim.sh`) runs the same
checks, so CI deselects these (`-m "not checks"`)."""

import pytest

import checks


@pytest.mark.checks
@pytest.mark.parametrize("check", checks.ALL, ids=lambda f: f.__name__)
def test_check(check):
    c = check()
    assert c.passed, (
        f"\n{c.id} ({c.paper}) FAILED\n  claim:    {c.claim}\n"
        f"  expected: {c.expected}\n  observed: {c.observed}\n"
    )


def test_every_check_is_named_after_its_function():
    for f in checks.ALL:
        assert f.__name__.lstrip("_") == f.__name__
    assert len({f.__name__ for f in checks.ALL}) == len(checks.ALL)
