-- Portable work plane; no household data or changes to existing read surfaces.
-- Server-only APIs. Actor labels are provenance, NEVER authenticated identity.
create schema life_ops;
revoke all on schema life_ops from public, anon, authenticated;
grant usage on schema life_ops to service_role;

create table life_ops.boards (
  id uuid primary key default gen_random_uuid(),
  board_key text not null unique check (length(btrim(board_key)) between 1 and 120),
  title text not null check (length(btrim(title)) between 1 and 300),
  enabled boolean not null default true,
  created_at timestamptz not null default now()
);

create table life_ops.work_items (
  id uuid primary key default gen_random_uuid(),
  board_id uuid not null references life_ops.boards(id),
  item_key text not null check (length(btrim(item_key)) between 1 and 500),
  title text not null check (length(btrim(title)) between 1 and 300),
  description text not null default '' check (length(description) <= 12000),
  domains text[] not null default '{}',
  source_ref text not null check (length(btrim(source_ref)) between 1 and 2000),
  proposed_by text not null check (length(btrim(proposed_by)) between 1 and 120),
  state text not null default 'proposed' check
    (state in ('proposed','ready','researching','blocked','review','scheduled','done','dismissed')),
  confidence numeric check (confidence between 0 and 1),
  due_at timestamptz,
  not_before timestamptz,
  snoozed_until timestamptz,
  decision_ref text,
  outcome_ref text,
  lease_token uuid,
  leased_by text,
  lease_until timestamptz,
  version bigint not null default 1,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (board_id,item_key),
  unique (board_id,id),
  check ((lease_token is null and leased_by is null and lease_until is null)
      or (lease_token is not null and leased_by is not null and lease_until is not null)),
  check (state <> 'done' or (nullif(btrim(decision_ref),'') is not null
                           and nullif(btrim(outcome_ref),'') is not null))
);
create index work_due on life_ops.work_items(board_id,due_at,id)
  where state not in ('done','dismissed');
create index work_lease on life_ops.work_items(board_id,lease_until)
  where lease_token is not null;

-- Opaque references reuse existing evidence/people/events/assets in their own stores.
create table life_ops.item_links (
  id uuid primary key default gen_random_uuid(),
  board_id uuid not null,
  item_id uuid not null,
  relation text not null check (relation in
    ('evidence','related','prepares_for','reminder_for','possible_match','solution','outcome')),
  source_store text not null check (length(btrim(source_store)) between 1 and 120),
  source_kind text not null check (length(btrim(source_kind)) between 1 and 120),
  source_key text not null check (length(btrim(source_key)) between 1 and 2000),
  evidence_ref text not null check (length(btrim(evidence_ref)) between 1 and 2000),
  observed_at timestamptz not null,
  created_at timestamptz not null default now(),
  foreign key(board_id,item_id) references life_ops.work_items(board_id,id),
  unique(item_id,relation,source_store,source_kind,source_key)
);
create index item_links_board on life_ops.item_links(board_id,item_id);
create index item_links_source on life_ops.item_links(source_store,source_kind,source_key);

create table life_ops.dependencies (
  board_id uuid not null,
  item_id uuid not null,
  requires_id uuid not null,
  primary key(item_id,requires_id),
  foreign key(board_id,item_id) references life_ops.work_items(board_id,id),
  foreign key(board_id,requires_id) references life_ops.work_items(board_id,id),
  check(item_id <> requires_id)
);
create index dependencies_required on life_ops.dependencies(requires_id);

create table life_ops.activity (
  id bigint generated always as identity primary key,
  board_id uuid not null references life_ops.boards(id),
  item_id uuid,
  actor_ref text not null,
  event_kind text not null,
  evidence_ref text,
  detail jsonb not null default '{}' check (jsonb_typeof(detail)='object'),
  recorded_at timestamptz not null default clock_timestamp(),
  foreign key(board_id,item_id) references life_ops.work_items(board_id,id)
);
create index activity_board on life_ops.activity(board_id,id);
create index activity_item on life_ops.activity(item_id,id);

