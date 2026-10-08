import { TOOL_LABELS, formatDateTime } from "@/lib/format";
import type { Meeting, Minutes } from "@/lib/types";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="border-t border-gray-200 pt-4">
      <h3 className="mb-2 text-sm font-bold text-brand-700">■ {title}</h3>
      {children}
    </section>
  );
}

function Bullets({ items }: { items: string[] }) {
  if (items.length === 0) return <p className="text-sm text-gray-500">なし</p>;
  return (
    <ul className="space-y-1 text-sm">
      {items.map((item, i) => (
        <li key={i} className="flex gap-1">
          <span aria-hidden>・</span>
          <span>{item}</span>
        </li>
      ))}
    </ul>
  );
}

function isUnclear(value: string) {
  return value === "不明" || value === "会議中に明確な指定なし";
}

export function MinutesView({ meeting, minutes }: { meeting: Meeting; minutes: Minutes }) {
  return (
    <article className="space-y-4">
      <dl className="grid grid-cols-[5.5rem_1fr] gap-x-3 gap-y-1 text-sm">
        <dt className="text-gray-500">会議名</dt>
        <dd className="font-semibold">{meeting.meeting_name}</dd>
        <dt className="text-gray-500">日時</dt>
        <dd>{formatDateTime(meeting.meeting_datetime)}</dd>
        <dt className="text-gray-500">会議ツール</dt>
        <dd>{TOOL_LABELS[meeting.meeting_tool]}</dd>
        <dt className="text-gray-500">参加者</dt>
        <dd>{meeting.participants.length ? meeting.participants.map((p) => p.name).join("、") : "記載なし"}</dd>
      </dl>

      <Section title="会議概要">
        <p className="text-sm leading-relaxed">{minutes.summary || "なし"}</p>
      </Section>

      <Section title="主な議論">
        {minutes.discussion.length === 0 && <p className="text-sm text-gray-500">なし</p>}
        <ol className="space-y-3">
          {minutes.discussion.map((d, i) => (
            <li key={i}>
              <p className="text-sm font-semibold">
                {i + 1}. {d.topic}
              </p>
              <Bullets
                items={d.content
                  .split("\n")
                  .map((l) => l.replace(/^\s*・\s*/, "").trim())
                  .filter(Boolean)}
              />
            </li>
          ))}
        </ol>
      </Section>

      <Section title="決定事項">
        <Bullets items={minutes.decisions} />
      </Section>

      <Section title="TODO">
        {minutes.todos.length === 0 ? (
          <p className="text-sm text-gray-500">なし</p>
        ) : (
          <>
            {/* PC：表 */}
            <table className="hidden w-full border-collapse text-sm sm:table">
              <thead>
                <tr className="bg-brand-700 text-left text-white">
                  <th className="border border-brand-700 px-3 py-2">タスク</th>
                  <th className="w-28 border border-brand-700 px-3 py-2">担当者</th>
                  <th className="w-48 border border-brand-700 px-3 py-2">期限</th>
                </tr>
              </thead>
              <tbody>
                {minutes.todos.map((t, i) => (
                  <tr key={i} className="even:bg-gray-50">
                    <td className="border border-gray-200 px-3 py-2">{t.task}</td>
                    <td className={`border border-gray-200 px-3 py-2 ${isUnclear(t.assignee) ? "text-amber-700" : ""}`}>{t.assignee}</td>
                    <td className={`border border-gray-200 px-3 py-2 ${isUnclear(t.deadline) ? "text-amber-700" : ""}`}>{t.deadline}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {/* スマホ：カード */}
            <ul className="space-y-2 sm:hidden">
              {minutes.todos.map((t, i) => (
                <li key={i} className="rounded-md border border-gray-200 p-3 text-sm">
                  <p className="font-semibold">{t.task}</p>
                  <p className="mt-1 text-gray-600">
                    担当者：<span className={isUnclear(t.assignee) ? "text-amber-700" : ""}>{t.assignee}</span>
                  </p>
                  <p className="text-gray-600">
                    期限：<span className={isUnclear(t.deadline) ? "text-amber-700" : ""}>{t.deadline}</span>
                  </p>
                </li>
              ))}
            </ul>
          </>
        )}
      </Section>

      <Section title="未決事項">
        <Bullets items={minutes.unresolved_items} />
      </Section>

      <Section title="次回確認事項">
        <Bullets items={minutes.next_actions} />
      </Section>
    </article>
  );
}
