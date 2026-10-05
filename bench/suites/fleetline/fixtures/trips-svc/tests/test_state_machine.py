from app.state_machine import advance


def test_advance():
    assert advance("requested") == "accepted"