-- Signals contain permitted matching keys and source locators, not raw private records.
create table life_ops.signals (
  id bigint generated always as identity primary key,
  board_id uuid not null references life_ops.boards(id),
  signal_key text not null check (length(btrim(signal_key)) between 1 and 500),
  kind text not null check (length(btrim(kind)) between 1 and 120),
  match_keys text[] not null default '{}',
  evidence_ref text not null check (length(btrim(evidence_ref)) between 1 and 2000),
  observed_at timestamptz not null,
  valid_until timestamptz,
  actor_ref text not null,
  recorded_at timestamptz not null default clock_timestamp(),
  unique(board_id,signal_key),
  check(cardinality(match_keys) <= 50),
  check(valid_until is null or valid_until >= observed_at)
);
create index signals_board on life_ops.signals(board_id,id);
create index signals_kind on life_ops.signals(board_id,kind,id);
create index signals_matching on life_ops.signals using gin(match_keys);

create table life_ops.routines (
  id uuid primary key default gen_random_uuid(),
  board_id uuid not null references life_ops.boards(id),
  routine_key text not null,
  title text not null check (length(btrim(title)) between 1 and 300),
  description text not null default '',
  evidence_ref text not null check (length(btrim(evidence_ref)) between 1 and 2000),
  domains text[] not null default '{}',
  cadence text not null check(cadence in ('interval','annual')),
  interval_days integer check(interval_days between 1 and 3660),
  month integer check(month between 1 and 12),
  day integer check(day between 1 and 31),
  timezone text not null default 'UTC',
  next_due_at timestamptz not null,
  last_generated_at timestamptz,
  enabled boolean not null default false,
  unique(board_id,routine_key),
  check((cadence='interval' and interval_days is not null and month is null and day is null)
     or (cadence='annual' and interval_days is null and month is not null and day is not null))
);
create index routines_due on life_ops.routines(next_due_at,board_id) where enabled;

create table life_ops.checkins (
  id uuid primary key default gen_random_uuid(),
  board_id uuid not null references life_ops.boards(id),
  agent_ref text not null,
  evidence_ref text not null,
  after_signal bigint not null,
  through_signal bigint not null,
  signal_count integer not null,
  item_count integer not null,
  recorded_at timestamptz not null default clock_timestamp(),
  check(after_signal >= 0 and through_signal >= after_signal)
);
create index checkins_board on life_ops.checkins(board_id,recorded_at desc);

create function life_ops.append_only() returns trigger language plpgsql
security invoker set search_path='' as $$
begin raise exception 'life_ops: append-only record' using errcode='55000'; end $$;

create function life_ops.guard_board() returns trigger language plpgsql
security invoker set search_path='' as $$
begin
  if current_user not in ('postgres','supabase_admin') and new is distinct from old then
    raise exception 'life_ops: board policy requires administrator' using errcode='42501';
  end if;
  return new;
end $$;
create trigger guard_board before update on life_ops.boards
for each row execute function life_ops.guard_board();

create function life_ops.serialize_signal() returns trigger language plpgsql
security invoker set search_path='' as $$
begin
  perform 1 from life_ops.boards where id=new.board_id and enabled for update;
  if not found then raise exception 'life_ops: inactive board' using errcode='55000'; end if;
  if exists(select 1 from unnest(new.match_keys) k
    where k is null or length(btrim(k)) not between 1 and 300) then
    raise exception 'life_ops: invalid matching keys' using errcode='22023'; end if;
  return new;
end $$;
create trigger serialize_signal before insert on life_ops.signals
for each row execute function life_ops.serialize_signal();

