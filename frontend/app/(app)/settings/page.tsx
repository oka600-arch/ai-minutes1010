"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { Alert, Button, Card } from "@/components/ui";
import { api } from "@/lib/api";
import type { DropboxStatus } from "@/lib/types";

const RESULT_MESSAGES: Record<string, { kind: "success" | "error"; text: string }> = {
  connected: { kind: "success", text: "Dropboxを連携しました。今後の議事録は自動でDropboxに保存されます。" },
  cancelled: { kind: "error", text: "Dropboxの連携がキャンセルされました。" },
  expired: { kind: "error", text: "連携の有効期限が切れました。もう一度お試しください。" },
  error: { kind: "error", text: "Dropboxの連携に失敗しました。もう一度お試しください。" },
};

function DropboxSettings() {
  const params = useSearchParams();
  const result = RESULT_MESSAGES[params.get("dropbox") ?? ""];
  const [status, setStatus] = useState<DropboxStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.dropboxStatus().then(setStatus).catch((e) => setError((e as Error).message));
  }, []);

  async function connect() {
    setBusy(true);
    setError(null);
    try {
      const { authorize_url } = await api.dropboxConnect();
      window.location.href = authorize_url;
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }

  async function disconnect() {
    if (!window.confirm("Dropboxとの連携を解除しますか？保存済みのファイルは削除されません。")) return;
    setBusy(true);
    setError(null);
    try {
      await api.dropboxDisconnect();
      setStatus(await api.dropboxStatus());
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <h1 className="mb-1 text-lg font-bold">Dropbox連携</h1>
      <p className="mb-4 text-sm text-gray-600">
        連携すると、生成した議事録（Word・PDF・文字起こし）が「/AI議事録/年/月/日付_会議名」フォルダに自動保存されます。
      </p>
      <div className="space-y-4">
        {result && <Alert kind={result.kind}>{result.text}</Alert>}
        {error && <Alert>{error}</Alert>}
        {status === null && !error && <p className="text-sm text-gray-500">読み込み中…</p>}
        {status && !status.configured && <Alert>サーバーにDropboxアプリの設定がありません。管理者に連絡してください。</Alert>}
        {status?.connected && (
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-sm">
              <span className="mr-2 inline-block rounded-full bg-green-50 px-2.5 py-0.5 text-xs font-semibold text-green-700">連携中</span>
              {status.email ?? "Dropboxアカウント"}
            </p>
            <Button variant="danger" onClick={disconnect} disabled={busy}>
              連携を解除
            </Button>
          </div>
        )}
        {status && !status.connected && status.configured && (
          <Button onClick={connect} disabled={busy}>
            Dropboxと連携する
          </Button>
        )}
      </div>
    </Card>
  );
}

export default function SettingsPage() {
  return (
    <Suspense fallback={<p className="text-sm text-gray-500">読み込み中…</p>}>
      <DropboxSettings />
    </Suspense>
  );
}
