"""Test Cases for Cloclify"""

import cloclify


def test_main_succeds() -> None:
    """It exits with a status code of zero."""
    result = cloclify.main()
    assert result == 0
