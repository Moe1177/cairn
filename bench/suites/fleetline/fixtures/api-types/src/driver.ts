export interface Driver {
  id: string;
  name: string;
  license_no: string;
  vehicle_id: string | null;
}

export type DriverApplication = Pick<Driver, "name" | "license_no">;
