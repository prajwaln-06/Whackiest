import { CornerDownRight } from "lucide-react";
import { Language, Run, Value } from "@/lib/api";
import AdaptiveForm from "./AdaptiveForm";

export default function MidFlightModal({ run, busy, plain, language, onSubmit }: {
  run: Run; busy: boolean; plain: boolean; language: Language; onSubmit: (values: Record<string, Value>) => void;
}) {
  return (
    <section className="subcard follow-card" aria-labelledby="follow-title">
      <div className="subcard-heading"><div className="tile-icon amber"><CornerDownRight size={20} /></div><div><h3 id="follow-title">A few more answers</h3><p>{run.message || "The website revealed new fields."}</p></div></div>
      <AdaptiveForm fields={run.schema.fields} sessionId={run.session_id} submitLabel="Continue" busy={busy} plain={plain} language={language} onSubmit={onSubmit} />
    </section>
  );
}