create function life_ops.guard_work() returns trigger language plpgsql
security invoker set search_path='' as $$
begin
  if tg_op='DELETE' then
    raise exception 'life_ops: dismiss work instead of deleting' using errcode='55000';
  end if;
  if tg_op='INSERT' then
    if new.state <> 'proposed' or new.decision_ref is not null or new.outcome_ref is not null
       or new.lease_token is not null then
      raise exception 'life_ops: new work must be an unaccepted proposal' using errcode='42501';
    end if;
  else
    if (to_jsonb(new) - array['state','snoozed_until','decision_ref','outcome_ref',
       'lease_token','leased_by','lease_until','version','updated_at']) is distinct from
       (to_jsonb(old) - array['state','snoozed_until','decision_ref','outcome_ref',
       'lease_token','leased_by','lease_until','version','updated_at']) then
      raise exception 'life_ops: source proposal is immutable; submit a correction' using errcode='55000';
    end if;
    if current_user not in ('postgres','supabase_admin') and (
       new.decision_ref is distinct from old.decision_ref or
       new.outcome_ref is distinct from old.outcome_ref or
       (new.state is distinct from old.state and not
        ((old.state='ready' and new.state='researching') or
         (old.state='researching' and new.state in ('review','blocked','ready')) or
         (old.state='blocked' and new.state='review')))) then
      raise exception 'life_ops: human acceptance requires administrative decision path' using errcode='42501';
    end if;
    new.version := old.version+1;
    new.updated_at := clock_timestamp();
  end if;
  return new;
end $$;

create function life_ops.log_work() returns trigger language plpgsql
security invoker set search_path='' as $$
begin
  insert into life_ops.activity(board_id,item_id,actor_ref,event_kind,evidence_ref,detail)
  values(new.board_id,new.id,current_user,
    case when tg_op='INSERT' then 'proposed' else 'work_changed' end,
    coalesce(new.outcome_ref,new.decision_ref,new.source_ref),
    jsonb_build_object('state',new.state,'version',new.version,
      'proposed_by',new.proposed_by,'leased_by',new.leased_by));
  return new;
end $$;
create trigger guard_work before insert or update or delete on life_ops.work_items
for each row execute function life_ops.guard_work();
create trigger log_work after insert or update on life_ops.work_items
for each row execute function life_ops.log_work();

create function life_ops.guard_dependency() returns trigger language plpgsql
security invoker set search_path='' as $$
begin
  -- Serializes graph edits within a board; prevents concurrent cycle creation.
  perform 1 from life_ops.boards where id=new.board_id for update;
  if exists(with recursive chain(id) as (
    select new.requires_id union
    select d.requires_id from life_ops.dependencies d join chain c on d.item_id=c.id
    where d.board_id=new.board_id
  ) select 1 from chain where id=new.item_id) then
    raise exception 'life_ops: dependency cycle' using errcode='23514';
  end if;
  return new;
end $$;
create trigger guard_dependency before insert or update on life_ops.dependencies
for each row execute function life_ops.guard_dependency();

create function public.life_propose_work_v1(p_board_key text,p_item_key text,p_title text,
  p_source_ref text,p_actor_ref text,p_description text default '',p_domains text[] default '{}',
  p_due_at timestamptz default null,p_not_before timestamptz default null,
  p_confidence numeric default null) returns uuid language plpgsql
security invoker set search_path='' as $$
declare b uuid; w life_ops.work_items; proposed uuid;
begin
  select id into strict b from life_ops.boards where board_key=p_board_key and enabled;
  insert into life_ops.work_items(board_id,item_key,title,description,domains,source_ref,
    proposed_by,due_at,not_before,confidence)
  values(b,p_item_key,p_title,p_description,p_domains,p_source_ref,p_actor_ref,
    p_due_at,p_not_before,p_confidence)
  on conflict(board_id,item_key) do nothing returning id into proposed;
  if proposed is not null then return proposed; end if;
  select * into strict w from life_ops.work_items where board_id=b and item_key=p_item_key;
  if row(w.title,w.description,w.domains,w.source_ref,w.proposed_by,w.due_at,w.not_before,w.confidence)
     is distinct from row(p_title,p_description,p_domains,p_source_ref,p_actor_ref,p_due_at,p_not_before,p_confidence) then
    raise exception 'life_ops: idempotency key reused with different proposal' using errcode='22023';
  end if;
  return w.id;
