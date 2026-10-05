import type { Trip } from "@fleetline/api-types";

const BASE = process.env.NEXT_PUBLIC_GATEWAY_URL;

export async function getTrip(id: string): Promise<Trip> {
  return (await fetch(`${BASE}/trips/${id}`)).json();
}

export async function listTrips(): Promise<Trip[]> {
  return (await fetch(`${BASE}/trips`)).json();
}

export async function requestRide(form: FormData): Promise<void> {
  await fetch(`${BASE}/trips`, { method: "POST", body: form });
}
