def grade_of(score: int) -> str:
    """90+ Excellent, 75+ Good, 60+ Passing, otherwise Failing."""
    if score >= 90:
        return "Excellent"
    if score >= 75:
        return "Good"
    if score >= 60:
        return "Passing"
    return "Failing"


def letter(g: str) -> str:
    """A, B, C or F for a grade."""
    return {"Excellent": "A", "Good": "B", "Passing": "C", "Failing": "F"}[g]


def average(scores: list) -> int:
    """Integer average of the scores."""
    assert len(scores) > 0
    return int(sum(scores) / len(scores))


def report(scores: list) -> str:
    """Letter for the average score."""
    assert len(scores) > 0
    return letter(grade_of(average(scores)))


def _examples():
    assert grade_of(95) == "Excellent" and grade_of(75) == "Good"
    assert grade_of(60) == "Passing" and grade_of(59) == "Failing"
    assert letter("Excellent") == "A" and letter("Failing") == "F"
    assert average([80, 90, 100]) == 90
    assert report([50, 60, 70]) == "C"
