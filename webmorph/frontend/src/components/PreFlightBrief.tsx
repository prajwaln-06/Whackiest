import { CalendarClock, ClipboardList, FileText, ShieldCheck, TriangleAlert } from "lucide-react";
import type { Brief } from "@/lib/api";

export default function PreFlightBrief({ brief }: { brief: Brief }) {
  const sections = [
    { label: "Required documents", items: brief.documents, icon: FileText },
    { label: "Deadlines", items: brief.deadlines, icon: CalendarClock },
    { label: "Eligibility", items: brief.eligibility, icon: ShieldCheck },
    { label: "Things to watch", items: brief.warnings, icon: TriangleAlert },
  ];
  return (
    <section className="subcard brief" aria-labelledby="brief-title">
      <div className="subcard-heading"><div className="tile-icon"><ClipboardList size={19} /></div><div><h3 id="brief-title">Before you start</h3><p>{brief.summary}</p></div></div>
      {sections.filter((section) => section.items.length > 0).map(({ label, items, icon: Icon }) => (
        <div className="brief-row" key={label}><Icon size={16} /><div><h4>{label}</h4><ul>{items.map((item) => <li key={item}>{item}</li>)}</ul></div></div>
      ))}
    </section>
  );
}
