def on_trip_completed(event: dict) -> str:
    return f"receipt for trip {event['trip_id']}"


def on_payout_sent(event: dict) -> str:
    return f"payout of {event['amount_cents']} sent"
