import { useEffect, useRef, useState, useCallback } from "react";
import type { LedgerEvent } from "../api/types";

interface UseWebSocketOptions {
  maxEvents?: number;
  autoConnect?: boolean;
}

export function useWebSocket(opts: UseWebSocketOptions = {}) {
  const { maxEvents = 500, autoConnect = true } = opts;
  const [events, setEvents] = useState<LedgerEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout>>();

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(`${protocol}//${window.location.host}/api/ws/pipeline`);

    ws.onopen = () => setConnected(true);

    ws.onmessage = (e) => {
      try {
        const event: LedgerEvent = JSON.parse(e.data);
        setEvents((prev) => {
          const next = [...prev, event];
          return next.length > maxEvents ? next.slice(-maxEvents) : next;
        });
      } catch {
        // Ignore malformed messages
      }
    };

    ws.onclose = () => {
      setConnected(false);
      // Reconnect after 3 seconds
      reconnectTimer.current = setTimeout(connect, 3000);
    };

    ws.onerror = () => ws.close();

    wsRef.current = ws;
  }, [maxEvents]);

  const disconnect = useCallback(() => {
    clearTimeout(reconnectTimer.current);
    wsRef.current?.close();
    wsRef.current = null;
  }, []);

  const clearEvents = useCallback(() => setEvents([]), []);

  useEffect(() => {
    if (autoConnect) connect();
    return disconnect;
  }, [autoConnect, connect, disconnect]);

  return { events, connected, connect, disconnect, clearEvents };
}