end $$;

create function public.life_record_signal_v1(p_board_key text,p_signal_key text,p_kind text,
  p_match_keys text[],p_evidence_ref text,p_observed_at timestamptz,p_actor_ref text,
  p_valid_until timestamptz default null) returns bigint language plpgsql
security invoker set search_path='' as $$
declare b uuid; r life_ops.signals; new_id bigint; keys text[];
begin
  select id into strict b from life_ops.boards where board_key=p_board_key and enabled;
  if p_actor_ref is null or length(btrim(p_actor_ref)) not between 1 and 120 then
    raise exception 'life_ops: actor reference required' using errcode='22023'; end if;
  if p_match_keys is null or exists(select 1 from unnest(p_match_keys) k
    where k is null or length(btrim(k)) not between 1 and 300) then
    raise exception 'life_ops: invalid matching keys' using errcode='22023'; end if;
  select coalesce(array_agg(distinct btrim(k) order by btrim(k)),'{}') into keys
    from unnest(p_match_keys) k;
  -- A per-board transaction lock makes incremental signal cursors commit-order safe.
  perform 1 from life_ops.boards where id=b for update;
  insert into life_ops.signals(board_id,signal_key,kind,match_keys,evidence_ref,
    observed_at,valid_until,actor_ref)
  values(b,p_signal_key,p_kind,keys,p_evidence_ref,p_observed_at,p_valid_until,p_actor_ref)
  on conflict(board_id,signal_key) do nothing returning id into new_id;
  if new_id is not null then return new_id; end if;
  select * into strict r from life_ops.signals where board_id=b and signal_key=p_signal_key;
  if row(r.kind,r.match_keys,r.evidence_ref,r.observed_at,r.valid_until,r.actor_ref)
    is distinct from row(p_kind,keys,p_evidence_ref,p_observed_at,p_valid_until,p_actor_ref) then
    raise exception 'life_ops: idempotency key reused with different signal' using errcode='22023';
  end if;
  return r.id;
end $$;

create function public.life_claim_work_v1(p_item_id uuid,p_actor_ref text,
  p_lease_seconds integer default 300) returns jsonb language plpgsql
security invoker set search_path='' as $$
declare w life_ops.work_items; token uuid:=gen_random_uuid();
begin
  if p_lease_seconds is null or p_lease_seconds not between 30 and 900 or
     p_actor_ref is null or length(btrim(p_actor_ref)) not between 1 and 120 then
    raise exception 'life_ops: invalid lease request' using errcode='22023'; end if;
  select * into strict w from life_ops.work_items where id=p_item_id for update;
  if not exists(select 1 from life_ops.boards where id=w.board_id and enabled) or
     w.state not in ('ready','researching') or
     coalesce(w.not_before,'-infinity') > clock_timestamp() or
     coalesce(w.snoozed_until,'-infinity') > clock_timestamp() or
     (w.lease_until is not null and w.lease_until > clock_timestamp()) or
     exists(select 1 from life_ops.dependencies d join life_ops.work_items r on r.id=d.requires_id
            where d.item_id=w.id and r.state <> 'done') then
    raise exception 'life_ops: work not claimable' using errcode='55000'; end if;
  update life_ops.work_items set state='researching',lease_token=token,
    leased_by=p_actor_ref,lease_until=clock_timestamp()+make_interval(secs=>p_lease_seconds)
    where id=w.id returning * into w;
  return jsonb_build_object('item_id',w.id,'lease_token',token,'lease_until',w.lease_until,
    'version',w.version,'authority','research_only');
end $$;

create function public.life_submit_work_v1(p_item_id uuid,p_lease_token uuid,
  p_actor_ref text,p_finding_ref text,p_blocked boolean default false) returns void
