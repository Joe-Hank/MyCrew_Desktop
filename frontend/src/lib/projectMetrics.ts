// Pure formatters for the home-card "项目统计小插件" badges.
//
// Backend stores three accumulated counters on each project:
//   total_input_tokens, total_output_tokens — integer token counts
//   total_cost_cents                         — integer cents (1/100 ¥)
//   total_runtime_seconds                    — whole seconds, pause/stop excluded
//
// The card UI distils those into two compact badges:
//
//     ¥0.32 · 12.5k tok            <- formatTokensAndCost()
//     1h 23m       (or 12:34:56)   <- formatRuntime()
//
// Rules baked in:
//   • Token count uses k / M abbreviations once it crosses 1_000 / 1_000_000.
//   • Cost shows "¥0.00" through "¥9999.99" with two decimals; falls back to
//     plain integer ¥ once it crosses ¥10_000 so the badge stays narrow.
//   • Runtime under 1h: shows mm:ss (e.g. "07:42").
//     1h – 99h:        shows Xh Ym  (e.g. "3h 07m").
//     ≥100h:           shows Xh    (e.g. "120h").
//   • A counter of exactly 0 returns the empty string so the card can render
//     `text && <Badge>` and skip the badge entirely.

export function formatTokens(tokens: number): string {
  const n = Math.max(0, Math.floor(tokens || 0));
  if (n === 0) return "";
  if (n < 1_000) return `${n} tok`;
  if (n < 1_000_000) {
    // One decimal when it visibly differs from the integer (e.g. 12.5k),
    // otherwise drop the trailing ".0" for a cleaner look (e.g. 3k).
    const v = n / 1_000;
    return `${v.toFixed(v < 10 ? 1 : 0).replace(/\.0$/, "")}k tok`;
  }
  const v = n / 1_000_000;
  return `${v.toFixed(v < 10 ? 2 : 1).replace(/\.?0+$/, "")}M tok`;
}

export function formatCostCny(cents: number): string {
  const n = Math.max(0, Math.floor(cents || 0));
  if (n === 0) return "";
  const yuan = n / 100;
  if (yuan < 10_000) return `¥${yuan.toFixed(2)}`;
  // For huge spends we trade precision for compactness — a card badge is
  // ~80px wide and "¥12345.67" doesn't fit alongside the token suffix.
  return `¥${Math.round(yuan).toLocaleString("en-US")}`;
}

export function formatTokensAndCost(
  inputTokens: number,
  outputTokens: number,
  costCents: number,
): string {
  const total = (inputTokens || 0) + (outputTokens || 0);
  const tokStr = formatTokens(total);
  const costStr = formatCostCny(costCents);
  if (!tokStr && !costStr) return "";
  if (tokStr && costStr) return `${costStr} · ${tokStr}`;
  return tokStr || costStr;
}

export function formatRuntime(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds || 0));
  if (total === 0) return "";
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h === 0) {
    // Under an hour: mm:ss, zero-padded on both halves (matches the
    // "stopwatch" feel users asked for — "02:47:31 or 1h 23m").
    return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  }
  if (h < 100) {
    return `${h}h ${String(m).padStart(2, "0")}m`;
  }
  // Hundred-hour-plus projects compress down to whole hours so the badge
  // still fits next to the favorite button.
  return `${h}h`;
}
