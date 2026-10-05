from pydantic import BaseModel


class Driver(BaseModel):
    id: str
    name: str
    license_no: str
    vehicle_id: str | None = None
