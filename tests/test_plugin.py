import pytest


def test_plugin_is_registered(pytestconfig: pytest.Config) -> None:
    assert pytestconfig.pluginmanager.has_plugin("mailpit")


def test_plugin_can_be_disabled(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(
        """
        def test_disabled(pytestconfig):
            assert not pytestconfig.pluginmanager.has_plugin("mailpit")
        """
    )

    result = pytester.runpytest("-p", "no:mailpit")

    result.assert_outcomes(passed=1)
