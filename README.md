# AI議事録自動生成・クラウド保存システム（MVP）

会議の録音（音声・動画）や文字起こしファイルから、AIが議事録の**ベース資料**を作ります（要約・決定事項・TODO・担当者・期限・未決事項）。そのあと Word と PDF を作成し、Dropbox に保存します。
正式な議事録は、参加者が内容を確認してから作成する前提です。
**利用料のかかる AI は使いません。** 文字起こしはサーバー内で動く Whisper、要約は Google Gemini API の無料枠（またはローカル AI）で行います。

```
ブラウザ（Next.js / Vercel）
  ├─ ログイン（Supabase Auth）
  ├─ 動画 → 音声抽出・圧縮（ffmpeg.wasm、映像は送信しない）
  ├─ Supabase Storage へ直接アップロード
  └─ FastAPI に処理開始を依頼し、進捗を2秒ごとに確認
FastAPI（Docker / Hugging Face Spaces・社内PC 等）
  文字起こし（faster-whisper・サーバー内）→ AI解析（Gemini 無料枠・構造化JSON）→ Word/PDF生成 → Dropbox保存
Supabase（PostgreSQL + RLS / Storage）
```

## 実装状況

| 機能 | 状態 |
|---|---|
| ログイン・アカウント登録 | 実装済み（Supabase Auth） |
| 会議データアップロード（音声・動画・TXT・VTT・SRT） | 実装済み |
| 音声文字起こし（faster-whisper、無料・音声を外部に送らない） | 実装済み・**実際の録音での確認はまだ**（開発環境からモデルを取得できないため） |
| AI解析（Gemini 無料枠。Ollama のローカル AI にも切り替え可） | 実装済み・**実APIでの確認はまだ** |
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

### 2. AI（無料）
**文字起こし（Whisper）**：キーは不要です。初回にモデル（small は約 500MB）を自動でダウンロードします。Docker の場合はイメージ作成時に含めます。
`.env` の `WHISPER_MODEL` で精度と速さを選べます。GPU のない PC では、1 時間の録音に small で 20〜40 分ほどかかる見込みです（目安・未計測）。

| モデル | 精度 | 速さ（CPU） | メモリ |
|---|---|---|---|
| small（標準） | 実用レベル。専門用語や人名は誤りが出やすい | 速い | 約 1GB |
| medium | より正確 | small の約 2〜3 倍の時間 | 約 2GB |
| large-v3 | 最も正確 | とても遅い（GPU 推奨） | 約 4GB |

**AI解析（Gemini）**：https://aistudio.google.com/apikey で Google アカウントにログインし、「API キーを作成」で発行して `GEMINI_API_KEY` に設定します（クレジットカード不要）。
- 無料枠には 1 分・1 日あたりの回数上限があります。上限に達すると画面に「無料枠の利用上限」と表示されるので、時間をおいて再試行します
- **無料枠では、送った内容が Google のサービス改善に使われることがあります。** 機密の会議では使わず、有料枠に切り替えるか、次のローカル AI を使ってください

**AI解析（ローカル AI・任意）**：外部に一切送りたくない場合は、https://ollama.com をインストールして `ollama pull qwen2.5:7b` を実行し、`.env` を `ANALYSIS_PROVIDER=ollama` にします。GPU のない PC では 1 回の解析に数分〜十数分かかり、精度も Gemini より下がります。

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
ffmpeg が必要です（Mac：`brew install ffmpeg`、Windows：`winget install ffmpeg`）。Docker を使う場合は、リポジトリ直下で `docker compose up --build` を実行します。

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
- **バックエンド**：Whisper を動かすにはメモリが 2GB 以上必要なため、Render の無料プラン（512MB）では動きません。次のどちらかにします
  - **Hugging Face Spaces（無料・CPU 2コア／メモリ 16GB）**：Space を「Docker」で作成し、`backend/` の中身を置きます。Space の README 冒頭に `sdk: docker` と `app_port: 8000` を書き、Settings > Variables and secrets に `.env.example` の項目を登録します。しばらく使わないと停止し、起動に数分かかるので、面談前に `/health` を開いて起こしておきます
  - **社内の PC**：`docker compose up --build` で起動します。社外のブラウザから使う場合は、Cloudflare Tunnel などで公開します
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
- 音声はサーバー内の Whisper で文字起こしするので、外部の AI には送りません。Gemini に送るのは文字起こしのテキストです
- Gemini の無料枠では、送った内容が Google のサービス改善に使われることがあります。実運用の前に、Gemini API の利用規約と社内のセキュリティポリシーを確認してください。MVP ではダミーデータだけを使います
