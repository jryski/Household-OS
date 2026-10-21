-- Optional human review adapter for existing life_ops work, not worker tools.
-- No grants are seeded/enabled. Keep life_review outside exposed API schemas.
-- Human OAuth clients must be newly provisioned and never enter model custody.
create role life_review_executor nologin noinherit nosuperuser nocreatedb
  nocreaterole noreplication nobypassrls;
create schema life_review;
revoke all on schema life_review from public,anon,authenticated,service_role,life_runtime_executor;
grant usage on schema life_review to authenticated,life_review_executor;
grant usage on schema life_ops,life_runtime to life_review_executor;

create table life_review.human_grants (
  id uuid primary key default gen_random_uuid(),
  auth_subject uuid not null,
  upstream_client_id uuid not null,
  board_id uuid not null references life_ops.boards(id),
  actor_ref text not null check (length(btrim(actor_ref)) between 1 and 120),
  operations text[] not null check (cardinality(operations) between 1 and 3
    and operations <@ array['queue','item','decide']::text[]
    and array_position(operations,null) is null),
  enabled boolean not null default false,
  valid_from timestamptz not null default now(),
  valid_until timestamptz not null,
  revoked_at timestamptz,
  evidence_ref text not null check (length(btrim(evidence_ref)) between 1 and 2000),
  check (valid_until>valid_from)
);
create index human_grants_subject_client on life_review.human_grants(auth_subject,upstream_client_id,board_id);
create index human_grants_board on life_review.human_grants(board_id);
alter table life_review.human_grants enable row level security;
revoke all on life_review.human_grants from public,anon,authenticated,service_role,life_review_executor,life_runtime_executor;
grant select,update(revoked_at) on life_review.human_grants to life_review_executor;
create policy review_read_grants on life_review.human_grants for select to life_review_executor using (true);
create policy review_lock_grants on life_review.human_grants for update to life_review_executor using (true) with check (true);

create function life_review.canonical_client(p_client text) returns uuid
language plpgsql immutable security invoker set search_path='' as $$
begin
  return p_client::uuid;
exception when invalid_text_representation then return null;
end $$;

-- The two admin-only guards serialize client classification. READ COMMITTED is
-- required so the cross-table check takes a fresh snapshot after a lock wait.
-- Retain disabled/expired/revoked rows and immutable client IDs: revoke/create,
-- never delete/reclassify a client whose token may still exist in worker custody.
create function life_review.guard_human_grant() returns trigger language plpgsql
security invoker set search_path='' as $$
begin
  if current_user not in ('postgres','supabase_admin') then
    raise exception 'life review: administrative configuration required' using errcode='42501'; end if;
  if current_setting('transaction_isolation')<>'read committed' then
    raise exception 'life review: configuration requires READ COMMITTED' using errcode='22023'; end if;
  if tg_op='DELETE' then
    raise exception 'life review: revoke grants instead of deleting client history' using errcode='55000'; end if;
  if tg_op='UPDATE' and new.upstream_client_id is distinct from old.upstream_client_id then
    raise exception 'life review: grant client is immutable; revoke and create' using errcode='55000'; end if;
  perform pg_advisory_xact_lock(hashtext('life-client-purpose/1'),hashtext(new.upstream_client_id::text));
  if exists(select 1 from life_runtime.principal_grants
    where life_review.canonical_client(upstream_client_id)=new.upstream_client_id) then
    raise exception 'life review: client is reserved for worker custody' using errcode='23514'; end if;
  return new;
end $$;
create trigger guard_human_grant before insert or update or delete on life_review.human_grants
for each row execute function life_review.guard_human_grant();

create function life_review.retain_client_history() returns trigger language plpgsql
security invoker set search_path='' as $$
begin
  raise exception 'life review: revoke grants instead of truncating client history' using errcode='55000';
end $$;
create trigger retain_human_clients before truncate on life_review.human_grants
for each statement execute function life_review.retain_client_history();
create trigger retain_worker_clients before truncate on life_runtime.principal_grants
for each statement execute function life_review.retain_client_history();

