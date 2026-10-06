import os

from fastapi import APIRouter, FastAPI

app = FastAPI()
router = APIRouter(prefix="/trips")
AUDIENCE = os.getenv("INTERNAL_AUTH_AUDIENCE")


@app.get("/health")
def health():
    return "ok"


@router.get("/{trip_id}")
def get_trip(trip_id: str):
    producer.send("trip.completed", trip_id.encode())
    producer.send("events", b"x")
    return {"id": trip_id}
