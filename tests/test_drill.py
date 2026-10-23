"""The failure drill: every scenario must report held, computed not asserted."""

import pytest

from hanko.drill import SCENARIOS, run


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_every_defence_holds(name):
    (result,) = run(name)
    assert result["held"], result["observed"]
    assert result["injected"] and result["promise"]


def test_an_unknown_scenario_is_refused():
    with pytest.raises(KeyError):
        run("nope")
