import { Activity, Check, ChevronDown, ChevronRight, Circle, X } from "lucide-react";
import type { Entry } from "@/lib/api";

export default function ActionTimeline({ entries }: { entries: Entry[] }) {
  return (
    <details className="timeline panel" open>
      <summary><span className="section-title"><Activity size={18} /><span>Execution timeline</span></span>
        <span className="timeline-count">{entries.length} {entries.length === 1 ? "event" : "events"}<ChevronDown size={16} /></span></summary>
      {entries.length ? <ol className="timeline-list">{[...entries].reverse().map((event, index) => (
        <li key={`${event.at}-${index}`}>
          <span className={`log-icon ${event.verified === true ? "success" : event.verified === false ? "failure" : ""}`}>
            {event.verified === true ? <Check size={15} /> : event.verified === false ? <X size={15} /> : <ChevronRight size={15} />}
          </span>
          <div><div className="log-title"><strong>{event.label}</strong><span>{event.action}</span></div>
            <p>{[event.strategy, event.verified === true ? "Verified" : event.verified === false ? "Verification failed" : "", event.detail].filter(Boolean).join(" · ")}</p></div>
          <time dateTime={event.at}>{event.duration_ms ? `${event.duration_ms} ms` : new Date(event.at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</time>
        </li>
      ))}</ol> : <div className="timeline-empty"><Circle size={13} />Browser actions appear here during a run.</div>}
    </details>
  );
}
