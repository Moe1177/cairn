REFUND = "INSERT INTO refunds (order_id, amount) VALUES (%s, %s)"
MARK_REFUNDED = "UPDATE orders SET status = 'refunded' WHERE id = %s"


def refund(db, order_id: str, amount: int) -> None:
    db.execute(REFUND, (order_id, amount))
    db.execute(MARK_REFUNDED, (order_id,))
