"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { UploadDropzone } from "@/components/UploadDropzone";
import { Alert, Button, Card, Field, inputClass } from "@/components/ui";
import { api, uploadToStorage } from "@/lib/api";
import { extractAudio } from "@/lib/audio-extract";
import { MAX_AUDIO_BYTES, classifyFile, formatBytes, validateFile } from "@/lib/files";
import { TOOL_LABELS } from "@/lib/format";
import { takePendingFile } from "@/lib/pending-file";
import type { MeetingTool } from "@/lib/types";

function nowForInput(): string {
  const d = new Date();
  d.setMinutes(0, 0, 0);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export default function NewMeetingPage() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [datetime, setDatetime] = useState(nowForInput);
  const [tool, setTool] = useState<MeetingTool>("zoom");
  const [participants, setParticipants] = useState<string[]>([""]);
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState<string | null>(null);

  useEffect(() => {
    const f = takePendingFile();
    if (f) setFile(f);
  }, []);

  function selectFile(f: File) {
    const err = validateFile(f);
    setError(err);
    setFile(err ? null : f);
  }

  function updateParticipant(i: number, value: string) {
    setParticipants((ps) => ps.map((p, j) => (j === i ? value : p)));
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!file) {
      setError("会議データのファイルを選択してください。");
      return;
    }
    const inputType = classifyFile(file);
    const fileErr = validateFile(file);
    if (!inputType || fileErr) {
      setError(fileErr);
      return;
    }

    try {
      // 動画、または上限を超える音声は、ブラウザで音声だけを取り出して圧縮する
      let uploadFile = file;
      if (inputType === "video" || (inputType === "audio" && file.size > MAX_AUDIO_BYTES)) {
        setProgress("音声を取り出しています… 0%");
        uploadFile = await extractAudio(file, (r) => setProgress(`音声を取り出しています… ${Math.round(r * 100)}%`));
        if (uploadFile.size > MAX_AUDIO_BYTES) {
          throw new Error("圧縮後の音声が100MBを超えています。会議を分けてアップロードしてください。");
        }
      }

      setProgress(`アップロードしています…（${formatBytes(uploadFile.size)}）`);
      const created = await api.createMeeting({
        meeting_name: name.trim(),
        meeting_datetime: new Date(datetime).toISOString(),
        meeting_tool: tool,
        participants: participants.map((p) => p.trim()).filter(Boolean),
        input_type: inputType,
        file_name: uploadFile.name,
        file_size: uploadFile.size,
      });
      await uploadToStorage(created.upload_path, created.upload_token, uploadFile);

      setProgress("処理を開始しています…");
      await api.processMeeting(created.meeting.id);
      router.push(`/meetings/${created.meeting.id}`);
    } catch (e) {
      setError((e as Error).message);
      setProgress(null);
    }
  }

  const busy = progress !== null;

  return (
    <Card>
      <h1 className="mb-5 text-lg font-bold">会議データ入力</h1>
      <form onSubmit={onSubmit} className="space-y-5">
        <Field label="会議名">
          <input required maxLength={100} value={name} onChange={(e) => setName(e.target.value)} placeholder="例：営業定例会議" className={inputClass} />
        </Field>

        <div className="grid gap-5 sm:grid-cols-2">
          <Field label="開催日時">
            <input type="datetime-local" required value={datetime} onChange={(e) => setDatetime(e.target.value)} className={inputClass} />
          </Field>
          <Field label="会議ツール">
            <select value={tool} onChange={(e) => setTool(e.target.value as MeetingTool)} className={inputClass}>
              {(Object.keys(TOOL_LABELS) as MeetingTool[]).map((t) => (
                <option key={t} value={t}>
                  {TOOL_LABELS[t]}
                </option>
              ))}
            </select>
          </Field>
        </div>

        <div>
          <span className="mb-1 block text-sm font-semibold text-gray-700">参加者</span>
          <div className="space-y-2">
            {participants.map((p, i) => (
              <div key={i} className="flex gap-2">
                <input
                  value={p}
                  onChange={(e) => updateParticipant(i, e.target.value)}
                  placeholder={`参加者${i + 1}`}
                  aria-label={`参加者${i + 1}`}
                  className={inputClass}
                />
                {participants.length > 1 && (
                  <button
                    type="button"
                    onClick={() => setParticipants((ps) => ps.filter((_, j) => j !== i))}
                    className="shrink-0 rounded-md border border-gray-300 px-3 text-sm text-gray-600 hover:bg-gray-50"
                    aria-label={`参加者${i + 1}を削除`}
                  >
                    削除
                  </button>
                )}
              </div>
            ))}
          </div>
          <button type="button" onClick={() => setParticipants((ps) => [...ps, ""])} className="mt-2 text-sm text-brand-600 hover:underline">
            ＋ 参加者を追加
          </button>
          <p className="mt-1 text-xs text-gray-500">参加者名はAIが担当者を判別する手がかりになります。</p>
        </div>

        <div>
          <span className="mb-1 block text-sm font-semibold text-gray-700">会議データ</span>
          <UploadDropzone file={file} onSelect={selectFile} compact />
          {file && classifyFile(file) === "video" && (
            <p className="mt-2 text-xs text-gray-500">動画はブラウザ内で音声だけを取り出してからアップロードします（映像は送信しません）。</p>
          )}
        </div>

        {error && <Alert>{error}</Alert>}
        {progress && <Alert kind="info">{progress}</Alert>}

        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button type="button" variant="secondary" onClick={() => router.push("/")} disabled={busy}>
            キャンセル
          </Button>
          <Button type="submit" disabled={busy}>
            議事録を生成
          </Button>
        </div>
      </form>
    </Card>
  );
}
