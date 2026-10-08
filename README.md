# AI議事録自動生成・クラウド保存システム（MVP）

会議の音声・動画・文字起こしファイルから、AIが議事録の**ベース資料**を作ります（要約・決定事項・TODO・担当者・期限・未決事項）。そのあと Word と PDF を作成し、Dropbox に保存します。
正式な議事録は、参加者が内容を確認してから作成する前提です。

```
ブラウザ（Next.js / Vercel）
  ├─ ログイン（Supabase Auth）
  ├─ 動画 → 音声抽出・圧縮（ffmpeg.wasm、映像は送信しない）
  ├─ Supabase Storage へ直接アップロード
  └─ FastAPI に処理開始を依頼し、進捗を2秒ごとに確認
FastAPI（Docker / Render 等）
  文字起こし（gpt-4o-transcribe）→ AI解析（構造化JSON）→ Word/PDF生成 → Dropbox保存
Supabase（PostgreSQL + RLS / Storage）
```

## 実装状況

| 機能 | 状態 |
|---|---|
| ログイン・アカウント登録 | 実装済み（Supabase Auth） |
| 会議データアップロード（音声・動画・TXT・VTT・SRT） | 実装済み |
| 音声文字起こし（10分単位に分割して25MB制限を回避） | 実装済み・**実APIでの確認はまだ** |
| AI解析（要約・議論・決定事項・TODO・担当者・期限・未決事項・次回確認事項） | 実装済み・**実APIでの確認はまだ** |
| Word / PDF 生成（日本語フォント埋め込み） | 実装済み・確認済み |
| Dropbox 保存（ユーザーごとの OAuth） | 実装済み・**実アカウントでの確認はまだ** |
| 処理状況表示・エラー表示・再試行（失敗したステップから再開） | 実装済み・確認済み |
| 会議履歴 | ダッシュボードの一覧で対応 |
| Zoom / Meet / Teams 連携、AI Bot 参加、通知 | **将来実装（未実装）** |

## ディレクトリ構成

```
frontend/    Next.js（App Router, TypeScript, Tailwind CSS）
backend/     FastAPI（Python 3.12）。tests/ にテスト、fonts/ に PDF 用日本語フォント
supabase/    テーブル・RLS・Storage バケットを作る SQL
sample-data/ 架空の「営業部 定例会議」（TXT / VTT）と、期待される抽出結果
```

## セットアップ

### 1. Supabase
1. https://supabase.com でプロジェクトを作成
2. SQL Editor で `supabase/migrations/0001_init.sql` を実行
3. Authentication > Providers で Email を有効化（デモ用なら「Confirm email」をオフにすると、登録後すぐログインできます）
4. Project Settings > API から次の値を控える
   - Project URL
   - anon（publishable）キー → フロントエンド用
   - service_role（secret）キー → バックエンド用（**絶対にフロントエンドに置かない**）

### 2. OpenAI
API キーを発行します。モデルは `.env` の `OPENAI_TRANSCRIBE_MODEL` と `OPENAI_ANALYSIS_MODEL` で変更できます。

### 3. Dropbox
1. https://www.dropbox.com/developers/apps で「Create app」を選ぶ
   - API：Scoped access ／ アクセス種別：Full Dropbox（`/AI議事録` フォルダを作るため）
2. Permissions タブで `files.content.write`、`files.content.read`、`files.metadata.read`、`account_info.read` にチェックを入れて Submit
3. Settings タブの Redirect URIs に `DROPBOX_REDIRECT_URI` と同じ URL を登録（ローカルなら `http://localhost:8000/api/dropbox/callback`）
4. App key と App secret を控える
   - 開発中（Development）のアプリは、連携できるユーザー数に上限があります。社内で広く使う場合は Production 申請が必要です

### 4. バックエンド（FastAPI）
```bash
cd backend
cp .env.example .env   # 値を記入する
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
# 暗号化キーを作り、.env の TOKEN_ENCRYPTION_KEY に貼る
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
uvicorn app.main:app --reload --port 8000
```
ffmpeg が必要です（Mac：`brew install ffmpeg`）。Docker を使う場合は、リポジトリ直下で `docker compose up --build` を実行します。

### 5. フロントエンド（Next.js）
```bash
cd frontend
cp .env.example .env.local   # 値を記入する
npm install
npm run dev   # http://localhost:3000
```

### 6. テスト
```bash
cd backend && pytest                       # API・パイプライン・文字起こし整形・Word/PDF生成
cd frontend && npm run lint && npm run build
```

## デプロイ（予定）
- **バックエンド**：Render の Web Service（Docker）。Root Directory を `backend` にし、環境変数は `.env.example` の項目を設定します。無料プランはアクセスがないと停止し、起動に数十秒かかるので、面談前に `/health` を開いて起こしておきます
- **フロントエンド**：Vercel。Root Directory を `frontend` にし、`NEXT_PUBLIC_*` の3つを設定します
- 本番 URL に合わせて `FRONTEND_URL`、`CORS_ORIGINS`、`DROPBOX_REDIRECT_URI`（Dropbox アプリ側にも登録）を変更します

## 面談デモ手順
1. ログインする
2. 設定画面で Dropbox を連携する（事前に済ませておく）
3. ダッシュボードに `sample-data/eigyo_teirei_2026-10-08.vtt` をドラッグ＆ドロップする
4. 会議名「営業部 定例会議」、参加者「山田・佐藤・田中」を入れて「議事録を生成」を押す
5. 処理状況画面で、ファイル受付 → 文字起こしデータ読込 → AI解析 → Word/PDF生成 → Dropbox保存 と進む様子を見せる
6. 結果画面で決定事項と TODO（担当者・期限）を見せる。期限が明確でないものは「会議中に明確な指定なし」になり、AI が日付を創作しないことを説明する
7. Word と PDF をダウンロードし、Dropbox の `/AI議事録/2026/10月/2026-10-08_営業部 定例会議/` を開いて見せる
8. 将来は Zoom・Google Meet・Teams の録画や文字起こし API とつなぐことで、会議終了後の処理まで自動化できる、と説明する

期待される抽出結果は `sample-data/expected_minutes.json` にあります（STEP 8 で実際の AI 出力と比べます）。

## セキュリティ上の注意
- API キーはすべて環境変数で管理し、ブラウザに渡すのは Supabase の anon キーだけです
- 他のユーザーの会議は API で 404 になり、DB は RLS で本人の行しか読めません
- Dropbox のリフレッシュトークンは暗号化して保存し、ブラウザからは読めません
- アップロードした元ファイルは、文字起こしが終わると削除します
- ログには会議 ID とエラーの種類だけを出し、会議内容は出しません
- 実運用の前に、OpenAI のデータ利用ポリシー（API に送ったデータの扱い・保存期間）と社内のセキュリティポリシーを確認してください。MVP ではダミーデータだけを使います
