from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()


class Order(BaseModel):
    id: str
    status: str = "pending"
    total: int


@app.post("/orders")
def create_order(order: Order) -> Order:
    return order


@app.get("/orders/{order_id}")
def get_order(order_id: str) -> Order:
    return Order(id=order_id, total=0)
