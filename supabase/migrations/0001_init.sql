-- AI議事録システム 初期スキーマ
-- Supabase の SQL Editor で実行するか、supabase db push で適用する。

-- ============================================================
-- profiles（auth.users と 1:1）
-- ============================================================
create table public.profiles (
  id uuid primary key references auth.users (id) on delete cascade,
  email text not null,
  name text not null default '',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- サインアップ時に profiles を自動作成する
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer set search_path = public
as $$
begin
  insert into public.profiles (id, email, name)
  values (new.id, new.email, coalesce(new.raw_user_meta_data ->> 'name', ''));
  return new;
end;
$$;

create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- ============================================================
-- meetings
-- ============================================================
create table public.meetings (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles (id) on delete cascade,
  meeting_name text not null,
  meeting_datetime timestamptz not null,
  meeting_tool text not null default 'other'
    check (meeting_tool in ('zoom', 'google_meet', 'teams', 'other')),
  input_type text not null
    check (input_type in ('audio', 'video', 'text')),
  source_file_name text,
  source_file_path text,
  status text not null default 'UPLOADED'
    check (status in (
      'UPLOADED', 'TRANSCRIBING', 'TRANSCRIBED', 'ANALYZING',
      'GENERATING', 'GENERATED', 'UPLOADING', 'COMPLETED', 'ERROR'
    )),
  error_step text,
  error_message text,
  dropbox_folder_path text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index meetings_user_id_created_at_idx on public.meetings (user_id, created_at desc);

-- ============================================================
-- participants
-- ============================================================
create table public.participants (
  id uuid primary key default gen_random_uuid(),
  meeting_id uuid not null references public.meetings (id) on delete cascade,
  name text not null,
  email text,
  created_at timestamptz not null default now()
);

create index participants_meeting_id_idx on public.participants (meeting_id);

-- ============================================================
-- transcripts
-- ============================================================
create table public.transcripts (
  id uuid primary key default gen_random_uuid(),
  meeting_id uuid not null unique references public.meetings (id) on delete cascade,
  source_format text not null check (source_format in ('audio', 'txt', 'vtt', 'srt')),
  file_path text,
  transcript_text text not null,
  created_at timestamptz not null default now()
);

-- ============================================================
-- meeting_minutes
-- ============================================================
create table public.meeting_minutes (
  id uuid primary key default gen_random_uuid(),
  meeting_id uuid not null unique references public.meetings (id) on delete cascade,
  summary text not null default '',
  discussion jsonb not null default '[]'::jsonb,
  decisions jsonb not null default '[]'::jsonb,
  todos jsonb not null default '[]'::jsonb,
  unresolved_items jsonb not null default '[]'::jsonb,
  next_actions jsonb not null default '[]'::jsonb,
  ai_model text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- ============================================================
-- files（生成物）
-- ============================================================
create table public.files (
  id uuid primary key default gen_random_uuid(),
  meeting_id uuid not null references public.meetings (id) on delete cascade,
  file_type text not null check (file_type in ('transcript', 'docx', 'pdf')),
  file_name text not null,
  file_path text not null,
  dropbox_path text,
  created_at timestamptz not null default now(),
  unique (meeting_id, file_type)
);

-- ============================================================
-- dropbox_connections（ブラウザからは読めない。FastAPI が service role で扱う）
-- ============================================================
create table public.dropbox_connections (
  user_id uuid primary key references public.profiles (id) on delete cascade,
  dropbox_account_id text not null,
  dropbox_email text,
  refresh_token_encrypted text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- Dropbox OAuth の state（CSRF 対策・PKCE verifier の一時保存）
create table public.dropbox_oauth_states (
  state text primary key,
  user_id uuid not null references public.profiles (id) on delete cascade,
  code_verifier text not null,
  created_at timestamptz not null default now()
);

-- ============================================================
-- updated_at 自動更新
-- ============================================================
create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

create trigger profiles_updated_at before update on public.profiles
  for each row execute function public.set_updated_at();
create trigger meetings_updated_at before update on public.meetings
  for each row execute function public.set_updated_at();
create trigger meeting_minutes_updated_at before update on public.meeting_minutes
  for each row execute function public.set_updated_at();
create trigger dropbox_connections_updated_at before update on public.dropbox_connections
  for each row execute function public.set_updated_at();

-- ============================================================
-- RLS：本人のデータのみ参照可能
-- 書き込みは FastAPI（service role）経由で行うため、ブラウザには参照権限のみ与える
-- ============================================================
alter table public.profiles enable row level security;
alter table public.meetings enable row level security;
alter table public.participants enable row level security;
alter table public.transcripts enable row level security;
alter table public.meeting_minutes enable row level security;
alter table public.files enable row level security;
alter table public.dropbox_connections enable row level security;
alter table public.dropbox_oauth_states enable row level security;
-- dropbox_connections / dropbox_oauth_states にはポリシーを作らない（= ブラウザから一切アクセス不可）

create policy "profiles: 本人のみ参照" on public.profiles
  for select using (id = auth.uid());

create policy "meetings: 本人のみ参照" on public.meetings
  for select using (user_id = auth.uid());

create policy "participants: 本人の会議のみ参照" on public.participants
  for select using (exists (
    select 1 from public.meetings m where m.id = meeting_id and m.user_id = auth.uid()
  ));

create policy "transcripts: 本人の会議のみ参照" on public.transcripts
  for select using (exists (
    select 1 from public.meetings m where m.id = meeting_id and m.user_id = auth.uid()
  ));

create policy "meeting_minutes: 本人の会議のみ参照" on public.meeting_minutes
  for select using (exists (
    select 1 from public.meetings m where m.id = meeting_id and m.user_id = auth.uid()
  ));

create policy "files: 本人の会議のみ参照" on public.files
  for select using (exists (
    select 1 from public.meetings m where m.id = meeting_id and m.user_id = auth.uid()
  ));

-- ============================================================
-- Storage バケット（非公開）
-- uploads: 元ファイル（{user_id}/{meeting_id}/source.*）
-- outputs: 生成物（{user_id}/{meeting_id}/meeting_minutes.docx 等）
-- ============================================================
insert into storage.buckets (id, name, public, file_size_limit)
values
  ('uploads', 'uploads', false, 104857600),
  ('outputs', 'outputs', false, 52428800)
on conflict (id) do nothing;

-- ブラウザからは、FastAPI が発行した署名付き URL でのみアップロード・ダウンロードする。
-- そのため storage.objects に追加のポリシーは作らない。
