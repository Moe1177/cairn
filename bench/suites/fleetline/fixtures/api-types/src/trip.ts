export type TripStatus = "requested" | "accepted" | "in_progress" | "completed" | "cancelled";

export interface Trip {
  id: string;
  rider_id: string;
  driver_id: string | null;
  status: TripStatus;
  fare_cents: number;
  created_at: string;
}
