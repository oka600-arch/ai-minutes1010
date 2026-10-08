// ダッシュボードで選んだファイルを、会議データ入力画面へ渡すための一時置き場（画面遷移の間だけ保持）
let pending: File | null = null;

export function setPendingFile(file: File | null): void {
  pending = file;
}

export function takePendingFile(): File | null {
  const f = pending;
  pending = null;
  return f;
}
