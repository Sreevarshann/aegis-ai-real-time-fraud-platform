import { describe, expect, it } from "vitest";
import { fmtInt, fmtMoney, fmtPct, shortId, titleCase } from "./format";

describe("formatters", () => {
  it("formats numbers, money and percentages", () => {
    expect(fmtInt(1234567)).toBe("1,234,567");
    expect(fmtInt(null)).toBe("—");
    expect(fmtMoney("1234.5", "USD")).toBe("$1,234.50");
    expect(fmtMoney("1234.5", "JPY")).toBe("¥1,235");
    expect(fmtPct(0.12345, 2)).toBe("12.35%");
  });
  it("formats identifiers and labels", () => {
    expect(shortId("1df565e9-2cb1-491c")).toBe("1df565e9");
    expect(titleCase("card_testing_burst")).toBe("Card Testing Burst");
  });
});
