import { statusSummary } from "@/lib/format";
import type { Meeting } from "@/lib/types";

export function StatusBadge({ meeting }: { meeting: Meeting }) {
  const { label, kind } = statusSummary(meeting);
  const styles = {
    done: "bg-green-50 text-green-700 border-green-200",
    running: "bg-brand-50 text-brand-700 border-brand-100",
    waiting: "bg-amber-50 text-amber-800 border-amber-200",
    error: "bg-red-50 text-red-700 border-red-200",
  }[kind];
  const icon = { done: "✓", running: "⟳", waiting: "!", error: "×" }[kind];
  return (
    <span className={`inline-flex items-center gap-1 whitespace-nowrap rounded-full border px-2.5 py-0.5 text-xs font-semibold ${styles}`}>
      <span aria-hidden className={kind === "running" ? "inline-block animate-spin" : ""}>
        {icon}
      </span>
      {label}
    </span>
  );
}