language plpgsql security invoker set search_path='' as $$
declare w life_ops.work_items;
begin
  select * into strict w from life_ops.work_items where id=p_item_id for update;
  if p_lease_token is null or w.lease_token is distinct from p_lease_token or
     p_actor_ref is distinct from w.leased_by or w.lease_until <= clock_timestamp() or
     w.state <> 'researching' or
     not exists(select 1 from life_ops.boards where id=w.board_id and enabled) then
    raise exception 'life_ops: stale or invalid lease' using errcode='55000'; end if;
  if p_finding_ref is null or length(btrim(p_finding_ref)) not between 1 and 2000 then
    raise exception 'life_ops: finding evidence required' using errcode='22023'; end if;
  insert into life_ops.activity(board_id,item_id,actor_ref,event_kind,evidence_ref)
    values(w.board_id,w.id,p_actor_ref,case when p_blocked then 'blocker' else 'finding' end,p_finding_ref);
  update life_ops.work_items set state=case when p_blocked then 'blocked' else 'review' end,
    lease_token=null,leased_by=null,lease_until=null where id=w.id;
end $$;

-- Deliberately NOT granted to service_role. Human broker integration is a separate gate.
create function public.life_decide_work_v1(p_item_id uuid,p_expected_version bigint,
  p_state text,p_decision_ref text,p_outcome_ref text default null) returns void
language plpgsql security invoker set search_path='' as $$
declare w life_ops.work_items;
begin
  if current_user not in ('postgres','supabase_admin') then
    raise exception 'life_ops: administrative decision required' using errcode='42501'; end if;
  if p_state is null or p_state not in ('ready','scheduled','done','dismissed') or
     p_decision_ref is null or length(btrim(p_decision_ref)) not between 1 and 2000 or
     (p_state='done' and (p_outcome_ref is null or length(btrim(p_outcome_ref)) not between 1 and 2000)) then
    raise exception 'life_ops: decision and outcome evidence required' using errcode='22023'; end if;
  select * into strict w from life_ops.work_items where id=p_item_id for update;
  if w.version is distinct from p_expected_version then
    raise exception 'life_ops: stale work version' using errcode='40001'; end if;
  if w.state in ('done','dismissed') then
    raise exception 'life_ops: terminal work requires a new correction proposal' using errcode='55000'; end if;
  update life_ops.work_items set state=p_state,decision_ref=p_decision_ref,
    outcome_ref=p_outcome_ref,lease_token=null,leased_by=null,lease_until=null where id=w.id;
end $$;

create function public.life_check_in_v1(p_board_key text,p_agent_ref text,
  p_evidence_ref text,p_after_signal bigint default 0,p_limit integer default 20) returns jsonb
