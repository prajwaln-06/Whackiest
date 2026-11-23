"use client";

import { FileUp, FolderLock, LoaderCircle, Plus, Save, Sparkles, Trash2, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";

const SAMPLE = {
  full_name: "Avery Morgan", email: "avery.morgan@example.com", phone: "+91 90000 12345",
  date_of_birth: "1994-08-21", country: "India",
};

export default function VaultDrawer({ onClose }: { onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const counter = useRef(0);
  const [rows, setRows] = useState<{ id: number; key: string; value: string }[]>([]);
  const [busy, setBusy] = useState(true);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const toRows = (facts: Record<string, string>) => Object.entries(facts).map(([key, value]) => ({ id: counter.current++, key, value }));

  useEffect(() => {
    dialog.current?.showModal();
    let alive = true;
    api.vault().then(({ facts }) => { if (alive) setRows(toRows(facts)); })
      .catch((problem: Error) => { if (alive) setError(problem.message); })
      .finally(() => { if (alive) setBusy(false); });
    return () => { alive = false; };
  }, []);

  const facts = () => Object.fromEntries(rows.filter((row) => row.key.trim() && row.value.trim()).map((row) => [row.key.trim(), row.value.trim()]));

  async function save(nextFacts: Record<string, string>, notice = "Vault saved.") {
    setBusy(true); setMessage(""); setError("");
    try { setRows(toRows((await api.saveVault(nextFacts)).facts)); setMessage(notice); }
    catch (problem) { setError((problem as Error).message); }
    finally { setBusy(false); }
  }

  async function extract(file?: File) {
    if (!file) return;
    setBusy(true); setMessage(""); setError("");
    try {
      const result = await api.document(file);
      setRows(toRows({ ...facts(), ...result.facts }));
      const count = Object.keys(result.facts).length;
      setMessage([count ? `${count} facts extracted. Review and save when ready.` : "No profile facts were extracted.", result.notice].filter(Boolean).join(" "));
    } catch (problem) { setError((problem as Error).message); }
    finally { setBusy(false); }
  }

  return (
    <dialog className="drawer" ref={dialog} onCancel={(event) => { event.preventDefault(); onClose(); }} aria-labelledby="vault-title">
      <div className="drawer-header"><div className="section-title"><FolderLock size={21} /><h2 id="vault-title">My Vault</h2></div><button className="button button-icon" type="button" aria-label="Close Vault" onClick={onClose}><X size={19} /></button></div>
      <div className="drawer-body">
        <p className="muted">Save reusable profile facts on this device. WebMorph suggests matches when a website asks for them.</p>
        <div className="button-row">
          <button className="button" type="button" disabled={busy} onClick={() => void save({ ...facts(), ...SAMPLE }, "Sample persona saved.")}><Sparkles size={16} />Load sample persona</button>
          <label className="button vault-upload"><FileUp size={16} />Extract PDF or TXT<input aria-label="Extract facts from PDF or TXT" type="file" accept=".pdf,.txt" disabled={busy} onChange={(event) => { void extract(event.target.files?.[0]); event.currentTarget.value = ""; }} /></label>
        </div>
        <p className="vault-note">Document text goes to your configured LLM provider for extraction when a provider is enabled.</p>
        <form onSubmit={(event) => { event.preventDefault(); void save(facts()); }}>
          <div className="vault-rows">
            {rows.map((row, index) => <div className="vault-row" key={row.id}>
              <input className="control" aria-label={`Fact name ${index + 1}`} value={row.key} maxLength={100} placeholder="Field name" onChange={(event) => setRows((previous) => previous.map((item) => item.id === row.id ? { ...item, key: event.target.value } : item))} />
              <input className="control" aria-label={`Fact value ${index + 1}`} value={row.value} maxLength={5000} placeholder="Saved value" onChange={(event) => setRows((previous) => previous.map((item) => item.id === row.id ? { ...item, value: event.target.value } : item))} />
              <button className="button button-icon" type="button" aria-label={`Remove ${row.key || "fact"}`} onClick={() => setRows((previous) => previous.filter((item) => item.id !== row.id))}><Trash2 size={16} /></button>
            </div>)}
          </div>
          <div className="button-row">
            <button className="button" type="button" disabled={busy} onClick={() => setRows((previous) => [...previous, { id: counter.current++, key: "", value: "" }])}><Plus size={16} />Add fact</button>
            <button className="button primary" type="submit" disabled={busy}>{busy ? <LoaderCircle size={16} className="spin" /> : <Save size={16} />}Save vault</button>
          </div>
        </form>
        {message && <p role="status" className="success-message">{message}</p>}
        {error && <p role="alert" className="inline-error">{error}</p>}
      </div>
    </dialog>
  );
}
