import { useState, useEffect, useRef } from 'react';
import { DEFAULT_STATE } from '../types/NeoState';
import type { NeoState } from '../types/NeoState';

const WS_URL =
  location.hostname === 'localhost' || location.hostname === '127.0.0.1'
    ? 'ws://localhost:8765'
    : `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`;
const RECONNECT_BASE_MS = 1000;
const RECONNECT_MAX_MS = 10000;

interface SocketStatus {
  connected: boolean;
  lastUpdate: number | null;
}

export function useNeoSocket(): { state: NeoState; status: SocketStatus } {
  // Use a ref for the raw incoming data so WS messages don't trigger a render
  const latestRef = useRef<NeoState>(DEFAULT_STATE);
  // Render state — updated at ~10 Hz via interval
  const [state, setState] = useState<NeoState>(DEFAULT_STATE);
  const [status, setStatus] = useState<SocketStatus>({ connected: false, lastUpdate: null });

  const reconnectDelay = useRef(RECONNECT_BASE_MS);
  const wsRef = useRef<WebSocket | null>(null);
  const unmounted = useRef(false);

  useEffect(() => {
    unmounted.current = false;

    function connect() {
      if (unmounted.current) return;

      const ws = new WebSocket(WS_URL);
      wsRef.current = ws;

      ws.onopen = () => {
        reconnectDelay.current = RECONNECT_BASE_MS;
        setStatus({ connected: true, lastUpdate: Date.now() });
      };

      ws.onmessage = (evt) => {
        try {
          const parsed = JSON.parse(evt.data) as Partial<NeoState>;
          latestRef.current = { ...DEFAULT_STATE, ...parsed } as NeoState;
          setStatus(prev => ({ ...prev, lastUpdate: Date.now() }));
        } catch {
          // malformed frame — ignore
        }
      };

      ws.onclose = () => {
        setStatus({ connected: false, lastUpdate: null });
        if (!unmounted.current) {
          setTimeout(connect, reconnectDelay.current);
          reconnectDelay.current = Math.min(reconnectDelay.current * 1.5, RECONNECT_MAX_MS);
        }
      };

      ws.onerror = () => {
        ws.close();
      };
    }

    connect();

    // Flush latest data to React state at 10 Hz
    const ticker = setInterval(() => {
      setState({ ...latestRef.current });
    }, 100);

    return () => {
      unmounted.current = true;
      clearInterval(ticker);
      wsRef.current?.close();
    };
  }, []);

  return { state, status };
}
