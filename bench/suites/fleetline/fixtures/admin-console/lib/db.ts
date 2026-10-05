import { sql } from "./sql";

export const recentTrips = () =>
  sql`SELECT id, status, fare_cents, created_at FROM trips ORDER BY created_at DESC LIMIT 100`;

export const driverById = (id: string) =>
  sql`SELECT id, name, license_no, vehicle_id FROM drivers WHERE id = ${id}`;

export const pendingPayouts = () =>
  sql`SELECT driver_id, amount_cents FROM payouts WHERE paid_at IS NULL`;
