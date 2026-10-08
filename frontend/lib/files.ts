import type { InputType } from "./types";

export const TEXT_EXTENSIONS = ["txt", "vtt", "srt"];
export const AUDIO_EXTENSIONS = ["mp3", "m4a", "wav", "webm", "ogg", "aac", "flac", "mpeg", "mpga"];
export const VIDEO_EXTENSIONS = ["mp4", "mov", "mkv", "avi", "m4v"];

export const MAX_TEXT_BYTES = 5 * 1024 * 1024;
export const MAX_AUDIO_BYTES = 100 * 1024 * 1024;
// ブラウザで変換できる動画の目安（ブラウザのメモリ上で処理するため）
export const MAX_VIDEO_BYTES = 1.5 * 1024 * 1024 * 1024;

export const ACCEPT = [...TEXT_EXTENSIONS, ...AUDIO_EXTENSIONS, ...VIDEO_EXTENSIONS].map((e) => `.${e}`).join(",");

export function extensionOf(name: string): string {
  const i = name.lastIndexOf(".");
  return i >= 0 ? name.slice(i + 1).toLowerCase() : "";
}

export function classifyFile(file: File): InputType | null {
  const ext = extensionOf(file.name);
  if (TEXT_EXTENSIONS.includes(ext)) return "text";
  if (AUDIO_EXTENSIONS.includes(ext)) return "audio";
  if (VIDEO_EXTENSIONS.includes(ext)) return "video";
  return null;
}

/** ファイル形式・容量をチェックし、問題があればエラーメッセージを返す */
export function validateFile(file: File): string | null {
  const type = classifyFile(file);
  if (!type) return "対応していないファイル形式です。音声・動画・TXT・VTT・SRT を選択してください。";
  if (file.size === 0) return "ファイルが空です。";
  if (type === "text" && file.size > MAX_TEXT_BYTES) return "文字起こしファイルは5MBまでです。";
  if (type === "video" && file.size > MAX_VIDEO_BYTES) return "動画ファイルが大きすぎます（1.5GBまで）。音声のみを書き出してアップロードしてください。";
  return null;
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))}KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)}MB`;
}
