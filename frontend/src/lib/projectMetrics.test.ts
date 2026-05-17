import { describe, it, expect } from "vitest";
import {
  formatTokens,
  formatCostCny,
  formatTokensAndCost,
  formatRuntime,
} from "./projectMetrics";

// These helpers feed the home-card badges. Bugs here cost the user
// trust ("why does my hobby project show ¥0.00 · 0 tok?") so the suite
// pins down each visible state — zero/hide, sub-thousand, k, M.

describe("formatTokens", () => {
  it("returns empty string for zero (hides the badge)", () => {
    expect(formatTokens(0)).toBe("");
  });

  it("formats sub-1k counts as plain integers", () => {
    expect(formatTokens(42)).toBe("42 tok");
    expect(formatTokens(999)).toBe("999 tok");
  });

  it("uses k with one decimal under 10k, none above", () => {
    expect(formatTokens(1_000)).toBe("1k tok");      // .0 stripped
    expect(formatTokens(1_500)).toBe("1.5k tok");
    expect(formatTokens(12_500)).toBe("13k tok");    // ≥10 → integer
    expect(formatTokens(999_999)).toBe("1000k tok"); // boundary
  });

  it("uses M with adaptive precision past 1M", () => {
    expect(formatTokens(1_000_000)).toBe("1M tok");
    expect(formatTokens(1_500_000)).toBe("1.5M tok");
    expect(formatTokens(12_300_000)).toBe("12.3M tok");
  });

  it("clamps negative input to zero (hidden badge)", () => {
    expect(formatTokens(-50)).toBe("");
  });
});

describe("formatCostCny", () => {
  it("hides zero", () => {
    expect(formatCostCny(0)).toBe("");
  });

  it("renders cents → 元 with two decimals under ¥10000", () => {
    expect(formatCostCny(1)).toBe("¥0.01");
    expect(formatCostCny(32)).toBe("¥0.32");
    expect(formatCostCny(12_345)).toBe("¥123.45");
  });

  it("switches to integer ¥ above ¥10000 to keep the badge compact", () => {
    expect(formatCostCny(1_000_000)).toBe("¥10,000");
    expect(formatCostCny(1_234_567)).toBe("¥12,346");
  });
});

describe("formatTokensAndCost", () => {
  it("joins both halves with a middle dot when both present", () => {
    expect(formatTokensAndCost(8_000, 4_500, 32)).toBe("¥0.32 · 12.5k tok");
  });

  it("shows only one half when the other is zero", () => {
    expect(formatTokensAndCost(0, 0, 32)).toBe("¥0.32");
    expect(formatTokensAndCost(8_000, 4_500, 0)).toBe("12.5k tok");
  });

  it("returns empty string when both halves are zero (hide entirely)", () => {
    expect(formatTokensAndCost(0, 0, 0)).toBe("");
  });
});

describe("formatRuntime", () => {
  it("hides zero", () => {
    expect(formatRuntime(0)).toBe("");
  });

  it("formats sub-hour intervals as mm:ss with zero-padding", () => {
    expect(formatRuntime(7)).toBe("00:07");
    expect(formatRuntime(60)).toBe("01:00");
    expect(formatRuntime(7 * 60 + 42)).toBe("07:42");
    expect(formatRuntime(59 * 60 + 59)).toBe("59:59");
  });

  it("formats sub-100h as 'Xh YYm' with the minutes zero-padded", () => {
    expect(formatRuntime(3600)).toBe("1h 00m");
    expect(formatRuntime(3 * 3600 + 7 * 60)).toBe("3h 07m");
    expect(formatRuntime(99 * 3600 + 59 * 60 + 59)).toBe("99h 59m");
  });

  it("collapses to whole hours past 100h to keep the badge narrow", () => {
    expect(formatRuntime(100 * 3600)).toBe("100h");
    expect(formatRuntime(120 * 3600 + 30 * 60)).toBe("120h");
  });

  it("ignores fractional seconds (we accumulate integers server-side)", () => {
    expect(formatRuntime(7.9)).toBe("00:07");
  });
});
