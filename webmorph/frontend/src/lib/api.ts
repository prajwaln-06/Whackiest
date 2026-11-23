export type Language = "en" | "hi" | "kn" | "es" | "fr";
export type Value = string | boolean | string[] | null;
export type Status =
  | "IDLE" | "SCOUTING" | "AWAITING_USER_FORM" | "EXECUTING"
  | "NEEDS_USER_INPUT" | "HUMAN_TAKEOVER" | "AWAITING_APPROVAL"
  | "COMPLETED" | "FAILED";

export interface FieldSpec {
  key: string;
  original: string;
  label: string;
  hint: string;
  kind: string;
  required: boolean;
  confirm_explicitly: boolean;
  options: { label: string; value: string }[];
  current: Value;
  suggestion: Value;
  confidence: number | null;
  source: string | null;
  error: string | null;
  accept: string;
  multiple: boolean;
  minimum: string;
  maximum: string;
  pattern: string;
  max_length: number | null;
  step: string;
}

export interface Schema { title: string; url: string; step: string; fields: FieldSpec[] }
export interface Brief {
  summary: string;
  documents: string[];
  deadlines: string[];
  warnings: string[];
  eligibility: string[];
  source: "llm" | "heuristic";
}
export interface Entry {
  at: string;
  action: string;
  label: string;
  strategy: string;
  verified: boolean | null;
  duration_ms: number;
  detail: string;
}
export interface Change { key: string; label: string; before: Value; after: Value; step: string; url: string; verified: boolean }
export interface Approval { token: string; button: string; screenshot: string; changes: Change[] }
export interface Receipt { reference: string | null; summary: string; url: string }
export interface Run {
  session_id: string;
  revision: number;
  status: Status;
  url: string;
  goal: string;
  schema: Schema;
  brief: Brief | null;
  timeline: Entry[];
  approval: Approval | null;
  receipt: Receipt | null;
  message: string;
  provider_notice: string;
  transitions: number;
}
export interface History { session_id: string; updated: string; status: Status; url: string; goal: string }

export const STATUS: Record<Status, string> = {
  IDLE: "Ready",
  SCOUTING: "Scouting",
  AWAITING_USER_FORM: "Ready for answers",
  EXECUTING: "Pilot active",
  NEEDS_USER_INPUT: "Waiting for answers",
  HUMAN_TAKEOVER: "Manual control",
  AWAITING_APPROVAL: "Paused for approval",
  COMPLETED: "Completed",
  FAILED: "Run stopped",
};

export const BASE = process.env.NEXT_PUBLIC_WEBMORPH_API || "http://127.0.0.1:8000";

async function request<T>(path: string, method = "GET", body?: object): Promise<T> {
  const headers: Record<string, string> = { "X-WebMorph-Client": "workspace" };
  const multipart = body instanceof FormData;
  if (body && !multipart) headers["Content-Type"] = "application/json";
  let response: Response;
  try {
    response = await fetch(`${BASE}/api${path}`, {
      method, headers, body: multipart ? body : body ? JSON.stringify(body) : undefined,
      signal: AbortSignal.timeout(35000), cache: "no-store",
    });
  } catch {
    throw new Error("Could not reach WebMorph. Check that the local backend is running.");
  }
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    const detail = typeof data.detail === "string" ? data.detail : data.detail?.[0]?.msg;
    throw new Error(detail || `The request failed (${response.status}).`);
  }
  return response.json() as Promise<T>;
}

function upload(file: File) {
  const data = new FormData();
  data.append("file", file);
  return data;
}

export const api = {
  health: () => request<{ status: string; provider_configured: boolean }>("/health"),
  launch: (url: string, goal: string, language: Language) => request<Run>("/runs", "POST", { url, goal, language }),
  state: (id: string) => request<Run>(`/runs/${id}`),
  history: () => request<History[]>("/runs"),
  close: (id: string) => request(`/runs/${id}`, "DELETE"),
  answer: (id: string, values: Record<string, Value>) => request<Run>(`/runs/${id}/answers`, "POST", { values }),
  approve: (id: string, token: string) => request<Run>(`/runs/${id}/approve`, "POST", { token }),
  takeover: (id: string) => request<Run>(`/runs/${id}/takeover`, "POST"),
  resume: (id: string) => request<Run>(`/runs/${id}/resume`, "POST"),
  file: (id: string, file: File) => request<{ token: string; name: string }>(`/runs/${id}/files`, "POST", upload(file)),
  vault: () => request<{ facts: Record<string, string> }>("/vault"),
  saveVault: (facts: Record<string, string>) => request<{ facts: Record<string, string> }>("/vault", "PUT", { facts }),
  document: (file: File) => request<{ facts: Record<string, string>; notice: string }>("/vault/document", "POST", upload(file)),
  audit: (id: string) => request<Record<string, unknown>>(`/runs/${id}/audit`),
};

export async function downloadAudit(id: string) {
  const data = await api.audit(id);
  const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = `webmorph-${id}.json`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function formatValue(value: Value): string {
  if (Array.isArray(value)) return value.length ? value.join(", ") : "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return value || "—";
}
