from datetime import datetime

from pydantic import BaseModel


class Trip(BaseModel):
    id: str
    rider_id: str
    driver_id: str | None = None
    status: str = "requested"
    fare_cents: int
    created_at: datetime
