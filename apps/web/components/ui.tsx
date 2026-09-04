import type { ReactNode } from "react";
import type { Tone } from "@/lib/event-types";

export function Badge({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return <span className={`badge badge-${tone}`}>{children}</span>;
}

export function Panel({
  eyebrow,
  title,
  mark,
  children,
  className = "",
}: {
  eyebrow: string;
  title: string;
  mark: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`panel ${className}`}>
      <div className="panel-heading">
        <div><p className="eyebrow">{eyebrow}</p><h2>{title}</h2></div>
        <span className="panel-mark" aria-hidden>{mark}</span>
      </div>
      {children}
    </section>
  );
}

export function Metric({ label, value, note }: { label: string; value: ReactNode; note?: string }) {
  return <div className="metric"><span>{label}</span><strong>{value}</strong>{note && <small>{note}</small>}</div>;
}
