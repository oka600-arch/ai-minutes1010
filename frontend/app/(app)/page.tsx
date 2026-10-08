"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { StatusBadge } from "@/components/StatusBadge";
import { UploadDropzone } from "@/components/UploadDropzone";
import { Alert, Card } from "@/components/ui";
import { api } from "@/lib/api";
import { validateFile } from "@/lib/files";
import { formatShortDate, isProcessing } from "@/lib/format";
import { setPendingFile } from "@/lib/pending-file";
import type { DropboxStatus, Meeting } from "@/lib/types";

export default function DashboardPage() {
  const router = useRouter();
  const [meetings, setMeetings] = useState<Meeting[] | null>(null);
  const [dropbox, setDropbox] = useState<DropboxStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setMeetings(await api.listMeetings());
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    load();
    api.dropboxStatus().then(setDropbox).catch(() => setDropbox(null));
  }, [load]);

  // 処理中の会議があれば定期的に更新する
  useEffect(() => {
    if (!meetings?.some(isProcessing)) return;
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, [meetings, load]);

  function onSelect(file: File) {
    const err = validateFile(file);
    setFileError(err);
    if (err) return;
    setPendingFile(file);
    router.push("/meetings/new");
  }

  return (
    <div className="space-y-6">
      {dropbox && !dropbox.connected && (
        <Alert kind="info">
          Dropboxが未連携です。議事録をDropboxに自動保存するには、
          <Link href="/settings" className="font-semibold underline">
            設定画面
          </Link>
          から連携してください。
        </Alert>
      )}

      <Card>
        <UploadDropzone file={null} onSelect={onSelect} />
        {fileError && (
          <div className="mt-3">
            <Alert>{fileError}</Alert>
          </div>
        )}
      </Card>

      <Card>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-base font-bold">最近の処理</h2>
          <Link href="/meetings/new" className="text-sm text-brand-600 hover:underline">
            ＋ 新しい会議
          </Link>
        </div>
        {error && <Alert>{error}</Alert>}
        {!error && meetings === null && <p className="text-sm text-gray-500">読み込み中…</p>}
        {meetings?.length === 0 && <p className="text-sm text-gray-500">まだ会議データがありません。</p>}
        <ul className="divide-y divide-gray-100">
          {meetings?.map((m) => (
            <li key={m.id}>
              <Link href={`/meetings/${m.id}`} className="flex items-center justify-between gap-3 rounded px-2 py-3 hover:bg-gray-50">
                <span className="min-w-0">
                  <span className="mr-3 text-sm text-gray-500">{formatShortDate(m.meeting_datetime)}</span>
                  <span className="break-all text-sm font-semibold">{m.meeting_name}</span>
                </span>
                <StatusBadge meeting={m} />
              </Link>
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
}
