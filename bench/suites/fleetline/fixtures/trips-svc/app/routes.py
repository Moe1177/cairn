from fastapi import APIRouter

from app.models import Trip
from app.state_machine import advance

router = APIRouter()

INSERT_TRIP = "INSERT INTO trips (id, rider_id, status, fare_cents) VALUES (%s, %s, %s, %s)"


@router.post("/trips")
def create_trip(trip: Trip) -> Trip:
    return trip


@router.post("/trips/{trip_id}/advance")
def advance_trip(trip_id: str) -> dict:
    return {"id": trip_id, "status": advance("requested")}
