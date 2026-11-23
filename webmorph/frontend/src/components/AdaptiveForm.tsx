"use client";

import { CircleHelp, FileUp, LoaderCircle, Mic, Radio, ScanLine, Sparkles } from "lucide-react";
import { FormEvent, useRef, useState } from "react";
import { api, FieldSpec, Language, Value } from "@/lib/api";

interface Speech {
  lang: string;
  onresult: ((event: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null;
  onerror: (() => void) | null;
  onend: (() => void) | null;
  start(): void;
  abort(): void;
}
const speechLocales = { en: "en-US", hi: "hi-IN", kn: "kn-IN", es: "es-ES", fr: "fr-FR" };
const supportedInputs = new Set(["email", "tel", "url", "number", "date", "datetime-local", "month", "week", "time", "search", "color", "range"]);

export default function AdaptiveForm({ fields, sessionId, submitLabel, busy, plain, language, onSubmit }: {
  fields: FieldSpec[]; sessionId: string; submitLabel: string; busy: boolean;
  plain: boolean; language: Language; onSubmit: (values: Record<string, Value>) => void;
}) {
  const [values, setValues] = useState<Record<string, Value>>(() => Object.fromEntries(fields.filter((field) => {
    if (field.kind === "file" || field.confirm_explicitly) return false;
    return field.suggestion !== null || (field.current !== null && field.current !== "" && field.current !== false);
  }).map((field) => [field.key, field.suggestion ?? field.current])));
  const initial = useRef(values);
  const [editing, setEditing] = useState<Record<string, boolean>>({});
  const [names, setNames] = useState<Record<string, string>>({});
  const [open, setOpen] = useState<string | null>(null);
  const [original, setOriginal] = useState(false);
  const [uploading, setUploading] = useState<string | null>(null);
  const [listening, setListening] = useState<string | null>(null);
  const [error, setError] = useState("");
  const recognition = useRef<Speech | null>(null);
  const hasSpeech = typeof window !== "undefined" && (
    "SpeechRecognition" in window || "webkitSpeechRecognition" in window
  );

  function change(key: string, value: Value) {
    setValues((previous) => ({ ...previous, [key]: value }));
    setEditing((previous) => ({ ...previous, [key]: true }));
  }

  function speak(key: string) {
    if (recognition.current) {
      recognition.current.abort();
      return;
    }
    const speechWindow = window as Window & { SpeechRecognition?: new () => Speech; webkitSpeechRecognition?: new () => Speech };
    const Recognition = speechWindow.SpeechRecognition ?? speechWindow.webkitSpeechRecognition;
    if (!Recognition) return;
    const speech = new Recognition();
    recognition.current = speech;
    speech.lang = speechLocales[language];
    speech.onresult = (event) => change(key, event.results[0][0].transcript.trim());
    speech.onerror = () => setError("Dictation was interrupted. Check browser microphone access and try again.");
    speech.onend = () => { recognition.current = null; setListening(null); };
    try { setError(""); setListening(key); speech.start(); }
    catch { recognition.current = null; setListening(null); setError("Dictation could not start in this browser."); }
  }

  async function upload(field: FieldSpec, files: FileList | null) {
    if (!files?.length) return;
    setError("");
    setUploading(field.key);
    try {
      const uploaded: { token: string; name: string }[] = [];
      for (const file of Array.from(files)) uploaded.push(await api.file(sessionId, file));
      change(field.key, field.multiple ? uploaded.map((item) => item.token) : uploaded[0].token);
      setNames((previous) => ({ ...previous, [field.key]: uploaded.map((item) => item.name).join(", ") }));
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : "Upload failed.");
    } finally { setUploading(null); }
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    const merged = { ...initial.current, ...values };
    const fileMissing = fields.find((field) => field.kind === "file" && field.required && !merged[field.key] && !(Array.isArray(field.current) && field.current.length));
    if (fileMissing) { setError(`Upload a file for “${fileMissing.label}”.`); return; }
    for (const field of fields) {
      if (field.kind === "file" && !merged[field.key]) continue;
      if (!field.required && !editing[field.key] && field.suggestion === null) delete merged[field.key];
    }
    setError("");
    onSubmit(merged);
  }

  return (
    <form onSubmit={submit} className="adaptive-form">
      {fields.length > 0 && <div className="form-tools"><span>{fields.filter((field) => field.required).length} required</span>
        {plain && <label><input type="checkbox" checked={original} onChange={(event) => setOriginal(event.target.checked)} /> Show original labels</label>}
      </div>}
      <div className="field-grid">
        {fields.map((field) => {
          const value = values[field.key];
          const text = typeof value === "string" ? value : "";
          const id = `field-${field.key}`;
          const label = !plain || original || (field.kind === "checkbox" && field.required) ? field.original : field.label;
          const long = ["checkbox", "file", "textarea", "radio"].includes(field.kind);
          const select = field.kind === "select" || (field.kind === "combobox" && field.options.length > 0);
          const inputType = supportedInputs.has(field.kind) ? field.kind : "text";
          const errorId = field.error ? `${id}-error` : undefined;
          return (
            <div key={field.key} className={`field ${long ? "field-wide" : ""}`}>
              <div className="field-heading">
                <label htmlFor={id}>{label}{field.required && <span className="required"> *</span>}</label>
                <button type="button" className="help-icon" title="Explain this field" aria-label={`Explain ${label}`} aria-expanded={open === field.key} onClick={() => setOpen((previous) => previous === field.key ? null : field.key)}><CircleHelp size={15} /></button>
              </div>
              {open === field.key && <p className="field-help">{field.hint}{field.original !== label && <small>Site label · {field.original}</small>}</p>}
              {field.kind === "checkbox" ? (
                <label className="choice" htmlFor={id}><input id={id} type="checkbox" checked={value === true} required={field.required} aria-describedby={errorId} onChange={(event) => change(field.key, event.target.checked)} />{field.required ? "I confirm" : "Yes"}</label>
              ) : field.kind === "radio" ? (
                <div role="radiogroup" aria-label={label} className="choices">{field.options.map((option, index) => <label key={option.value} className="choice"><input id={index === 0 ? id : undefined} type="radio" name={field.key} value={option.value} checked={text === option.value} required={field.required} onChange={() => change(field.key, option.value)} />{option.label}</label>)}</div>
              ) : field.kind === "file" ? (
                <div className="file-upload">
                  <input id={id} className="sr-only" type="file" accept={field.accept || undefined} multiple={field.multiple} onChange={(event) => void upload(field, event.target.files)} />
                  <label htmlFor={id} className="button"><FileUp size={16} />{uploading === field.key ? "Uploading…" : "Choose file"}</label>
                  <span>{names[field.key] || (Array.isArray(field.current) ? field.current.join(", ") : "") || field.accept || "Up to 10 MB"}</span>
                </div>
              ) : select ? (
                <select className="control" id={id} value={field.multiple ? Array.isArray(value) ? value : [] : text}
                  onChange={(event) => change(field.key, field.multiple ? Array.from(event.target.selectedOptions, (option) => option.value) : event.target.value)}
                  multiple={field.multiple} required={field.required} aria-describedby={errorId}>
                  {!field.multiple && <option value="">Choose an option</option>}
                  {field.options.map((option, index) => <option key={`${option.value}-${index}`} value={option.value}>{option.label}</option>)}
                </select>
              ) : (
                <div className="dictation">
                  {field.kind === "textarea" ? <textarea className="control" id={id} value={text} onChange={(event) => change(field.key, event.target.value)} required={field.required} maxLength={field.max_length ?? undefined} aria-describedby={errorId} /> :
                    <input className="control" id={id} type={inputType} value={text} required={field.required}
                      min={field.minimum || undefined} max={field.maximum || undefined} step={field.step || undefined}
                      maxLength={field.max_length ?? undefined} pattern={field.pattern || undefined} aria-describedby={errorId}
                      onChange={(event) => change(field.key, event.target.value)} />}
                  {hasSpeech && ["text", "email", "tel", "url", "textarea"].includes(inputType) && <button className={`mic ${listening === field.key ? "listening" : ""}`} type="button" title="Dictate answer" aria-label={`Dictate ${label}`} onClick={() => speak(field.key)}>{listening === field.key ? <Radio size={16} /> : <Mic size={16} />}</button>}
                </div>
              )}
              {!editing[field.key] && field.source && <span className="vault-badge" title={field.confidence ? `${Math.round(field.confidence * 100)}% match confidence` : undefined}><Sparkles size={13} />{field.source === "vault" ? "Auto-filled from Vault" : "From an earlier answer"}{field.confidence ? ` · ${Math.round(field.confidence * 100)}%` : ""}</span>}
              {field.error && !editing[field.key] && <p className="inline-error" id={errorId}>{field.error}</p>}
            </div>
          );
        })}
      </div>
      {error && <p role="alert" className="inline-error">{error}</p>}
      <button type="submit" className="button primary form-submit" disabled={busy || Boolean(uploading)}>{busy ? <LoaderCircle size={17} className="spin" /> : <ScanLine size={17} />}{submitLabel}</button>
    </form>
  );
}
