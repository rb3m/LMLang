def divides(d: int, n: int) -> bool:
    """True when d divides n; false for d = 0."""
    return d != 0 and n % d == 0


def is_prime(n: int) -> bool:
    """True when n >= 2 has no divisor between 2 and n-1."""
    return n >= 2 and not any(divides(d, n) for d in range(2, n))


def count_below(limit: int) -> int:
    """How many primes are smaller than limit."""
    return sum(1 for k in range(0, limit) if is_prime(k))


def _examples():
    assert divides(3, 12) and not divides(5, 12) and not divides(0, 12)
    assert is_prime(2) and not is_prime(1) and not is_prime(91) and is_prime(97)
    assert count_below(10) == 4
    assert count_below(2) == 0
