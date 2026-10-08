import type { Meeting, MeetingStatus, MeetingTool, PipelineStep } from "./types";

export const TOOL_LABELS: Record<MeetingTool, string> = {
  zoom: "Zoom",
  google_meet: "Google Meet",
  teams: "Microsoft Teams",
  other: "その他",
};

export function formatDateTime(iso: string): string {
  const d = new Date(iso);
  return new Intl.DateTimeFormat("ja-JP", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "Asia/Tokyo",
  }).format(d);
}

export function formatShortDate(iso: string): string {
  return new Intl.DateTimeFormat("ja-JP", { month: "2-digit", day: "2-digit", timeZone: "Asia/Tokyo" }).format(new Date(iso));
}

export type StatusKind = "done" | "running" | "waiting" | "error";

export function statusSummary(m: Meeting): { label: string; kind: StatusKind } {
  switch (m.status) {
    case "COMPLETED":
      return { label: "完了", kind: "done" };
    case "GENERATED":
      return { label: "生成済み（Dropbox未保存）", kind: "waiting" };
    case "ERROR":
      return { label: "エラー", kind: "error" };
    default:
      return { label: "処理中", kind: "running" };
  }
}

// 処理状況画面のステップ（実際の処理単位に合わせる）
export interface StepView {
  key: "upload" | PipelineStep;
  label: string;
}

export function stepsFor(m: Meeting): StepView[] {
  return [
    { key: "upload", label: "ファイル受付" },
    { key: "transcribe", label: m.input_type === "text" ? "文字起こしデータ読込" : "文字起こし" },
    { key: "analyze", label: "AI解析（要約・決定事項・TODO・未決事項）" },
    { key: "generate", label: "Word/PDF生成" },
    { key: "dropbox", label: "Dropbox保存" },
  ];
}

const ORDER: StepView["key"][] = ["upload", "transcribe", "analyze", "generate", "dropbox"];

const RUNNING_STEP: Partial<Record<MeetingStatus, StepView["key"]>> = {
  UPLOADED: "transcribe",
  TRANSCRIBING: "transcribe",
  TRANSCRIBED: "analyze",
  ANALYZING: "analyze",
  GENERATING: "generate",
  UPLOADING: "dropbox",
};

export type StepState = "done" | "running" | "pending" | "error" | "skipped";

/** 各ステップの状態を、会議のステータスから求める */
export function stepState(m: Meeting, key: StepView["key"]): StepState {
  const idx = ORDER.indexOf(key);
  if (m.status === "COMPLETED") return "done";
  if (m.status === "GENERATED") return key === "dropbox" ? "skipped" : "done";
  if (m.status === "ERROR") {
    const errIdx = ORDER.indexOf(m.error_step ?? "transcribe");
    if (idx < errIdx) return "done";
    return idx === errIdx ? "error" : "pending";
  }
  const runIdx = ORDER.indexOf(RUNNING_STEP[m.status] ?? "transcribe");
  if (idx < runIdx) return "done";
  return idx === runIdx ? "running" : "pending";
}

export function isProcessing(m: Meeting): boolean {
  return !["COMPLETED", "GENERATED", "ERROR"].includes(m.status);
}

export const STEP_ERROR_LABELS: Record<PipelineStep, string> = {
  transcribe: "文字起こし",
  analyze: "AI解析",
  generate: "Word/PDF生成",
  dropbox: "Dropbox保存",
};
