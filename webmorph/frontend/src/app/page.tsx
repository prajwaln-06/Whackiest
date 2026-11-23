"use client";

import { CircleAlert, CircleCheck, ClipboardList, Download, Hand, History as HistoryIcon, Layers3, LoaderCircle, Radar, ScanLine, ShieldCheck, Workflow, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import ActionTimeline from "@/components/ActionTimeline";
import AdaptiveForm from "@/components/AdaptiveForm";
import ApprovalGate from "@/components/ApprovalGate";
import LiveBrowser from "@/components/LiveBrowser";
import MidFlightModal from "@/components/MidFlightModal";
import PreFlightBrief from "@/components/PreFlightBrief";
import TopBar, { Theme } from "@/components/TopBar";
import VaultDrawer from "@/components/VaultDrawer";
import { api, downloadAudit, History, Language, Run, STATUS, Value } from "@/lib/api";
import { useRunSocket } from "@/lib/ws";

const DEMO_URL = "http://localhost:8001";
const DEMO_GOAL = "Complete the National Innovation & Travel Permit application";

function HistoryDrawer({ close }: { close: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [history, setHistory] = useState<History[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    dialog.current?.showModal();
    let alive = true;
    api.history().then((data) => { if (alive) setHistory(data); }).catch((problem: Error) => { if (alive) setError(problem.message); });
    return () => { alive = false; };
  }, []);
  return <dialog className="drawer" ref={dialog} onCancel={(event) => { event.preventDefault(); close(); }} aria-labelledby="history-title">
    <div className="drawer-header"><div className="section-title"><HistoryIcon size={21} /><h2 id="history-title">Run history</h2></div><button className="button button-icon" aria-label="Close run history" onClick={close}><X size={19} /></button></div>
    <div className="drawer-body">
      {error && <p role="alert" className="inline-error">{error}</p>}
      {!history && !error && <LoaderCircle size={22} className="spin" aria-label="Loading history" />}
      {history?.length === 0 && <p className="muted">Completed and interrupted runs will appear here.</p>}
      <ul className="history-list">{history?.map((item) => <li key={item.session_id}>
        <div><strong>{item.goal}</strong><small>{STATUS[item.status]} · {new Date(item.updated).toLocaleString()}</small><small>{item.url}</small></div>
        <button type="button" className="button button-icon" aria-label={`Download audit for ${item.goal}`} onClick={() => void downloadAudit(item.session_id).catch((problem: Error) => setError(problem.message))}><Download size={17} /></button>
      </li>)}</ul>
    </div>
  </dialog>;
}

export default function Home() {
  const [url, setUrl] = useState("");
  const [goal, setGoal] = useState("");
  const [language, setLanguage] = useState<Language>("en");
  const [theme, setTheme] = useState<Theme>("dark");
  const [plain, setPlain] = useState(true);
  const [ready, setReady] = useState(false);
  const [online, setOnline] = useState(false);
  const [run, setRun] = useState<Run | null>(null);
  const [busy, setBusy] = useState(false);
  const [launching, setLaunching] = useState(false);
  const [error, setError] = useState("");
  const [drawer, setDrawer] = useState<"vault" | "history" | null>(null);
  const activeId = useRef<string | null>(null);
  const busyRef = useRef(false);
  const apply = useCallback((current: Run) => {
    if (current.session_id !== activeId.current) return;
    setRun((previous) => previous?.session_id === current.session_id && previous.revision > current.revision ? previous : current);
  }, []);
  const stream = useRunSocket(run?.session_id ?? null, apply, setError);

  useEffect(() => {
    const savedTheme = localStorage.getItem("webmorph-theme");
    const savedLanguage = localStorage.getItem("webmorph-language") as Language | null;
    if (savedTheme === "contrast" || savedTheme === "reading") setTheme(savedTheme);
    if (savedLanguage && ["en", "hi", "kn", "es", "fr"].includes(savedLanguage)) setLanguage(savedLanguage);
    setPlain(localStorage.getItem("webmorph-plain") !== "false");
    setReady(true);
    let alive = true;
    const savedId = sessionStorage.getItem("webmorph-run");
    if (savedId) api.state(savedId).then((current) => {
      if (!alive || activeId.current || busyRef.current) return;
      activeId.current = current.session_id;
      setRun(current); setUrl(current.url); setGoal(current.goal);
    }).catch(() => { if (alive && !activeId.current) sessionStorage.removeItem("webmorph-run"); });
    function check() { api.health().then(() => { if (alive) setOnline(true); }).catch(() => { if (alive) setOnline(false); }); }
    check();
    const timer = setInterval(check, 8000);
    return () => { alive = false; clearInterval(timer); };
  }, []);

  useEffect(() => {
    if (!ready) return;
    localStorage.setItem("webmorph-theme", theme);
    localStorage.setItem("webmorph-language", language);
    localStorage.setItem("webmorph-plain", String(plain));
    document.documentElement.dataset.appearance = theme;
  }, [ready, language, plain, theme]);

  async function perform(operation: () => Promise<void>) {
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(true); setError("");
    try { await operation(); }
    catch (problem) { setError(problem instanceof Error ? problem.message : "The action could not be completed."); }
    finally { busyRef.current = false; setBusy(false); }
  }

  function start() {
    void perform(async () => {
      setLaunching(true);
      try {
        let target: URL;
        try { target = new URL(url.trim()); } catch { throw new Error("Enter a full website address beginning with http:// or https://."); }
        if (!["http:", "https:"].includes(target.protocol)) throw new Error("Use an HTTP or HTTPS website address.");
        if (run && !["COMPLETED", "FAILED"].includes(run.status)) throw new Error("Close the current browser session before scouting another website.");
        const current = await api.launch(target.href, goal, language);
        activeId.current = current.session_id;
        sessionStorage.setItem("webmorph-run", current.session_id);
        setRun(current);
      } finally { setLaunching(false); }
    });
  }

  function answer(values: Record<string, Value>) {
    if (run) void perform(async () => apply(await api.answer(run.session_id, values)));
  }
  function takeover() {
    if (run) void perform(async () => apply(await api.takeover(run.session_id)));
  }
  function resume() {
    if (run) void perform(async () => apply(await api.resume(run.session_id)));
  }
  function close() {
    if (run) void perform(async () => {
      await api.close(run.session_id);
      activeId.current = null;
      sessionStorage.removeItem("webmorph-run");
      setRun(null);
    });
  }
  function approve() {
    const token = run?.approval?.token;
    if (run && token) void perform(async () => apply(await api.approve(run.session_id, token)));
  }

  const state = run?.status ?? "IDLE";
  const formKey = run ? `${run.session_id}-${run.timeline.at(-1)?.at || ""}` : "";
  return (
    <div className="app-shell">
      <TopBar url={url} goal={goal} language={language} theme={theme} plain={plain} busy={launching} online={online}
        setUrl={setUrl} setGoal={setGoal} setLanguage={setLanguage} setTheme={setTheme} setPlain={setPlain}
        onLaunch={start} onDemo={() => { setUrl(DEMO_URL); setGoal(DEMO_GOAL); }} onVault={() => setDrawer("vault")} onHistory={() => setDrawer("history")} />
      {error && <div className="notice error-notice" role="alert"><CircleAlert size={17} />{error}<button type="button" className="help-icon" aria-label="Dismiss error" onClick={() => setError("")}><X size={16} /></button></div>}
      <main className="workspace">
        <section className="adaptive panel" aria-labelledby="adaptive-title">
          <div className="pane-heading"><div className="section-title"><Layers3 size={19} /><h2 id="adaptive-title">Adaptive workspace</h2></div><span className="pane-caption">{run?.schema.step || STATUS[state]}</span></div>
          <div className="adaptive-content">
            {state === "IDLE" && <div className="idle-intake">
              <div className="idle-icon"><Workflow size={30} strokeWidth={1.6} /></div>
              <h3>Ready when you are</h3>
              <p>Scout a website to uncover what it needs and turn its forms into a guided workflow.</p>
              <div className="idle-steps">
                <div><ScanLine size={18} /><span><b>Scout</b><small>See requirements up front</small></span></div>
                <div><ClipboardList size={18} /><span><b>Answer</b><small>Fill gaps with help from your Vault</small></span></div>
                <div><ShieldCheck size={18} /><span><b>Review</b><small>Approve final actions</small></span></div>
              </div>
            </div>}
            {state === "SCOUTING" && <div className="state-box" role="status"><LoaderCircle size={24} className="spin" /><h3>Scouting the website</h3><p>Reading the page and identifying the fields you’ll need.</p></div>}
            {run?.brief && (state === "AWAITING_USER_FORM" || state === "EXECUTING") && <PreFlightBrief brief={run.brief} />}
            {run && state === "AWAITING_USER_FORM" && <section className="subcard">
              <div className="subcard-heading"><div className="tile-icon"><ClipboardList size={19} /></div><div><h3>Website fields</h3><p>{run.schema.fields.length ? "Review the suggested values and add the missing answers." : "The pilot will find the next step on the site."}</p></div></div>
              <AdaptiveForm key={formKey} fields={run.schema.fields} sessionId={run.session_id} submitLabel="Auto-apply to website" busy={busy} plain={plain} language={language} onSubmit={answer} />
            </section>}
            {run && state === "NEEDS_USER_INPUT" && <MidFlightModal key={formKey} run={run} busy={busy} plain={plain} language={language} onSubmit={answer} />}
            {state === "EXECUTING" && <div className="state-box" role="status"><Radar size={24} /><h3>Pilot active</h3><p>Follow the live browser as WebMorph fills and verifies the page.</p></div>}
            {run && state === "HUMAN_TAKEOVER" && <div className="state-box take-state" role="status"><Hand size={25} /><h3>Your turn in the browser</h3><p>{run.message}</p><p>Click inside the live browser to interact, then hand control back to the agent.</p></div>}
            {run?.approval && state === "AWAITING_APPROVAL" && <ApprovalGate approval={run.approval} busy={busy} onApprove={approve} onTakeover={takeover} />}
            {run?.receipt && state === "COMPLETED" && <section className="subcard receipt-card">
              <div className="subcard-heading"><div className="tile-icon green"><CircleCheck size={21} /></div><div><h3>Workflow complete</h3><p>{run.receipt.summary}</p></div></div>
              {run.receipt.reference && <div className="receipt-ref"><span>Reference ID</span><strong>{run.receipt.reference}</strong></div>}
              <button type="button" className="button" onClick={() => void perform(() => downloadAudit(run.session_id))}><Download size={17} />Download audit JSON</button>
            </section>}
            {run && state === "FAILED" && <div className="state-box failed-state" role="alert"><CircleAlert size={24} /><h3>The run stopped</h3><p>{run.message}</p><button type="button" className="button" onClick={() => void perform(() => downloadAudit(run.session_id))}><Download size={17} />Download audit JSON</button></div>}
            {run?.provider_notice && state !== "FAILED" && <p className="provider-note">{run.provider_notice.split(" · ").slice(1).join(" · ") || run.provider_notice}</p>}
          </div>
        </section>
        <div className="glassbox">
          <LiveBrowser run={run} {...stream} busy={busy} onTakeover={takeover} onResume={resume} onClose={close} />
          <ActionTimeline entries={run?.timeline ?? []} />
        </div>
      </main>
      {drawer === "vault" && <VaultDrawer onClose={() => setDrawer(null)} />}
      {drawer === "history" && <HistoryDrawer close={() => setDrawer(null)} />}
    </div>
  );
}
