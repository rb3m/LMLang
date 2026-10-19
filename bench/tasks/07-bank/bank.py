class InsufficientFunds(Exception):
    def __init__(self, need: int, have: int):
        super().__init__(need, have)


def open_account(name: str) -> dict:
    """New account with zero balance."""
    return {"owner": name, "balance": 0}


def deposit(acct: dict, amount: int) -> dict:
    """Add a positive amount to the balance."""
    assert amount > 0
    return {**acct, "balance": acct["balance"] + amount}


def withdraw(acct: dict, amount: int) -> dict:
    """Remove an amount; fails when the balance is too small."""
    assert amount > 0
    if amount > acct["balance"]:
        raise InsufficientFunds(amount, acct["balance"])
    return {**acct, "balance": acct["balance"] - amount}


def statement(acct: dict) -> str:
    """One-line text such as ana: 15."""
    return f'{acct["owner"]}: {acct["balance"]}'


def _examples():
    assert open_account("ana") == {"owner": "ana", "balance": 0}
    assert deposit({"owner": "ana", "balance": 5}, 10) == {"owner": "ana", "balance": 15}
    assert withdraw({"owner": "ana", "balance": 15}, 10) == {"owner": "ana", "balance": 5}
    try:
        withdraw({"owner": "ana", "balance": 5}, 10)
        assert False
    except InsufficientFunds:
        pass
    assert statement({"owner": "ana", "balance": 15}) == "ana: 15"
