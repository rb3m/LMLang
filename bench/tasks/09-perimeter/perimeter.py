def of(sh: dict) -> int:
    """Perimeter of one shape; circles use 6 as 2*pi."""
    kind, a = sh["$v"], sh["args"]
    if kind == "Circle":
        return 6 * a[0]
    if kind == "Rect":
        return 2 * (a[0] + a[1])
    if kind == "Square":
        return 4 * a[0]
    if kind == "Triangle":
        return a[0] + a[1] + a[2]
    raise ValueError(kind)


def total(shapes: list) -> int:
    """Sum of the perimeters."""
    return sum(of(s) for s in shapes)


def _examples():
    assert of({"$v": "Circle", "args": [2]}) == 12
    assert of({"$v": "Rect", "args": [2, 3]}) == 10
    assert of({"$v": "Square", "args": [4]}) == 16
    assert of({"$v": "Triangle", "args": [3, 4, 5]}) == 12
    assert total([{"$v": "Square", "args": [1]}, {"$v": "Rect", "args": [1, 1]}]) == 8
