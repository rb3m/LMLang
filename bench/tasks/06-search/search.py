from typing import Optional


def find_index(xs: list, target: int) -> Optional[int]:
    """Index of the first occurrence of target, if any."""
    for i, x in enumerate(xs):
        if x == target:
            return i
    return None


def get_or(xs: list, i: int, default: int) -> int:
    """Element at index i, or default when out of range."""
    return xs[i] if 0 <= i < len(xs) else default


def contains(xs: list, target: int) -> bool:
    """True when target occurs in xs."""
    return find_index(xs, target) is not None


def _examples():
    assert find_index([5, 6, 7], 7) == 2
    assert find_index([5, 6, 7], 9) is None
    assert get_or([5, 6], 1, 0) == 6
    assert get_or([5, 6], 4, -1) == -1
    assert contains([1, 2], 2) and not contains([1, 2], 3)
