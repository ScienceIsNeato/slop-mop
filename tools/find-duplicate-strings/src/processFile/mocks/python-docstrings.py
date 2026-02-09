"""Module docstring that should be ignored."""


def my_function():
    """Return reason for skipping - a common docstring."""
    return "actual string constant"


class MyClass:
    """Another docstring with the same text."""

    def method(self):
        """Return reason for skipping - a common docstring."""
        x = "actual string constant"
        return x


# Multi-line docstring
def another():
    """
    This is a multi-line docstring.
    It spans several lines.
    """


# Regular strings should still be captured
msg = "this is a regular string"
msg2 = "this is a regular string"
