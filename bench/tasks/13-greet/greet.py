def greeting(name: str) -> str:
    """Hello line for one name."""
    return "Hello, " + name


def announce(names: list) -> None:
    """Print one greeting per name."""
    for n in names:
        print(greeting(n))


def _examples():
    assert greeting("Ana") == "Hello, Ana"
