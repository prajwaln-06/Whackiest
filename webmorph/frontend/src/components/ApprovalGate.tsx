"use client";

import { ExternalLink, Hand, LockKeyhole, ShieldAlert } from "lucide-react";
import { Approval, formatValue } from "@/lib/api";

export default function ApprovalGate({ approval, busy, onApprove, onTakeover }: {
  approval: Approval; busy: boolean; onApprove: () => void; onTakeover: () => void;
}) {
  const screenshot = `data:image/jpeg;base64,${approval.screenshot}`;
  return (
    <section className="subcard approval-card" aria-labelledby="approval-title">
      <div className="subcard-heading"><div className="tile-icon amber"><ShieldAlert size={20} /></div>
        <div><h3 id="approval-title">Review before continuing</h3><p>The next action is <strong>{approval.button}</strong>.</p></div>
      </div>
      <details className="approval-preview">
        <summary>Website screenshot <ExternalLink size={14} /></summary>
        {/* The preview is provided by this run's local Chromium session. */}
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={screenshot} alt="Browser screenshot captured before the pending action" />
      </details>
      <div className="approval-diff">
        <h4>Field audit</h4>
        {approval.changes.length ? <div className="diff-scroll"><table><thead><tr><th>Field</th><th>Before</th><th>Current</th></tr></thead>
          <tbody>{approval.changes.map((change) => <tr key={change.key}><td>{change.label}{change.step && <small>{change.step}</small>}</td>
            <td>{formatValue(change.before)}</td><td>{formatValue(change.after)}</td></tr>)}</tbody></table></div> : <p>No form values have been recorded for this run.</p>}
      </div>
      <div className="button-row">
        <button className="button amber-button" type="button" disabled={busy} onClick={onApprove}><LockKeyhole size={16} />Approve this action</button>
        <button className="button" type="button" disabled={busy} onClick={onTakeover}><Hand size={16} />Take manual control</button>
      </div>
    </section>
  );
}
