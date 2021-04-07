"""Test Cases for Cloclify"""

from cloclify.main import main


def test_main_succeds() -> None:
    """It exits with a status code of zero."""
    result = main()
    assert result == 0