create or replace function life_runtime.guard_grant() returns trigger language plpgsql
security invoker set search_path='' as $$
declare client uuid;
begin
  if current_user not in ('postgres','supabase_admin') then
    raise exception 'life runtime: administrative configuration required' using errcode='42501'; end if;
  if current_setting('transaction_isolation')<>'read committed' then
    raise exception 'life runtime: configuration requires READ COMMITTED' using errcode='22023'; end if;
  if tg_op='DELETE' then
    raise exception 'life runtime: revoke grants instead of deleting client history' using errcode='55000'; end if;
  if tg_op='UPDATE' and new.upstream_client_id is distinct from old.upstream_client_id then
    raise exception 'life runtime: grant client is immutable; revoke and create' using errcode='55000'; end if;
  client:=life_review.canonical_client(new.upstream_client_id);
  if client is not null then
    perform pg_advisory_xact_lock(hashtext('life-client-purpose/1'),hashtext(client::text));
    if exists(select 1 from life_review.human_grants where upstream_client_id=client) then
      raise exception 'life runtime: client is reserved for human review custody' using errcode='23514'; end if;
  end if;
  return new;
end $$;

-- Read-only identity helper uses existing installer auth privileges. The
-- verified live-session helper is reused; no auth privilege is regranted.
create function life_review.request_identity() returns jsonb language plpgsql
security definer set search_path='' as $$
declare identity jsonb;
begin
  identity:=life_runtime.request_identity();
  return jsonb_build_object('auth_subject',identity->'auth_subject',
    'upstream_client_id',(identity->>'upstream_client_id')::uuid,
    'session_id',(auth.jwt()->>'session_id')::uuid);
end $$;

do $$ declare t text; begin
  foreach t in array array['boards','work_items','item_links','dependencies','activity'] loop
    execute format('grant select on life_ops.%I to life_review_executor',t);
    execute format('create policy life_review_read on life_ops.%I for select to life_review_executor using (true)',t);
  end loop;
end $$;
grant update(state,decision_ref,outcome_ref,lease_token,leased_by,lease_until) on life_ops.work_items to life_review_executor;
create policy life_review_update on life_ops.work_items for update to life_review_executor using (true) with check (true);
grant update(enabled) on life_ops.boards to life_review_executor;
create policy life_review_lock on life_ops.boards for update to life_review_executor using (true) with check (true);
grant insert on life_ops.activity to life_review_executor;
create policy life_review_audit on life_ops.activity for insert to life_review_executor with check (true);
grant usage on sequence life_ops.activity_id_seq to life_review_executor;
grant execute on function life_runtime.safe_ref(text),life_runtime.prose(text,integer),
  life_runtime.fit_rows(jsonb,integer) to life_review_executor;

create function life_review.authorize(p_human_grant_id uuid,p_operation text)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare identity jsonb; g life_review.human_grants; board_key text;
begin
  identity:=life_review.request_identity();
  select * into g from life_review.human_grants where id=p_human_grant_id
    and auth_subject=(identity->>'auth_subject')::uuid
    and upstream_client_id=(identity->>'upstream_client_id')::uuid
    and enabled and revoked_at is null and valid_from<=clock_timestamp()
    and valid_until>clock_timestamp() and p_operation=any(operations) for share;
  if not found then raise exception 'life review: request denied' using errcode='42501'; end if;
  select b.board_key into board_key from life_ops.boards b where b.id=g.board_id and b.enabled for share;
  if not found then raise exception 'life review: request denied' using errcode='42501'; end if;
  return jsonb_build_object('human_grant_id',g.id,'auth_subject',g.auth_subject,
    'upstream_client_id',g.upstream_client_id,'session_id',identity->'session_id',
    'board_id',g.board_id,'board_key',board_key,'actor_ref',g.actor_ref);
end $$;

