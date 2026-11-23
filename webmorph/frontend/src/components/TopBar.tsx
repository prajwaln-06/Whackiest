"use client";

import { Accessibility, Box, ChevronDown, FlaskConical, Globe2, History, Languages, LoaderCircle, ScanLine, Target, Vault } from "lucide-react";
import { Language } from "@/lib/api";

export type Theme = "dark" | "contrast" | "reading";

export default function TopBar(props: {
  url: string; goal: string; language: Language; theme: Theme; plain: boolean; busy: boolean; online: boolean;
  setUrl: (value: string) => void; setGoal: (value: string) => void;
  setLanguage: (value: Language) => void; setTheme: (value: Theme) => void; setPlain: (value: boolean) => void;
  onLaunch: () => void; onDemo: () => void; onVault: () => void; onHistory: () => void;
}) {
  return (
    <>
      <header className="topbar">
        <div className="top-inner">
          <div className="brand" aria-label="WebMorph workspace">
            <span className="brand-mark"><Box size={21} strokeWidth={2.2} /></span>
            <span>Web<span className="brand-accent">Morph</span></span>
          </div>
          <div className="top-actions">
            <div className="toolbar-select"><Accessibility size={17} /><select aria-label="Accessibility mode" value={props.theme} onChange={(ev) => props.setTheme(ev.target.value as Theme)}>
              <option value="dark">Obsidian dark</option><option value="contrast">High contrast</option><option value="reading">Dyslexia-friendly</option>
            </select><ChevronDown size={13} /></div>
            <label className="plain-toggle"><input type="checkbox" checked={props.plain} onChange={(ev) => props.setPlain(ev.target.checked)} /><span>Plain language</span></label>
            <div className="toolbar-select"><Languages size={17} /><select aria-label="Form language" value={props.language} onChange={(ev) => props.setLanguage(ev.target.value as Language)}>
              <option value="en">English</option><option value="hi">हिन्दी</option><option value="kn">ಕನ್ನಡ</option><option value="es">Español</option><option value="fr">Français</option>
            </select><ChevronDown size={13} /></div>
            <button className="button button-icon" type="button" title="Run history" aria-label="Run history" onClick={props.onHistory}><History size={17} /></button>
            <button className="button vault-button" type="button" onClick={props.onVault}><Vault size={16} />My Vault</button>
          </div>
        </div>
      </header>
      <div className="page-heading">
        <div>
          <h1>Browser Workspace</h1>
          <p>Tell WebMorph what you want to do on a website.</p>
        </div>
        <span className={`service-status ${props.online ? "up" : ""}`}><i />{props.online ? "Local agent online" : "Local agent offline"}</span>
      </div>
      <form className="command panel" onSubmit={(ev) => { ev.preventDefault(); props.onLaunch(); }}>
        <div className="command-head"><div><ScanLine size={18} /><h2>Start a workflow</h2></div><button className="button demo-button" type="button" onClick={props.onDemo}><FlaskConical size={16} />Launch Demo Portal</button></div>
        <div className="command-fields">
          <label><span>Target website</span><div className="input-wrap"><Globe2 size={17} /><input value={props.url} onChange={(ev) => props.setUrl(ev.target.value)} placeholder="https://example.org/application" required inputMode="url" maxLength={2000} /></div></label>
          <label><span>Your goal</span><div className="input-wrap"><Target size={17} /><input value={props.goal} onChange={(ev) => props.setGoal(ev.target.value)} placeholder="What would you like to get done?" required minLength={3} maxLength={600} /></div></label>
          <button className="button primary scout-button" type="submit" disabled={props.busy}>{props.busy ? <LoaderCircle className="spin" size={17} /> : <ScanLine size={17} />} Scout website</button>
        </div>
      </form>
    </>
  );
}
