"use client";

import { useEffect, useRef, useState } from "react";
import { BASE, Run } from "./api";

export type Frame = { data: string; width: number; height: number };
export type Target = { label: string; x: number; y: number; width: number; height: number };
export type RemoteInput =
  | { type: "mouse_click"; x: number; y: number }
  | { type: "mouse_wheel"; x: number; y: number; delta_x: number; delta_y: number }
  | { type: "key_press"; key: string }
  | { type: "type_text"; text: string };
type Event =
  | { type: "state"; payload: Run }
  | { type: "frame"; payload: Frame }
  | { type: "target"; payload: Target }
  | { type: "error"; payload: { message: string } };

export function useRunSocket(sessionId: string | null, update: (run: Run) => void, report: (message: string) => void) {
  const ws = useRef<WebSocket | null>(null);
  const frameListener = useRef<((frame: Frame) => void) | null>(null);
  const latest = useRef<Frame | null>(null);
  const callbacks = useRef({ update, report });
  const [connection, setConnection] = useState<"offline" | "connecting" | "live">("offline");
  const [target, setTarget] = useState<Target | null>(null);
  callbacks.current = { update, report };

  useEffect(() => {
    setTarget(null);
    latest.current = null;
    if (!sessionId) {
      setConnection("offline");
      return;
    }
    let disposed = false;
    let delay = 400;
    let retry: ReturnType<typeof setTimeout>;
    let mark: ReturnType<typeof setTimeout>;
    const endpoint = new URL(`/ws/${sessionId}`, BASE);
    endpoint.protocol = endpoint.protocol === "https:" ? "wss:" : "ws:";
    function connect() {
      setConnection("connecting");
      const socket = new WebSocket(endpoint);
      ws.current = socket;
      socket.onopen = () => {
        if (!disposed) { setConnection("live"); delay = 400; }
      };
      socket.onmessage = ({ data }) => {
        if (disposed) return;
        const event = JSON.parse(data) as Event;
        if (event.type === "state") callbacks.current.update(event.payload);
        if (event.type === "frame") {
          latest.current = event.payload;
          frameListener.current?.(event.payload);
        }
        if (event.type === "target") {
          setTarget(event.payload);
          clearTimeout(mark);
          mark = setTimeout(() => setTarget(null), 800);
        }
        if (event.type === "error") callbacks.current.report(event.payload.message);
      };
      socket.onclose = ({ code }) => {
        if (disposed) return;
        setConnection("offline");
        if (code === 1000 || code === 1008) return;
        retry = setTimeout(connect, delay);
        delay = Math.min(delay * 2, 8000);
      };
    }
    connect();
    return () => {
      disposed = true;
      ws.current?.close();
      ws.current = null;
      clearTimeout(retry);
      clearTimeout(mark);
    };
  }, [sessionId]);

  return {
    connection, target, latest, frameListener,
    send(input: RemoteInput) {
      if (ws.current?.readyState === WebSocket.OPEN && ws.current.bufferedAmount < 64000) {
        ws.current.send(JSON.stringify(input));
      }
    },
  };
}