create function life_review.queue(p_human_grant_id uuid,p_after_id uuid default null,p_limit integer default 10)
returns jsonb language plpgsql security definer set search_path='' as $$
declare scope jsonb; rows jsonb; n bigint; result jsonb; board uuid; next_id uuid;
begin
  scope:=life_review.authorize(p_human_grant_id,'queue'); board:=(scope->>'board_id')::uuid;
  if p_limit is null or p_limit not between 1 and 20 then
    raise exception 'life review: invalid page bound' using errcode='22023'; end if;
  if p_after_id is not null and not exists(select 1 from life_ops.work_items where id=p_after_id and board_id=board) then
    raise exception 'life review: request denied' using errcode='42501'; end if;
  -- Count and candidate page share one statement snapshot; byte trimming then
  -- advances only through actually returned rows, never the pre-trim limit.
  select (select count(*) from life_ops.work_items where board_id=board and state not in ('done','dismissed')
    and (p_after_id is null or id>p_after_id)),
    life_runtime.fit_rows(coalesce(jsonb_agg(to_jsonb(r) order by r.id),'[]'),12288) into n,rows
    from (select id,life_runtime.prose(title,512) as title,octet_length(title)>512 as title_truncated,
      state,version::text,life_runtime.safe_ref(source_ref) as source_ref,
      octet_length(source_ref)>512 as source_ref_omitted,due_at,not_before,updated_at
      from life_ops.work_items where board_id=board and state not in ('done','dismissed')
      and (p_after_id is null or id>p_after_id) order by id limit p_limit) r;
  if n>jsonb_array_length(rows) then
    if jsonb_array_length(rows)=0 then raise exception 'life review: response exceeds budget' using errcode='54000'; end if;
    next_id:=(rows->-1->>'id')::uuid;
  end if;
  result:=jsonb_build_object('contract','life-human-review/1','generated_at',clock_timestamp(),'scope',scope,
    'items',rows,'next_after_id',next_id,'has_more',n>jsonb_array_length(rows),
    'coverage',jsonb_build_object('scope','One authorized board; all nonterminal work, ordered by item UUID.',
      'items_omitted',n-jsonb_array_length(rows),'external_sources_checked',false,'snapshot_consistent_across_pages',false));
  if octet_length(result::text)>16384 then raise exception 'life review: response exceeds budget' using errcode='54000'; end if;
  return result;
end $$;

create function life_review.item(p_human_grant_id uuid,p_item_id uuid,p_limit integer default 10)
returns jsonb language plpgsql security definer set search_path='' as $$
declare scope jsonb; w life_ops.work_items; links jsonb; deps jsonb; events jsonb;
  n_links bigint; n_deps bigint; n_events bigint; result jsonb; board uuid;
