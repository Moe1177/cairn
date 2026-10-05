NEXT = {"requested": "accepted", "accepted": "in_progress", "in_progress": "completed"}


def advance(status: str) -> str:
    return NEXT.get(status, status)
