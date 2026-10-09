"""Checks of arguments, shared by the clients and the models."""

from collections.abc import Iterable


def strings(values: Iterable[str], what: str) -> list[str]:
    """``values`` as a list; a single string is refused.

    A string is an iterable of its characters, so ``list("urgent")`` would be
    six one-letter tags, and ``ignore="linkedin.com"`` would ignore every link
    that contains an "i".
    """
    if isinstance(values, str):
        raise TypeError(f"Expected a list of {what}, got a single string")
    return list(values)