begin
  scope:=life_review.authorize(p_human_grant_id,'item'); board:=(scope->>'board_id')::uuid;
  if p_limit is null or p_limit not between 1 and 20 then
    raise exception 'life review: invalid context bound' using errcode='22023'; end if;
  select * into w from life_ops.work_items where id=p_item_id and board_id=board;
  if not found then raise exception 'life review: request denied' using errcode='42501'; end if;
  select count(*) into n_links from life_ops.item_links where board_id=board and item_id=w.id;
  select count(*) into n_deps from life_ops.dependencies where board_id=board and item_id=w.id;
  select count(*) into n_events from life_ops.activity where board_id=board and item_id=w.id;
  select life_runtime.fit_rows(coalesce(jsonb_agg(to_jsonb(r) order by r.created_at,r.id),'[]'),2048) into links
    from (select relation,source_store,source_kind,life_runtime.safe_ref(source_key) as source_key,
      life_runtime.safe_ref(evidence_ref) as evidence_ref,observed_at,
      octet_length(source_key)>512 or octet_length(evidence_ref)>512 as references_omitted,
      created_at,id from life_ops.item_links where board_id=board and item_id=w.id order by created_at,id limit p_limit) r;
  -- Ordering keys are internal, not part of the UI's evidence schema.
  select coalesce(jsonb_agg(value-'created_at'-'id' order by ordinal),'[]') into links
    from jsonb_array_elements(links) with ordinality e(value,ordinal);
  select life_runtime.fit_rows(coalesce(jsonb_agg(to_jsonb(r) order by r.id),'[]'),2048) into deps
    from (select r.id,life_runtime.prose(r.title,512) as title,octet_length(r.title)>512 as title_truncated,r.state,r.version::text
      from life_ops.dependencies d join life_ops.work_items r on r.id=d.requires_id and r.board_id=d.board_id
      where d.board_id=board and d.item_id=w.id order by r.id limit p_limit) r;
  select life_runtime.fit_rows(coalesce(jsonb_agg(jsonb_build_object('id',r.id::text,'actor_ref',r.actor_ref,
    'event_kind',r.event_kind,'evidence_ref',r.evidence_ref,'reference_omitted',r.reference_omitted,
    'recorded_at',r.recorded_at) order by r.id desc),'[]'),2048) into events
    from (select id,actor_ref,event_kind,life_runtime.safe_ref(evidence_ref) as evidence_ref,
      coalesce(octet_length(evidence_ref)>512,false) as reference_omitted,recorded_at
      from life_ops.activity where board_id=board and item_id=w.id order by id desc limit p_limit) r;
  result:=jsonb_build_object('contract','life-human-review/1','generated_at',clock_timestamp(),'scope',scope,
    'item',jsonb_build_object('id',w.id,'title',life_runtime.prose(w.title,512),'title_truncated',octet_length(w.title)>512,
      'description',life_runtime.prose(w.description,4096),'description_truncated',octet_length(w.description)>4096,
      'state',w.state,'version',w.version::text,'source_ref',life_runtime.safe_ref(w.source_ref),
      'source_ref_omitted',octet_length(w.source_ref)>512,'decision_ref',life_runtime.safe_ref(w.decision_ref),
      'decision_ref_omitted',coalesce(octet_length(w.decision_ref)>512,false),'outcome_ref',life_runtime.safe_ref(w.outcome_ref),
      'outcome_ref_omitted',coalesce(octet_length(w.outcome_ref)>512,false),'due_at',w.due_at,'not_before',w.not_before,
      'snoozed_until',w.snoozed_until,'updated_at',w.updated_at),
    'evidence',links,'dependencies',deps,'activity',events,'coverage',jsonb_build_object(
      'scope','One authorized board; references are untrusted locators, not verified source contents.',
      'evidence_omitted',greatest(n_links-jsonb_array_length(links),0),
      'dependencies_omitted',greatest(n_deps-jsonb_array_length(deps),0),
      'activity_omitted',greatest(n_events-jsonb_array_length(events),0),'external_sources_checked',false));
  if octet_length(result::text)>16384 then raise exception 'life review: response exceeds budget' using errcode='54000'; end if;
  return result;
end $$;

create function life_review.decide(p_human_grant_id uuid,p_item_id uuid,p_expected_version bigint,
  p_state text,p_decision_ref text,p_outcome_ref text default null)
returns jsonb language plpgsql security definer set search_path='' as $$
declare scope jsonb; w life_ops.work_items; result jsonb;
begin
  scope:=life_review.authorize(p_human_grant_id,'decide');
  if p_expected_version is null or p_expected_version<1 or p_state is null
     or p_state not in ('ready','done','dismissed')
     or p_decision_ref is null or p_decision_ref<>btrim(p_decision_ref)
     or length(p_decision_ref) not between 1 and 2000 or octet_length(p_decision_ref)>2048
     or (p_state<>'done' and p_outcome_ref is not null)
     or (p_state='done' and (p_outcome_ref is null or p_outcome_ref<>btrim(p_outcome_ref)
       or length(p_outcome_ref) not between 1 and 2000 or octet_length(p_outcome_ref)>2048)) then
    raise exception 'life review: invalid decision or evidence' using errcode='22023'; end if;
  select * into w from life_ops.work_items where id=p_item_id and board_id=(scope->>'board_id')::uuid for update;
  if not found then raise exception 'life review: request denied' using errcode='42501'; end if;
  -- Recheck session/expiry after any item-lock wait, before decision authority.
  scope:=life_review.authorize(p_human_grant_id,'decide');
  perform public.life_decide_work_v1(w.id,p_expected_version,p_state,p_decision_ref,p_outcome_ref);
  select * into w from life_ops.work_items where id=w.id;
  insert into life_ops.activity(board_id,item_id,actor_ref,event_kind,evidence_ref,detail)
  values(w.board_id,w.id,scope->>'actor_ref','human_decision',p_decision_ref,
    jsonb_build_object('human_grant_id',scope->'human_grant_id','auth_subject',scope->'auth_subject',
      'upstream_client_id',scope->'upstream_client_id','session_id',scope->'session_id',
      'expected_version',p_expected_version::text,'item_version',w.version::text,'state',w.state));
  result:=jsonb_build_object('contract','life-human-review/1','generated_at',clock_timestamp(),'scope',scope,
    'item',jsonb_build_object('id',w.id,'state',w.state,'version',w.version::text,
      'decision_ref',life_runtime.safe_ref(w.decision_ref),'decision_ref_omitted',octet_length(w.decision_ref)>512,
      'outcome_ref',life_runtime.safe_ref(w.outcome_ref),'outcome_ref_omitted',coalesce(octet_length(w.outcome_ref)>512,false)),
    'authority','Human decision recorded; no external action performed.');
  if octet_length(result::text)>16384 then raise exception 'life review: response exceeds budget' using errcode='54000'; end if;
  return result;
