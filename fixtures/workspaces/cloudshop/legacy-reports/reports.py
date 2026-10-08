import psycopg

TABLE_NAME = "orders"


def daily_total(conn: psycopg.Connection) -> int:
    return conn.execute(f"select sum(total) from {TABLE_NAME}").fetchone()[0]
