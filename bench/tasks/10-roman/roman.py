TABLE = [(1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"),
         (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]


def to_roman(n: int) -> str:
    """Roman numeral for 1..3999."""
    assert 1 <= n <= 3999
    out = ""
    for value, sym in TABLE:
        while n >= value:
            out += sym
            n -= value
    return out


def _examples():
    assert to_roman(4) == "IV"
    assert to_roman(9) == "IX"
    assert to_roman(1994) == "MCMXCIV"
