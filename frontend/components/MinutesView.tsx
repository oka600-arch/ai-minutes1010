"use client";

import { useState } from "react";
import { Button, inputClass } from "@/components/ui";
import { TOOL_LABELS, formatDateTime } from "@/lib/format";
import type { Meeting, Minutes, MinutesData, MinutesFieldDef, MinutesTypeDef, TodoItem } from "@/lib/types";

// 冒頭の基本情報に表示する項目（会議記録のタイトル・日時・担当者）
const HEADER_KEYS = ["title", "datetime", "assignee"];
const EMPTY_TODO: TodoItem = { task: "", assignee: "", deadline: "" };

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

/** 改行を含む文章。【】で始まる行は小見出し、「・」で始まる行は箇条書きとして表示する */
function MultilineText({ text }: { text: string }) {
  const lines = text.split("\n").filter((l) => l.trim());
  if (lines.length === 0) return <p className="text-sm text-gray-500">なし</p>;
  return (
    <div className="space-y-1 text-sm leading-relaxed">
      {lines.map((line, i) =>
        line.trim().startsWith("【") ? (
          <p key={i} className="pt-2 font-semibold first:pt-0">
            {line}
          </p>
        ) : (
          <p key={i} className={line.trim().startsWith("・") ? "pl-3 -indent-3" : ""}>
            {line}
          </p>
        ),
      )}
    </div>
  );
}