language plpgsql security invoker set search_path='' as $$
declare b uuid; sig jsonb; work jsonb; next_id bigint; check_id uuid; more boolean;
begin
  if p_limit is null or p_limit not between 1 and 50 or p_after_signal is null or p_after_signal < 0 or
     p_agent_ref is null or length(btrim(p_agent_ref)) not between 1 and 120 or
     p_evidence_ref is null or length(btrim(p_evidence_ref)) not between 1 and 2000 then
    raise exception 'life_ops: invalid bounded check-in' using errcode='22023'; end if;
  select id into strict b from life_ops.boards where board_key=p_board_key and enabled;
  -- Takes the same lock as signal writers so no uncommitted low ID can be skipped.
  perform 1 from life_ops.boards where id=b for update;
  if p_after_signal > coalesce((select max(id) from life_ops.signals where board_id=b),0) then
    raise exception 'life_ops: cursor beyond board history' using errcode='22023'; end if;
  select coalesce(jsonb_agg(to_jsonb(s) order by s.id),'[]'),coalesce(max(s.id),p_after_signal)
    into sig,next_id from (select id,kind,match_keys,evidence_ref,observed_at,valid_until
      from life_ops.signals where board_id=b and id>p_after_signal order by id limit p_limit)s;
  select exists(select 1 from life_ops.signals where board_id=b and id>next_id) into more;
  select coalesce(jsonb_agg(to_jsonb(w) order by w.due_at nulls last,w.created_at,w.id),'[]') into work
    from (select id,title,state,domains,source_ref,due_at,not_before,version,created_at
      from life_ops.work_items where board_id=b and state not in ('done','dismissed')
      and coalesce(snoozed_until,'-infinity') <= clock_timestamp()
      order by due_at nulls last,created_at,id limit p_limit)w;
  insert into life_ops.checkins(board_id,agent_ref,evidence_ref,after_signal,through_signal,signal_count,item_count)
    values(b,p_agent_ref,p_evidence_ref,p_after_signal,next_id,jsonb_array_length(sig),jsonb_array_length(work))
    returning id into check_id;
  return jsonb_build_object('contract','life-check-in/1','checkin_id',check_id,
    'signals',sig,'next_signal_cursor',next_id,'has_more_signals',more,'work',work,
    'work_total',(select count(*) from life_ops.work_items where board_id=b
                  and state not in ('done','dismissed') and coalesce(snoozed_until,'-infinity')<=clock_timestamp()),
    'coverage','This board only; external sources and other stores have not been checked.',
    'authority','Suggestions and research only; no external execution.');
end $$;

create function public.life_materialize_routines_v1(p_board_key text,p_as_of timestamptz default now(),
  p_limit integer default 20) returns integer language plpgsql
security invoker set search_path='' as $$
declare b uuid; r life_ops.routines; next_due timestamptz; local_day date; y integer;
  n integer:=0; work_id uuid; d integer;
