"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { MinutesView } from "@/components/MinutesView";
import { ProgressSteps } from "@/components/ProgressSteps";
import { Alert, Button, Card } from "@/components/ui";
import { api } from "@/lib/api";
import { STEP_ERROR_LABELS, isProcessing } from "@/lib/format";
import type { DropboxStatus, FileType, Meeting, Minutes } from "@/lib/types";

const POLL_MS = 2000;

export default function MeetingPage() {
  const { id } = useParams<{ id: string }>();
  const [meeting, setMeeting] = useState<Meeting | null>(null);
  const [minutes, setMinutes] = useState<Minutes | null>(null);
  const [dropbox, setDropbox] = useState<DropboxStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const minutesLoaded = useRef(false);

  const load = useCallback(async () => {
    try {
      const m = await api.getMeeting(id);
      setMeeting(m);
      setError(null);
      if (["GENERATED", "UPLOADING", "COMPLETED"].includes(m.status) || (m.status === "ERROR" && m.error_step === "dropbox")) {
        if (!minutesLoaded.current) {
          setMinutes(await api.getMinutes(id));
          minutesLoaded.current = true;
        }
      }
    } catch (e) {
      setError((e as Error).message);
    }
  }, [id]);

  useEffect(() => {
    load();
    api.dropboxStatus().then(setDropbox).catch(() => setDropbox(null));
  }, [load]);

  useEffect(() => {
    if (!meeting || !isProcessing(meeting)) return;
    const t = setTimeout(load, POLL_MS);
    return () => clearTimeout(t);
  }, [meeting, load]);

  async function run(action: () => Promise<Meeting>) {
    setBusy(true);
    setActionError(null);
    try {
      setMeeting(await action());
    } catch (e) {
      setActionError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function download(type: FileType) {
    setActionError(null);
    try {
      const { url } = await api.getFileUrl(id, type);
      window.location.href = url;
    } catch (e) {
      setActionError((e as Error).message);
    }
  }

  if (error && !meeting) {
    return (
      <Card>
        <Alert>{error}</Alert>
        <Link href="/" className="mt-4 inline-block text-sm text-brand-600 hover:underline">
          ダッシュボードへ戻る
        </Link>
      </Card>
    );
  }
  if (!meeting) return <p className="text-sm text-gray-500">読み込み中…</p>;

  const processing = isProcessing(meeting);
  const failed = meeting.status === "ERROR";

  return (
    <div className="space-y-6">
      {(processing || failed || !minutes) && (
        <Card>
          <h1 className="mb-4 text-lg font-bold">{processing ? "議事録を生成しています" : failed ? "議事録の生成に失敗しました" : meeting.meeting_name}</h1>
          {failed && (
            <div className="mb-4 space-y-3">
              <Alert>
                <p className="font-semibold">原因：{meeting.error_step ? `${STEP_ERROR_LABELS[meeting.error_step]}で失敗しました。` : ""}</p>
                <p>{meeting.error_message}</p>
              </Alert>
              {meeting.error_message?.includes("再連携") && (
                <Link href="/settings" className="text-sm text-brand-600 hover:underline">
                  設定画面でDropboxを再連携する
                </Link>
              )}
              <Button onClick={() => run(() => api.processMeeting(id))} disabled={busy}>
                再試行
              </Button>
            </div>
          )}
          <ProgressSteps meeting={meeting} />
          {processing && (
            <p className="mt-4 text-xs text-gray-500">
              {meeting.input_type !== "text" && meeting.status === "TRANSCRIBING"
                ? "音声の文字起こしには、録音時間の半分〜同じくらいの時間がかかります。"
                : ""}
              この画面を閉じても処理は続きます。
            </p>
          )}
        </Card>
      )}

      {minutes && (
        <Card>
          <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <h1 className="text-lg font-bold">AI自動生成議事録</h1>
              <p className="mt-1 text-xs text-gray-500">AIが生成したベース資料です。正式な議事録は内容を確認のうえ作成してください。</p>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button variant="secondary" onClick={() => download("docx")}>
                Wordダウンロード
              </Button>
              <Button variant="secondary" onClick={() => download("pdf")}>
                PDFダウンロード
              </Button>
              {dropbox?.connected ? (
                <Button onClick={() => run(() => api.saveToDropbox(id))} disabled={busy || meeting.status === "UPLOADING"}>
                  {meeting.status === "COMPLETED" ? "Dropboxへ再保存" : "Dropboxへ保存"}
                </Button>
              ) : (
                <Link
                  href="/settings"
                  className="inline-flex items-center rounded-md bg-brand-700 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-800"
                >
                  Dropboxを連携して保存
                </Link>
              )}
            </div>
          </div>
          {meeting.status === "COMPLETED" && meeting.dropbox_folder_path && (
            <div className="mb-4">
              <Alert kind="success">Dropboxに保存しました：{meeting.dropbox_folder_path}</Alert>
            </div>
          )}
          {meeting.status === "UPLOADING" && (
            <div className="mb-4">
              <Alert kind="info">Dropboxに保存しています…</Alert>
            </div>
          )}
          {actionError && (
            <div className="mb-4">
              <Alert>{actionError}</Alert>
            </div>
          )}
          <MinutesView meeting={meeting} minutes={minutes} />
          <p className="mt-6 border-t border-gray-200 pt-3 text-xs text-gray-400">
            <button onClick={() => download("transcript")} className="hover:underline">
              文字起こし全文をダウンロード
            </button>
          </p>
        </Card>
      )}
      {actionError && !minutes && <Alert>{actionError}</Alert>}
    </div>
  );
}
