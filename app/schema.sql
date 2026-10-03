-- Run this once in Supabase: SQL Editor -> New query -> paste -> Run.
create table if not exists public.cruises (
  id              bigint generated always as identity primary key,
  title           text    not null,
  cruise_name     text    not null,
  nights          integer not null,
  banner          text    not null,
  offer           text    not null,
  departure_port  text    not null,
  locations       text    not null,
  price_inr       bigint  not null,
  price_text      text    not null,
  dates_count     integer not null,
  note            text    not null
);

-- Row Level Security on, with a public read-only policy.
alter table public.cruises enable row level security;

drop policy if exists "Public read access" on public.cruises;
create policy "Public read access"
  on public.cruises for select
  to anon, authenticated
  using (true);

-- Newer Supabase projects no longer grant table access automatically.
grant usage on schema public to anon, authenticated;
grant select on public.cruises to anon, authenticated;
