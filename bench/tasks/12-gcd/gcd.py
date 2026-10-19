def gcd(a: int, b: int) -> int:
    """Euclid's algorithm for non-negative integers."""
    assert a >= 0 and b >= 0
    return a if b == 0 else gcd(b, a % b)


def lcm(a: int, b: int) -> int:
    """Least common multiple of positive integers."""
    assert a > 0 and b > 0
    return a * b // gcd(a, b)


def coprime(a: int, b: int) -> bool:
    """True when the only common divisor is 1."""
    assert a >= 0 and b >= 0
    return gcd(a, b) == 1


def _examples():
    assert gcd(12, 18) == 6
    assert gcd(7, 0) == 7
    assert lcm(4, 6) == 12
    assert coprime(8, 15) and not coprime(8, 12)