begin
  if p_limit is null or p_limit not between 1 and 50 or p_as_of is null then
    raise exception 'life_ops: invalid routine window' using errcode='22023'; end if;
  select id into strict b from life_ops.boards where board_key=p_board_key and enabled;
  for r in select * from life_ops.routines where board_id=b and enabled and next_due_at<=p_as_of
    order by next_due_at,id limit p_limit for update skip locked loop
    work_id:=null;
    select id into work_id from life_ops.work_items where board_id=b
      and item_key like 'routine:'||r.id||':%' and state not in ('done','dismissed') limit 1;
    if work_id is null then
      work_id := public.life_propose_work_v1(p_board_key,
        'routine:'||r.id||':'||to_char(r.next_due_at at time zone 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US'),
        r.title,r.evidence_ref,'routine-materializer',r.description,r.domains,r.next_due_at);
      n:=n+1;
    end if;
    -- Coalesce missed occurrences into one suggestion; never flood a daily backlog.
    if r.cadence='interval' then
      next_due := r.next_due_at + make_interval(days=>
        ((floor(extract(epoch from (p_as_of-r.next_due_at))/(r.interval_days*86400.0))+1)*r.interval_days)::integer);
    else
      local_day := (p_as_of at time zone r.timezone)::date;
      y := extract(year from local_day)::integer;
      d := least(r.day,extract(day from (make_date(y,r.month,1)+interval '1 month - 1 day'))::integer);
      next_due := make_date(y,r.month,d)::timestamp at time zone r.timezone;
      if next_due<=p_as_of then
        y:=y+1;
        d:=least(r.day,extract(day from (make_date(y,r.month,1)+interval '1 month - 1 day'))::integer);
        next_due:=make_date(y,r.month,d)::timestamp at time zone r.timezone;
      end if;
    end if;
    update life_ops.routines set next_due_at=next_due,last_generated_at=p_as_of where id=r.id;
  end loop;
  return n;
end $$;

create function public.life_match_recall_signals_v1(p_board_key text,p_actor_ref text,
  p_as_of timestamptz default now(),p_limit integer default 20) returns integer
language plpgsql security invoker set search_path='' as $$
declare b uuid; pair record; work_id uuid; n integer:=0;
begin
  if p_limit is null or p_limit not between 1 and 50 or p_as_of is null or
     p_actor_ref is null or length(btrim(p_actor_ref)) not between 1 and 120 then
    raise exception 'life_ops: invalid recall matching request' using errcode='22023'; end if;
  select id into strict b from life_ops.boards where board_key=p_board_key and enabled;
  for pair in select p.id as purchase_id,r.id as recall_id,p.evidence_ref as purchase_ref,
    r.evidence_ref as recall_ref,p.observed_at as purchase_at,r.observed_at as recall_at
    from life_ops.signals p join life_ops.signals r on r.board_id=p.board_id
      and r.kind='recall' and p.match_keys && r.match_keys
    where p.board_id=b and p.kind='purchase' and p.observed_at<=p_as_of and r.observed_at<=p_as_of
      and (p.valid_until is null or p.valid_until>=p_as_of)
      and (r.valid_until is null or r.valid_until>=p_as_of)
      and not exists(select 1 from life_ops.work_items w where w.board_id=b and
        w.item_key='recall:'||p.id||':'||r.id)
    order by r.id,p.id limit p_limit loop
    work_id:=public.life_propose_work_v1(p_board_key,'recall:'||pair.purchase_id||':'||pair.recall_id,
      'Check a possible product recall match',pair.recall_ref,p_actor_ref,
      'An exact supplied matching key overlaps a purchase and a recall. Verify product, dates, lot and possession; exposure is not confirmed.',
      array['purchases','safety']);
    insert into life_ops.item_links(board_id,item_id,relation,source_store,source_kind,source_key,evidence_ref,observed_at)
      values(b,work_id,'possible_match','local','signal',pair.purchase_id::text,pair.purchase_ref,pair.purchase_at),
            (b,work_id,'possible_match','local','signal',pair.recall_id::text,pair.recall_ref,pair.recall_at)
      on conflict do nothing;
    n:=n+1;
  end loop;
  return n;
end $$;

-- All new tables fail closed. No principal-facing or browser grants are added.
do $$ declare t text; f record; begin
  foreach t in array array['boards','work_items','item_links','dependencies','activity','signals','routines','checkins'] loop
    execute format('alter table life_ops.%I enable row level security',t);
    execute format('revoke all on life_ops.%I from public, anon, authenticated, service_role',t);
    execute format('grant select on life_ops.%I to service_role',t);
  end loop;
  foreach t in array array['item_links','activity','signals','checkins'] loop
    execute format('create trigger append_only before update or delete on life_ops.%I for each row execute function life_ops.append_only()',t);
  end loop;
  for f in select p.oid::regprocedure as signature from pg_proc p join pg_namespace n on n.oid=p.pronamespace
    where n.nspname='life_ops' or (n.nspname='public' and p.proname in
    ('life_propose_work_v1','life_record_signal_v1','life_claim_work_v1','life_submit_work_v1',
     'life_decide_work_v1','life_check_in_v1','life_materialize_routines_v1','life_match_recall_signals_v1')) loop
    execute format('revoke all on function %s from public, anon, authenticated, service_role',f.signature);
    if f.signature::text not like '%life_decide_work_v1%' then
      execute format('grant execute on function %s to service_role',f.signature);
    end if;
  end loop;
end $$;
grant insert on life_ops.work_items,life_ops.item_links,life_ops.activity,life_ops.signals,life_ops.checkins to service_role;
grant update(state,snoozed_until,lease_token,leased_by,lease_until) on life_ops.work_items to service_role;
grant update(next_due_at,last_generated_at) on life_ops.routines to service_role;
-- Row locks require UPDATE privilege even when the row is not changed.
grant update(enabled) on life_ops.boards to service_role;
grant usage,select on all sequences in schema life_ops to service_role;
comment on schema life_ops is 'Server-only life-assistance work plane. No browser, household-user, or autonomous agent access is granted.';
