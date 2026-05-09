import { useEffect } from "react";
import { wsClient, type WsMessage } from "../net/ws";

export function useEvent(eventType: string, handler: (msg: WsMessage) => void) {
  useEffect(() => {
    return wsClient.on(eventType, handler);
  }, [eventType, handler]);
}

export function useAnyEvent(handler: (msg: WsMessage) => void) {
  useEffect(() => {
    return wsClient.onAny(handler);
  }, [handler]);
}