end $$;

create function public.life_human_review_queue_v1(p_human_grant_id uuid,p_after_id uuid default null,p_limit integer default 10)
returns jsonb language sql security invoker set search_path='' as $$
  select life_review.queue(p_human_grant_id,p_after_id,p_limit)
$$;
create function public.life_human_review_item_v1(p_human_grant_id uuid,p_item_id uuid,p_limit integer default 10)
returns jsonb language sql security invoker set search_path='' as $$
  select life_review.item(p_human_grant_id,p_item_id,p_limit)
$$;
create function public.life_human_decide_work_v1(p_human_grant_id uuid,p_item_id uuid,p_expected_version bigint,
  p_state text,p_decision_ref text,p_outcome_ref text default null)
returns jsonb language plpgsql security invoker set search_path='' as $$
begin
  return life_review.decide(p_human_grant_id,p_item_id,p_expected_version,p_state,p_decision_ref,p_outcome_ref);
exception when sqlstate '40001' or sqlstate '55000' then
  raise exception 'life review: work decision conflict' using errcode='PT409';
end $$;

-- Base guard/decision definitions below retain existing behavior, adding only
-- the isolated review executor to their administrative current_user allowlists.
create or replace function life_ops.guard_work() returns trigger language plpgsql
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
    if current_user not in ('postgres','supabase_admin','life_review_executor') and (
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

create or replace function public.life_decide_work_v1(p_item_id uuid,p_expected_version bigint,
  p_state text,p_decision_ref text,p_outcome_ref text default null) returns void
language plpgsql security invoker set search_path='' as $$
declare w life_ops.work_items;
begin
  if current_user not in ('postgres','supabase_admin','life_review_executor') then
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

grant execute on function public.life_decide_work_v1(uuid,bigint,text,text,text) to life_review_executor;
do $$ declare f record; begin
  execute format('grant life_review_executor to %I with inherit false,set true',current_user);
  grant create on schema life_review to life_review_executor;
  for f in select p.oid::regprocedure as signature,p.proname,n.nspname from pg_proc p
    join pg_namespace n on n.oid=p.pronamespace where n.nspname='life_review'
    or (n.nspname='public' and p.proname in ('life_human_review_queue_v1','life_human_review_item_v1','life_human_decide_work_v1')) loop
    execute format('revoke all on function %s from public,anon,authenticated,service_role,life_runtime_executor',f.signature);
    if f.nspname='life_review' then
      if f.proname in ('queue','item','decide') then
        execute format('grant execute on function %s to authenticated',f.signature);
        execute format('alter function %s owner to life_review_executor',f.signature);
      else execute format('grant execute on function %s to life_review_executor',f.signature); end if;
    else execute format('grant execute on function %s to authenticated',f.signature); end if;
  end loop;
  revoke create on schema life_review from life_review_executor;
  execute format('revoke life_review_executor from %I',current_user);
end $$;
comment on schema life_review is 'Optional human review adapter; no grants seeded; dedicated client custody required; keep outside exposed API schemas.';
