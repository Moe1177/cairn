TOPIC = "order.paid"


def handle(event: dict) -> None:
    print(f"email receipt for order {event['order_id']}")
