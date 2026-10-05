import type { DriverApplication } from "@fleetline/api-types";

const BASE = process.env.NEXT_PUBLIC_GATEWAY_URL;

export async function submitApplication(app: DriverApplication): Promise<void> {
  await fetch(`${BASE}/drivers/applications`, { method: "POST", body: JSON.stringify(app) });
}

export async function getEarnings(): Promise<{ week: string; total: string }[]> {
  return (await fetch(`${BASE}/payouts/me`)).json();
}
