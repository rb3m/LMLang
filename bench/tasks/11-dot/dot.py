def dot(xs: list, ys: list) -> int:
    """Sum of pairwise products; both lists must have equal length."""
    assert len(xs) == len(ys)
    return sum(a * b for a, b in zip(xs, ys))


def norm_sq(xs: list) -> int:
    """Squared length of a vector."""
    return dot(xs, xs)


def _examples():
    assert dot([1, 2, 3], [4, 5, 6]) == 32
    assert norm_sq([3, 4]) == 25