function Todos({ todos }: { todos: TodoItem[] }) {
  if (todos.length === 0) return <p className="text-sm text-gray-500">なし</p>;
  return (
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
          {todos.map((t, i) => (
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
        {todos.map((t, i) => (
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
  );
}

function asText(v: MinutesData[string] | undefined): string {
  return typeof v === "string" ? v : "";
}
function asList(v: MinutesData[string] | undefined): string[] {
  return Array.isArray(v) ? (v as string[]).filter((x) => typeof x === "string") : [];
}
function asTodos(v: MinutesData[string] | undefined): TodoItem[] {
  return Array.isArray(v) ? (v as TodoItem[]).filter((x) => typeof x === "object" && x !== null) : [];
}

function FieldValue({ field, data }: { field: MinutesFieldDef; data: MinutesData }) {
  if (field.kind === "text") return <MultilineText text={asText(data[field.key])} />;
  if (field.kind === "list") return <Bullets items={asList(data[field.key])} />;
  return <Todos todos={asTodos(data[field.key])} />;
}

// ---------------------------------------------------------------- 表示

export function MinutesView({ meeting, minutes, type }: { meeting: Meeting; minutes: Minutes; type: MinutesTypeDef }) {
  const d = minutes.data;
  const has = (key: string) => type.fields.some((f) => f.key === key);
  return (
    <article className="space-y-4">
      <dl className="grid grid-cols-[5.5rem_1fr] gap-x-3 gap-y-1 text-sm">
        <dt className="text-gray-500">{has("title") ? "タイトル" : "会議名"}</dt>
        <dd className="font-semibold">{asText(d.title) || meeting.meeting_name}</dd>
        <dt className="text-gray-500">日時</dt>
        <dd>{asText(d.datetime) || formatDateTime(meeting.meeting_datetime)}</dd>
        {has("assignee") && (
          <>
            <dt className="text-gray-500">担当者</dt>
            <dd className={isUnclear(asText(d.assignee)) ? "text-amber-700" : ""}>{asText(d.assignee) || "不明"}</dd>
          </>
        )}
        <dt className="text-gray-500">会議ツール</dt>
        <dd>{TOOL_LABELS[meeting.meeting_tool]}</dd>
        <dt className="text-gray-500">参加者</dt>
        <dd>{meeting.participants.length ? meeting.participants.map((p) => p.name).join("、") : "記載なし"}</dd>
      </dl>

      {type.fields
        .filter((f) => !HEADER_KEYS.includes(f.key))
        .map((f) => (
          <Section key={f.key} title={f.label}>
            <FieldValue field={f} data={d} />
          </Section>
        ))}
    </article>
  );
}

// ---------------------------------------------------------------- 編集

function TodoEditor({ value, onChange }: { value: TodoItem[]; onChange: (v: TodoItem[]) => void }) {
  const update = (i: number, patch: Partial<TodoItem>) => onChange(value.map((t, j) => (j === i ? { ...t, ...patch } : t)));
  return (
    <div className="space-y-2">
      {value.map((t, i) => (
        <div key={i} className="grid gap-2 rounded-md border border-gray-200 p-2 sm:grid-cols-[1fr_8rem_10rem_auto]">
          <input value={t.task} onChange={(e) => update(i, { task: e.target.value })} placeholder="タスク" aria-label={`タスク${i + 1}`} className={inputClass} />
          <input value={t.assignee} onChange={(e) => update(i, { assignee: e.target.value })} placeholder="担当者" aria-label={`担当者${i + 1}`} className={inputClass} />
          <input value={t.deadline} onChange={(e) => update(i, { deadline: e.target.value })} placeholder="期限" aria-label={`期限${i + 1}`} className={inputClass} />
          <button
            type="button"
            onClick={() => onChange(value.filter((_, j) => j !== i))}
            className="rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-600 hover:bg-gray-50"
          >
            削除
          </button>
        </div>
      ))}
      <button type="button" onClick={() => onChange([...value, EMPTY_TODO])} className="text-sm text-brand-600 hover:underline">
        ＋ タスクを追加
      </button>
    </div>
  );
}

export function MinutesEditor({
  type,
  initial,
  saving,
  onSave,
  onCancel,
}: {
  type: MinutesTypeDef;
  initial: MinutesData;
  saving: boolean;
  onSave: (data: MinutesData) => void;
  onCancel: () => void;
}) {
  // 箇条書きは「1行に1項目」のテキストとして編集し、保存時に配列へ戻す
  const [draft, setDraft] = useState<Record<string, string | TodoItem[]>>(() =>
    Object.fromEntries(
      type.fields.map((f) => [
        f.key,
        f.kind === "text" ? asText(initial[f.key]) : f.kind === "list" ? asList(initial[f.key]).join("\n") : asTodos(initial[f.key]),
      ]),
    ),
  );

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const data: MinutesData = {};
    for (const f of type.fields) {
      const v = draft[f.key];
      if (f.kind === "list") data[f.key] = String(v).split("\n").map((l) => l.replace(/^\s*・\s*/, "").trim()).filter(Boolean);
      else if (f.kind === "todos") data[f.key] = (v as TodoItem[]).filter((t) => t.task.trim());
      else data[f.key] = String(v);
    }
    onSave(data);
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      {type.fields.map((f) => (
        <div key={f.key}>
          <label htmlFor={`field-${f.key}`} className="mb-1 block text-sm font-semibold text-gray-700">
            {f.label}
            {f.kind === "list" && <span className="ml-2 text-xs font-normal text-gray-500">1行に1項目</span>}
          </label>
          {f.kind === "todos" ? (
            <TodoEditor value={draft[f.key] as TodoItem[]} onChange={(v) => setDraft((d) => ({ ...d, [f.key]: v }))} />
          ) : f.kind === "text" && HEADER_KEYS.includes(f.key) ? (
            <input
              id={`field-${f.key}`}
              value={draft[f.key] as string}
              onChange={(e) => setDraft((d) => ({ ...d, [f.key]: e.target.value }))}
              className={inputClass}
            />
          ) : (
            <textarea
              id={`field-${f.key}`}
              value={draft[f.key] as string}
              onChange={(e) => setDraft((d) => ({ ...d, [f.key]: e.target.value }))}
              rows={f.key === "details" ? 14 : f.kind === "list" ? 5 : 4}
              className={`${inputClass} leading-relaxed`}
            />
          )}
        </div>
      ))}
      <div className="flex flex-col-reverse gap-2 border-t border-gray-200 pt-4 sm:flex-row sm:justify-end">
        <Button type="button" variant="secondary" onClick={onCancel} disabled={saving}>
          キャンセル
        </Button>
        <Button type="submit" disabled={saving}>
          {saving ? "保存しています…" : "保存してWord/PDFを更新"}
        </Button>
      </div>
    </form>
  );
}
