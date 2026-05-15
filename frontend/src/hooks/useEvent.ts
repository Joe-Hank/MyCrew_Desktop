import { useEffect, useRef } from "react";
import { wsClient, type WsMessage } from "../net/ws";

/** Subscribe to a typed WS event for the lifetime of the calling component.
 *
 *  Design note: we register a STABLE wrapper that forwards to a ref'd
 *  handler. Two reasons:
 *    1. useCallback'd handlers change identity when their deps change —
 *       without the ref indirection, useEffect would re-run on every
 *       dep change, fragmenting the listener and burning a tiny bit of
 *       WS internals.
 *    2. Vite Fast Refresh sometimes fails to run cleanup when a module
 *       reloads. With a stable wrapper, even if a stale registration
 *       leaks, it only ever fires the CURRENT handler (via the ref),
 *       not 5 different historical versions. */
export function useEvent(eventType: string, handler: (msg: WsMessage) => void) {
  const handlerRef = useRef(handler);
  handlerRef.current = handler;

  useEffect(() => {
    const wrapper = (msg: WsMessage) => handlerRef.current(msg);
    return wsClient.on(eventType, wrapper);
  }, [eventType]);
}

/** Subscribe to ALL WS events for the lifetime of the calling component.
 *  See useEvent for the ref-stable-wrapper rationale. */
export function useAnyEvent(handler: (msg: WsMessage) => void) {
  const handlerRef = useRef(handler);
  handlerRef.current = handler;

  useEffect(() => {
    const wrapper = (msg: WsMessage) => handlerRef.current(msg);
    return wsClient.onAny(wrapper);
  }, []);
}
