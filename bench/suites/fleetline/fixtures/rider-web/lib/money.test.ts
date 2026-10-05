import { expect, test } from "vitest";
import { formatCents } from "./money";

test("formats cents", () => expect(formatCents(1234)).toBe("$12.34"));
