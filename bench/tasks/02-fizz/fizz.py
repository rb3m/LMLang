def word(n: int) -> str:
    """Fizz for multiples of 3, Buzz for 5, FizzBuzz for both, else the number."""
    if n % 15 == 0:
        return "FizzBuzz"
    if n % 3 == 0:
        return "Fizz"
    if n % 5 == 0:
        return "Buzz"
    return str(n)


def upto(n: int) -> str:
    """Words for 1..n joined by commas."""
    return ",".join(word(i) for i in range(1, n + 1))


def _examples():
    assert word(3) == "Fizz"
    assert word(5) == "Buzz"
    assert word(15) == "FizzBuzz"
    assert word(7) == "7"
    assert upto(5) == "1,2,Fizz,4,Buzz"
