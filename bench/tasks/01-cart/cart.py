def line_total(it: dict) -> int:
    """Price times quantity for one item."""
    return it["price"] * it["qty"]


def subtotal(items: list) -> int:
    """Sum of all line totals."""
    return sum(line_total(i) for i in items)


def discount_percent(amount: int) -> int:
    """10 percent from 10000, 5 percent from 5000, otherwise none."""
    if amount >= 10000:
        return 10
    if amount >= 5000:
        return 5
    return 0


def total(items: list) -> int:
    """Subtotal minus the discount for that subtotal."""
    s = subtotal(items)
    return s - s * discount_percent(s) // 100


def _examples():
    assert line_total({"price": 250, "qty": 3}) == 750
    assert subtotal([{"price": 100, "qty": 2}, {"price": 50, "qty": 1}]) == 250
    assert discount_percent(10000) == 10
    assert discount_percent(5000) == 5
    assert discount_percent(4999) == 0
    assert total([{"price": 5000, "qty": 2}]) == 9000
