def maximum(xs: list) -> int:
    """Largest element."""
    assert len(xs) > 0
    return max(xs)


def minimum(xs: list) -> int:
    """Smallest element."""
    assert len(xs) > 0
    return min(xs)


def mean(xs: list) -> int:
    """Integer mean, rounded down."""
    assert len(xs) > 0
    return sum(xs) // len(xs)


def spread(xs: list) -> int:
    """Largest minus smallest element."""
    assert len(xs) > 0
    return maximum(xs) - minimum(xs)


def _examples():
    assert maximum([3, 9, 2]) == 9
    assert minimum([3, 9, 2]) == 2
    assert mean([1, 2, 3, 4]) == 2
    assert spread([3, 9, 2]) == 7
