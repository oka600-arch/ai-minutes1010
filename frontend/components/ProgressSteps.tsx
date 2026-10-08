import { stepState, stepsFor } from "@/lib/format";
import type { Meeting } from "@/lib/types";

const ICON = { done: "✓", running: "⟳", pending: "○", error: "×", skipped: "–" } as const;
const COLOR = {
  done: "text-green-700",
  running: "text-brand-700 font-semibold",
  pending: "text-gray-400",
  error: "text-red-700 font-semibold",
  skipped: "text-gray-400",
} as const;

export function ProgressSteps({ meeting }: { meeting: Meeting }) {
  const steps = stepsFor(meeting);
  const states = steps.map((s) => stepState(meeting, s.key));
  const done = states.filter((s) => s === "done").length;
  const percent = Math.round((done / steps.length) * 100);

  return (
    <div>
      <ol className="space-y-2">
        {steps.map((s, i) => (
          <li key={s.key} className={`flex items-start gap-3 text-sm ${COLOR[states[i]]}`}>
            <span aria-hidden className={`w-4 shrink-0 text-center ${states[i] === "running" ? "animate-spin" : ""}`}>
              {ICON[states[i]]}
            </span>
            <span>
              {s.label}
              {states[i] === "skipped" && <span className="ml-2 text-xs">（Dropbox未連携のため未保存）</span>}
            </span>
          </li>
        ))}
      </ol>
      <div className="mt-4">
        <div className="mb-1 flex justify-between text-xs text-gray-500">
          <span>進捗</span>
          <span>
            {done} / {steps.length} ステップ（{percent}%）
          </span>
        </div>
        <div className="h-2 overflow-hidden rounded-full bg-gray-200">
          <div className="h-full bg-brand-600 transition-all" style={{ width: `${percent}%` }} />
        </div>
      </div>
    </div>
  );
}
