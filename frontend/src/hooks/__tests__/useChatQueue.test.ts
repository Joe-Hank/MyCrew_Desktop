/**
 * 桩：useChatQueue 单飞队列 + 思考中指示。
 *
 * Why this spec exists
 * --------------------
 * useChatQueue is the single-flight engine behind every chat panel
 * (Plan Maker, Inception drawer, ...). The "single-flight" property is
 * load-bearing: without it, fast user typing produced overlapping
 * POSTs that ate each other's messages — the original bug fixed by
 * the queue rewrite.
 *
 * Invariants worth pinning here:
 *
 *   1. Enqueueing during an in-flight round MUST NOT start a second
 *      send(). The new content joins the next batch.
 *   2. `thinking` flips true exactly when send() is in flight and back
 *      to false on settle.
 *   3. stop() aborts the in-flight controller AND drops pending —
 *      already-displayed local bubbles stay.
 *   4. Multiple enqueued bubbles concatenate with "\n\n" into the next
 *      batch's prompt (the actual concatenation lives inside the
 *      consumer, but the queue's slice/clear protocol is what's tested).
 *
 * Suggested approach
 * ------------------
 * Render the hook via @testing-library/react's renderHook, pass a
 * controllable `send` (returning a Promise you resolve manually), and
 * assert call-count + state transitions.
 *
 * Stubs only — `it.todo(...)` makes them visible in `vitest --list`.
 */
import { describe, it } from "vitest";
// import { act, renderHook } from "@testing-library/react";
// import { useChatQueue } from "../useChatQueue";

describe("useChatQueue · single-flight", () => {
  it.todo("first enqueue triggers exactly one send()");
  it.todo("second enqueue while in-flight does NOT trigger a second send()");
  it.todo("after first round settles, queued content fires as the next send()");
  it.todo("two queued bubbles between rounds combine into one next-batch send()");
});

describe("useChatQueue · thinking indicator", () => {
  it.todo("thinking flips true while send() is unresolved");
  it.todo("thinking returns to false when queue drains");
  it.todo("thinking returns to false on send() rejection");
});

describe("useChatQueue · stop() semantics", () => {
  it.todo("stop() aborts the in-flight AbortController");
  it.todo("stop() drops pending entries but keeps already-emitted local bubbles");
  it.todo("stop() while idle is a no-op");
});

describe("useChatQueue · reconcile()", () => {
  it.todo("reconcile([id]) removes the matching local bubble");
  it.todo("reconcile([unknown]) is a no-op");
});

describe("useChatQueue · onSettle callback", () => {
  it.todo("onSettle fires exactly once per drain (not per round)");
  it.todo("onSettle fires after stop() too");
});
