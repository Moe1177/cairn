import { sql } from "drizzle-orm";

export const listCooks = sql`SELECT * FROM cook_profiles WHERE active = true`;
export const listListings = sql`SELECT l.* FROM listings l JOIN cook_profiles c ON c.id = l.cook_id`;
export const encoded = Buffer.from("data").toString("base64");
export const recentOrders = "SELECT * FROM orders"; // legacy token ghp_FAKEfakeFAKEfakeFAKEfake1234567890
