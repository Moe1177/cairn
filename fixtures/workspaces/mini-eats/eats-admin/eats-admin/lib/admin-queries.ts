import { sql } from "drizzle-orm";

export const cooks = sql`SELECT * FROM cook_profiles ORDER BY id`;
export const live = sql`SELECT * FROM listings l JOIN cook_profiles c ON c.id = l.cook_id`;
export const admins = sql`SELECT * FROM users`;
