/**
 * 桩：QueryErrorState 错误态 UI。
 *
 * Why this spec exists
 * --------------------
 * Every page that fetches via React Query falls through to this
 * component when the backend is down. The exact copy ("数据未丢失，
 * 仍在本地数据库中") is intentional reassurance and the only signal
 * users get during a sidecar crash. If it silently changes or the
 * retry button stops working, the perceived data-loss panic returns
 * (this was a real complaint pre-Phase 12).
 *
 * Behaviour to pin
 * ----------------
 *   1. Renders the `title` prop verbatim.
 *   2. Renders `error.message` when error is an Error, otherwise
 *      String(error). The branch matters for "thrown strings".
 *   3. "重试" button is enabled by default; turns into "重试中…" and
 *      disabled when `isFetching` is true.
 *   4. Clicking the button calls onRetry exactly once per click.
 *   5. Reassurance copy is always present (don't let i18n drift kill it).
 *
 * Stubs only — use React Testing Library + jest-dom matchers.
 */
import { describe, it } from "vitest";
// import { render, screen, fireEvent } from "@testing-library/react";
// import QueryErrorState from "../QueryErrorState";

describe("QueryErrorState · rendering", () => {
  it.todo("renders the title prop");
  it.todo("renders Error.message when error is an Error instance");
  it.todo("falls back to String(error) when error is a string");
  it.todo("falls back to String(error) when error is a plain object");
  it.todo("always renders the '数据未丢失' reassurance line");
});

describe("QueryErrorState · retry button", () => {
  it.todo("calls onRetry on click");
  it.todo("button label is '重试' when isFetching is false");
  it.todo("button label is '重试中…' when isFetching is true");
  it.todo("button is disabled while isFetching is true");
});
