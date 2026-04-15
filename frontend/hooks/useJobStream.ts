"use client";

import { useEffect, useRef, useState } from "react";
import { getScanStreamUrl, Scan } from "@/lib/api";

export type StreamEvent =
  | { type: "stage_update"; stage: string; timestamp: string }
  | { type: "status_update"; status: string }
  | { type: "completed"; scan: Scan }
  | { type: "failed"; scan: Scan }
  | { type: "error"; message: string };

interface UseJobStreamResult {
  scan: Scan | null;
  events: StreamEvent[];
  connected: boolean;
  done: boolean;
}

export function useJobStream(scanId: string, initialScan: Scan | null = null): UseJobStreamResult {
  const [scan, setScan] = useState<Scan | null>(initialScan);
  const [events, setEvents] = useState<StreamEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const [done, setDone] = useState(false);
  const esRef = useRef<EventSource | null>(null);
  const reconnectTimeout = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (done) return;

    function connect() {
      const es = new EventSource(getScanStreamUrl(scanId));
      esRef.current = es;
      setConnected(false);

      es.onopen = () => setConnected(true);

      es.addEventListener("stage_update", (e: MessageEvent) => {
        const data = JSON.parse(e.data);
        setEvents((prev) => [...prev, { type: "stage_update", ...data }]);
        // Merge timeline update into local scan state
        setScan((prev) =>
          prev ? { ...prev, timeline: { ...prev.timeline, [data.stage]: data.timestamp } } : prev
        );
      });

      es.addEventListener("status_update", (e: MessageEvent) => {
        const data = JSON.parse(e.data);
        setEvents((prev) => [...prev, { type: "status_update", ...data }]);
        setScan((prev) => (prev ? { ...prev, status: data.status } : prev));
      });

      es.addEventListener("completed", (e: MessageEvent) => {
        const fullScan: Scan = JSON.parse(e.data);
        setScan(fullScan);
        setEvents((prev) => [...prev, { type: "completed", scan: fullScan }]);
        setDone(true);
        es.close();
      });

      es.addEventListener("failed", (e: MessageEvent) => {
        const fullScan: Scan = JSON.parse(e.data);
        setScan(fullScan);
        setEvents((prev) => [...prev, { type: "failed", scan: fullScan }]);
        setDone(true);
        es.close();
      });

      es.onerror = () => {
        setConnected(false);
        es.close();
        if (!done) {
          // Reconnect after 3 seconds
          reconnectTimeout.current = setTimeout(connect, 3000);
        }
      };
    }

    connect();

    return () => {
      esRef.current?.close();
      if (reconnectTimeout.current) clearTimeout(reconnectTimeout.current);
    };
  }, [scanId, done]);

  return { scan, events, connected, done };
}
