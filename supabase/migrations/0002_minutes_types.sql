-- 議事録を3種類（会議記録・会議の振り返り・日常の振り返り）に対応し、画面での編集内容を保存できるようにする
-- 0001_init.sql の後に SQL Editor で実行する

alter table public.meetings
  add column if not exists minutes_type text not null default 'record'
  check (minutes_type in ('record', 'review', 'daily'));

-- 項目は種類ごとに違うので、議事録の中身は data（jsonb）にまとめて保存する
alter table public.meeting_minutes
  add column if not exists minutes_type text not null default 'record'
    check (minutes_type in ('record', 'review', 'daily')),
  add column if not exists data jsonb not null default '{}'::jsonb,
  add column if not exists edited_at timestamptz,
  drop column if exists summary,
  drop column if exists discussion,
  drop column if exists decisions,
  drop column if exists todos,
  drop column if exists unresolved_items,
  drop column if exists next_actions;
