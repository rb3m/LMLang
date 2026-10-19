def next_value(n: int) -> int:
    """Next Collatz value: halve when even, else 3n+1."""
    return n // 2 if n % 2 == 0 else 3 * n + 1


def steps(n: int) -> int:
    """Number of steps to reach 1."""
    assert n > 0
    return 0 if n == 1 else 1 + steps(next_value(n))


def _examples():
    assert next_value(6) == 3
    assert next_value(7) == 22
    assert steps(1) == 0
    assert steps(6) == 8
