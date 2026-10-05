import { expect, test } from "vitest";
import { Button } from "./Button";

test("defaults to primary", () => expect(Button({}).props["data-variant"]).toBe("primary"));
