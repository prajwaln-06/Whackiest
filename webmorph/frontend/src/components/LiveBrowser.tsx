"use client";

import { AppWindow, Globe2, Hand, LockKeyhole, MousePointer2, Radio, RotateCcw, Sparkles, X } from "lucide-react";
import { ClipboardEvent, KeyboardEvent, MouseEvent, MutableRefObject, useEffect, useRef, useState } from "react";
import { Run, STATUS } from "@/lib/api";
import { Frame, RemoteInput, Target } from "@/lib/ws";

const KEYS: Record<string, string> = { " ": "Space", Escape: "Escape", Delete: "Delete", Backspace: "Backspace",
  Enter: "Enter", Tab: "Tab", ArrowLeft: "ArrowLeft", ArrowRight: "ArrowRight", ArrowUp: "ArrowUp",
  ArrowDown: "ArrowDown", Home: "Home", End: "End", PageDown: "PageDown", PageUp: "PageUp", Insert: "Insert" };

export default function LiveBrowser({ run, connection, target, latest, frameListener, send, busy, onTakeover, onResume, onClose }: {
  run: Run | null; connection: string; target: Target | null; latest: MutableRefObject<Frame | null>;
  frameListener: MutableRefObject<((frame: Frame) => void) | null>; send: (input: RemoteInput) => void;
  busy: boolean; onTakeover: () => void; onResume: () => void; onClose: () => void;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const manual = run?.status === "HUMAN_TAKEOVER";
  const [hasFrame, setHasFrame] = useState(false);
  const [typed, setTyped] = useState("");
  const active = run && run.status !== "COMPLETED" && run.status !== "FAILED";

  useEffect(() => {
    setHasFrame(false);
    let alive = true;
    let decoding = false;
    let pending: Frame | null = null;
    function draw(frame: Frame) {
      if (!alive) return;
      if (decoding) { pending = frame; return; }
      decoding = true;
      const picture = new Image();
      function done() {
        decoding = false;
        const next = pending;
        pending = null;
        if (next) draw(next);
      }
      picture.onload = () => {
        const node = canvas.current;
        if (alive && node) {
          const ctx = node.getContext("2d", { alpha: false });
          ctx?.drawImage(picture, 0, 0, node.width, node.height);
          setHasFrame(true);
        }
        done();
      };
      picture.onerror = done;
      picture.src = `data:image/jpeg;base64,${frame.data}`;
    }
    frameListener.current = draw;
    if (latest.current) draw(latest.current);
    return () => {
      alive = false;
      if (frameListener.current === draw) frameListener.current = null;
      const node = canvas.current;
      if (node) node.getContext("2d")?.clearRect(0, 0, node.width, node.height);
    };
  }, [run?.session_id, frameListener, latest]);

  useEffect(() => {
    const node = canvas.current;
    if (!manual || !node) return;
    function onWheel(event: WheelEvent) {
      if (!node || connection !== "live") return;
      event.preventDefault();
      const { x, y } = point(node, event.clientX, event.clientY);
      const factor = event.deltaMode === 1 ? 18 : event.deltaMode === 2 ? 500 : 1;
      const clamp = (value: number) => Math.max(-2500, Math.min(2500, value * factor));
      send({ type: "mouse_wheel", x, y, delta_x: clamp(event.deltaX), delta_y: clamp(event.deltaY) });
    }
    node.addEventListener("wheel", onWheel, { passive: false });
    return () => node.removeEventListener("wheel", onWheel);
  }, [manual, connection, send]);

  function point(node: HTMLCanvasElement, clientX: number, clientY: number) {
    const rect = node.getBoundingClientRect();
    return { x: Math.min(1279, Math.max(0, (clientX - rect.left) * 1280 / rect.width)),
      y: Math.min(799, Math.max(0, (clientY - rect.top) * 800 / rect.height)) };
  }

  function click(event: MouseEvent<HTMLCanvasElement>) {
    if (!manual || connection !== "live") return;
    event.currentTarget.focus();
    send({ type: "mouse_click", ...point(event.currentTarget, event.clientX, event.clientY) });
  }

  function key(event: KeyboardEvent<HTMLCanvasElement>) {
    if (!manual || connection !== "live") return;
    if (event.key === "Tab" && event.shiftKey && event.ctrlKey) return;
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "v") return;
    if (event.altKey && event.key === "Escape") { event.preventDefault(); event.currentTarget.blur(); return; }
    if (!event.altKey && !event.ctrlKey && !event.metaKey && /^[a-z0-9]$/i.test(event.key)) {
      event.preventDefault();
      const key = event.shiftKey ? "Shift+" + event.code : event.key;
      send({ type: "key_press", key });
    } else if (!event.altKey && !event.ctrlKey && !event.metaKey && event.key.length === 1) {
      event.preventDefault();
      send({ type: "type_text", text: event.key });
    } else if (KEYS[event.key] || event.key.length === 1 && (event.ctrlKey || event.metaKey || event.altKey)) {
      event.preventDefault();
      const keys = [event.ctrlKey && "Control", event.metaKey && "Meta", event.altKey && "Alt",
        event.shiftKey && "Shift", KEYS[event.key] || (event.key === "+" ? "Equal" : event.key)].filter(Boolean);
      send({ type: "key_press", key: keys.join("+") });
    }
  }

  function paste(event: ClipboardEvent<HTMLCanvasElement>) {
    if (!manual || connection !== "live") return;
    event.preventDefault();
    const text = event.clipboardData.getData("text/plain");
    if (text) send({ type: "type_text", text: text.slice(0, 3000) });
  }

  return (
    <section className="browser panel" aria-labelledby="browser-title">
      <div className="pane-heading">
        <div className="section-title"><AppWindow size={19} /><h2 id="browser-title">Live browser</h2></div>
        <div className="browser-actions">
          {active && <button className="button compact" type="button" disabled={busy}
            onClick={manual ? onResume : onTakeover}>{manual ? <RotateCcw size={15} /> : <Hand size={15} />}{manual ? "Hand back to agent" : "Take control"}</button>}
          {run && <button className="button button-icon compact" type="button" title="Close session" aria-label="Close session" disabled={busy} onClick={onClose}><X size={16} /></button>}
        </div>
      </div>
      <div className="browser-chrome">
        <span className="browser-dots" aria-hidden="true"><i /><i /><i /></span>
        <div className="browser-address" title={run?.url || "No active website"}><LockKeyhole size={13} /><span>{run?.url || "about:blank"}</span></div>
        <span className={`stream-indicator ${connection === "live" ? "stream-up" : ""}`} title={connection}><Radio size={15} /></span>
      </div>
      <div className={`viewport ${manual ? "manual" : ""}`}>
        <canvas ref={canvas} width={1280} height={800} className={hasFrame ? "frame-visible" : ""} tabIndex={manual ? 0 : -1}
          aria-label={manual ? "Remote browser. Click to focus. Press Alt Escape to leave the canvas." : "Live website stream"}
          onClick={click} onKeyDown={key} onPaste={paste} />
        {!hasFrame && <div className="viewport-empty"><div className="viewport-orbit"><Globe2 size={33} strokeWidth={1.45} /></div>
          <strong>{run ? run.status === "FAILED" ? "Browser unavailable" : "Opening the browser" : "No website open"}</strong><p>{run ? "Waiting for a browser frame." : "Scout a website to see it here."}</p></div>}
        {target && !manual && hasFrame && <div className="target-box" style={{ left: `${target.x / 12.8}%`, top: `${target.y / 8}%`, width: `${target.width / 12.8}%`, height: `${target.height / 8}%` }}>
          <span><MousePointer2 size={13} />{target.label}</span>
        </div>}
      </div>
      <div className="viewport-footer">
        <span className={`status-badge ${run?.status.toLowerCase() || "idle"}`}><i />{run ? STATUS[run.status] : "Standby"}</span>
        <span>{run?.schema.step || (run ? connection === "live" ? "Live stream" : "Reconnecting stream" : "1280 × 800")}</span>
      </div>
      {manual && <form className="remote-text" onSubmit={(event) => { event.preventDefault(); if (typed) { send({ type: "type_text", text: typed }); setTyped(""); } }}>
        <Sparkles size={15} /><input type="text" value={typed} onChange={(event) => setTyped(event.target.value)} maxLength={3000} aria-label="Text to type in the focused website field" placeholder="Send text to the focused website field" />
        <button className="button compact" disabled={!typed || connection !== "live"}>Send text</button>
      </form>}
    </section>
  );
}
