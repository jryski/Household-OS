-- Optional authenticated adapter for the existing life work plane.
-- No grants are seeded or enabled. No broker, human-decision or policy adapter
-- is activated. JWT claims must be set by the authenticated Data API, not SQL
-- supplied by a model. The private schema must stay outside exposed API schemas.
create role life_runtime_executor nologin noinherit nosuperuser nocreatedb
  nocreaterole noreplication nobypassrls;
create schema life_runtime;
revoke all on schema life_runtime from public,anon,authenticated,service_role;
grant usage on schema life_runtime to authenticated,life_runtime_executor;
grant usage on schema life_ops to life_runtime_executor;

create table life_runtime.principal_grants (
  id uuid primary key default gen_random_uuid(),
  auth_subject uuid not null,
  upstream_client_id text not null check
    (length(upstream_client_id) between 1 and 256 and upstream_client_id=btrim(upstream_client_id)),
  board_id uuid not null references life_ops.boards(id),
  actor_ref text not null check (length(btrim(actor_ref)) between 1 and 120),
  operations text[] not null check (cardinality(operations) between 1 and 4
    and operations <@ array['context','check_in','claim','submit']::text[]
    and array_position(operations,null) is null),
  enabled boolean not null default false,
  valid_from timestamptz not null default now(),
  valid_until timestamptz not null,
  revoked_at timestamptz,
  evidence_ref text not null check (length(btrim(evidence_ref)) between 1 and 2000),
  check (valid_until > valid_from)
);
create index principal_grants_subject_client on life_runtime.principal_grants(auth_subject,upstream_client_id,board_id);
create index principal_grants_board on life_runtime.principal_grants(board_id);
alter table life_runtime.principal_grants enable row level security;
revoke all on life_runtime.principal_grants from public,anon,authenticated,service_role,life_runtime_executor;
grant select,update(revoked_at) on life_runtime.principal_grants to life_runtime_executor;
create policy executor_read_grants on life_runtime.principal_grants for select
  to life_runtime_executor using (true);
create policy executor_lock_grants on life_runtime.principal_grants for update
  to life_runtime_executor using (true) with check (true);
-- UPDATE privilege permits row locks, but never runtime configuration changes.
create function life_runtime.guard_grant() returns trigger language plpgsql
security invoker set search_path='' as $$
begin
  if current_user not in ('postgres','supabase_admin') then
    raise exception 'life runtime: administrative configuration required' using errcode='42501';
  end if;
  return case when tg_op='DELETE' then old else new end;
end $$;
create trigger guard_grant before insert or update or delete on life_runtime.principal_grants
  for each row execute function life_runtime.guard_grant();

-- Only a non-login executor receives these additive object policies. No existing
-- caller policy changes, no BYPASSRLS and no direct authenticated table access.
do $$ declare t text; begin
  foreach t in array array['boards','work_items','item_links','dependencies','activity','signals','checkins'] loop
    execute format('grant select on life_ops.%I to life_runtime_executor',t);
    execute format('create policy life_runtime_read on life_ops.%I for select to life_runtime_executor using (true)',t);
  end loop;
  foreach t in array array['activity','checkins'] loop
    execute format('grant insert on life_ops.%I to life_runtime_executor',t);
    execute format('create policy life_runtime_insert on life_ops.%I for insert to life_runtime_executor with check (true)',t);
  end loop;
end $$;
grant update(state,snoozed_until,lease_token,leased_by,lease_until) on life_ops.work_items to life_runtime_executor;
create policy life_runtime_update on life_ops.work_items for update to life_runtime_executor using (true) with check (true);
grant update(enabled) on life_ops.boards to life_runtime_executor;
create policy life_runtime_lock on life_ops.boards for update to life_runtime_executor using (true) with check (true);
grant usage on sequence life_ops.activity_id_seq to life_runtime_executor;
grant execute on function public.life_check_in_v1(text,text,text,bigint,integer),
  public.life_claim_work_v1(uuid,text,integer),public.life_submit_work_v1(uuid,uuid,text,text,boolean)
  to life_runtime_executor;

-- Identity-only helper uses the installer's existing auth privileges. Hosted
-- postgres cannot regrant auth-schema usage. This helper cannot mutate work,
-- grants, policy or sessions and is callable only by the isolated executor.
create function life_runtime.request_identity() returns jsonb language plpgsql
security definer set search_path='' as $$
declare claims jsonb; subject uuid; sid uuid; top_client text; nested_client text; effective_client text;
begin
  -- Every operation resolves current request identity and rechecks live authority.
  -- user_metadata is deliberately ignored: it is not a server-controlled claim.
  claims:=auth.jwt(); subject:=auth.uid();
  if jsonb_typeof(claims) is distinct from 'object' or subject is null
     or claims->>'role' is distinct from 'authenticated' then
    raise exception 'life runtime: request denied' using errcode='42501'; end if;
  if claims ? 'client_id' then
    if jsonb_typeof(claims->'client_id') is distinct from 'string' then
      raise exception 'life runtime: request denied' using errcode='42501'; end if;
    top_client:=claims->>'client_id';
    if length(top_client) not between 1 and 256 or top_client<>btrim(top_client) then
      raise exception 'life runtime: request denied' using errcode='42501'; end if;
  end if;
  if claims ? 'app_metadata' then
    if jsonb_typeof(claims->'app_metadata') is distinct from 'object' then
      raise exception 'life runtime: request denied' using errcode='42501'; end if;
    if (claims->'app_metadata') ? 'client_id' then
      if jsonb_typeof(claims#>'{app_metadata,client_id}') is distinct from 'string' then
        raise exception 'life runtime: request denied' using errcode='42501'; end if;
      nested_client:=claims#>>'{app_metadata,client_id}';
      if length(nested_client) not between 1 and 256 or nested_client<>btrim(nested_client) then
        raise exception 'life runtime: request denied' using errcode='42501'; end if;
    end if;
  end if;
  effective_client:=coalesce(top_client,nested_client);
  if effective_client is null or (top_client is not null and nested_client is not null and top_client<>nested_client) then
    raise exception 'life runtime: request denied' using errcode='42501'; end if;
  if jsonb_typeof(claims->'session_id') is distinct from 'string'
     or jsonb_typeof(claims->'exp') is distinct from 'number'
     or (claims->>'exp') !~ '^[0-9]{1,12}$' then
    raise exception 'life runtime: request denied' using errcode='42501'; end if;
  sid:=(claims->>'session_id')::uuid;
  if (claims->>'exp')::bigint<=extract(epoch from clock_timestamp()) or
    not exists(select 1 from auth.sessions s where s.id=sid and s.user_id=subject
      and (s.not_after is null or s.not_after>clock_timestamp())
      and s.oauth_client_id=effective_client::uuid) then
    raise exception 'life runtime: request denied' using errcode='42501'; end if;
  return jsonb_build_object('auth_subject',subject,'upstream_client_id',effective_client);
exception when invalid_text_representation then
  raise exception 'life runtime: request denied' using errcode='42501';
end $$;

create function life_runtime.authorize(p_grant_id uuid,p_operation text)
returns life_runtime.principal_grants language plpgsql security invoker set search_path='' as $$
declare identity jsonb; subject uuid; effective_client text; g life_runtime.principal_grants;
begin
  identity:=life_runtime.request_identity();
  subject:=(identity->>'auth_subject')::uuid;
  effective_client:=identity->>'upstream_client_id';
  select * into g from life_runtime.principal_grants where id=p_grant_id
    and auth_subject=subject and upstream_client_id=effective_client
    and enabled and revoked_at is null and valid_from<=clock_timestamp()
    and valid_until>clock_timestamp() and p_operation=any(operations) for share;
  if not found or not exists(select 1 from life_ops.boards where id=g.board_id and enabled) then
    raise exception 'life runtime: request denied' using errcode='42501'; end if;
  return g;
exception when invalid_text_representation then
  raise exception 'life runtime: request denied' using errcode='42501';
end $$;

-- Keep opaque references intact or explicitly omit them. Never silently shorten
-- a reference into a different locator. Descriptions may be shortened as prose.
create function life_runtime.safe_ref(p_value text) returns text language sql
immutable security invoker set search_path='' as $$
  select case when octet_length(p_value)<=512 then p_value else null end
$$;
create function life_runtime.prose(p_value text,p_bytes integer) returns text language plpgsql
immutable security invoker set search_path='' as $$
declare value text:=left(p_value,p_bytes);
begin
  while octet_length(value)>p_bytes loop value:=left(value,length(value)-1); end loop;
  return value;
end $$;
create function life_runtime.fit_rows(p_rows jsonb,p_bytes integer) returns jsonb
language plpgsql immutable security invoker set search_path='' as $$
declare rows jsonb:='[]'; candidate jsonb;
begin
  for candidate in select value from jsonb_array_elements(p_rows) loop
    exit when octet_length((rows||jsonb_build_array(candidate))::text)>p_bytes;
    rows:=rows||jsonb_build_array(candidate);
  end loop;
  return rows;
end $$;
create function life_runtime.scope(p_grant life_runtime.principal_grants)
returns jsonb language sql immutable security invoker set search_path='' as $$
  select jsonb_build_object('grant_id',p_grant.id,'auth_subject',p_grant.auth_subject,
    'upstream_client_id',p_grant.upstream_client_id,'board_id',p_grant.board_id)
$$;
create function life_runtime.audit(p_grant life_runtime.principal_grants,p_item uuid,p_kind text,p_ref text,
  p_item_version bigint default null)
returns void language sql security invoker set search_path='' as $$
  insert into life_ops.activity(board_id,item_id,actor_ref,event_kind,evidence_ref,detail)
  values(p_grant.board_id,p_item,p_grant.actor_ref,p_kind,p_ref,
    jsonb_build_object('grant_id',p_grant.id,'auth_subject',p_grant.auth_subject,
      'upstream_client_id',p_grant.upstream_client_id,'item_version',p_item_version))
$$;

create function life_runtime.context(p_grant_id uuid,p_item_id uuid,p_limit integer default 10)
returns jsonb language plpgsql security definer set search_path='' as $$
declare g life_runtime.principal_grants; w life_ops.work_items; links jsonb; deps jsonb; events jsonb;
  n_links bigint; n_deps bigint; n_events bigint; result jsonb;
begin
  g:=life_runtime.authorize(p_grant_id,'context');
  if p_limit is null or p_limit not between 1 and 20 then
    raise exception 'life runtime: invalid context bound' using errcode='22023'; end if;
  select * into w from life_ops.work_items where id=p_item_id and board_id=g.board_id;
  if not found then raise exception 'life runtime: request denied' using errcode='42501'; end if;
  select count(*) into n_links from life_ops.item_links where board_id=g.board_id and item_id=w.id;
  select count(*) into n_deps from life_ops.dependencies where board_id=g.board_id and item_id=w.id;
  select count(*) into n_events from life_ops.activity where board_id=g.board_id and item_id=w.id;
  select life_runtime.fit_rows(coalesce(jsonb_agg(to_jsonb(r) order by r.created_at,r.id),'[]'),2048) into links
    from (select id,relation,source_store,source_kind,life_runtime.safe_ref(source_key) as source_key,
      life_runtime.safe_ref(evidence_ref) as evidence_ref,
      octet_length(source_key)>512 or octet_length(evidence_ref)>512 as references_omitted,
      observed_at,created_at from life_ops.item_links where board_id=g.board_id and item_id=w.id
      order by created_at,id limit p_limit) r;
  select life_runtime.fit_rows(coalesce(jsonb_agg(to_jsonb(r) order by r.id),'[]'),2048) into deps
    from (select d.requires_id as id,r.title,r.state,r.version
      from life_ops.dependencies d join life_ops.work_items r on r.id=d.requires_id and r.board_id=d.board_id
      where d.board_id=g.board_id and d.item_id=w.id order by d.requires_id limit p_limit) r;
  select life_runtime.fit_rows(coalesce(jsonb_agg(to_jsonb(r) order by r.id desc),'[]'),2048) into events
    from (select id,event_kind,actor_ref,life_runtime.safe_ref(evidence_ref) as evidence_ref,
      coalesce(octet_length(evidence_ref)>512,false) as reference_omitted,recorded_at
      from life_ops.activity where board_id=g.board_id and item_id=w.id order by id desc limit p_limit) r;
  result:=jsonb_build_object('contract','life-runtime-context/1','generated_at',clock_timestamp(),
    'scope',life_runtime.scope(g),'item',jsonb_build_object(
    'id',w.id,'title',w.title,'description',life_runtime.prose(w.description,4096),
    'description_truncated',octet_length(w.description)>4096,'state',w.state,'version',w.version,
    'source_ref',life_runtime.safe_ref(w.source_ref),'source_ref_omitted',octet_length(w.source_ref)>512,
    'due_at',w.due_at,'not_before',w.not_before,'lease_until',w.lease_until),
    'evidence',links,'dependencies',deps,'activity',events,
    'coverage',jsonb_build_object('scope','One authorized board; references are locators, not verified source contents.',
      'evidence_total',n_links,'evidence_omitted',n_links-jsonb_array_length(links),
      'dependencies_total',n_deps,'dependencies_omitted',n_deps-jsonb_array_length(deps),
      'activity_total',n_events,'activity_omitted',n_events-jsonb_array_length(events),
      'limits','At most 20 rows per section and 2048 bytes per section; long locators omitted explicitly.',
      'external_sources_checked',false,'other_stores_checked',false),
    'authority','Research and submission for review only; no accepted outcome or external action.');
  if octet_length(result::text)>16384 then
    raise exception 'life runtime: context exceeds response budget' using errcode='54000'; end if;
  return result;
end $$;

create function life_runtime.check_in(p_grant_id uuid,p_evidence_ref text,
  p_after_signal bigint default 0,p_limit integer default 10) returns jsonb
language plpgsql security definer set search_path='' as $$
declare g life_runtime.principal_grants; raw jsonb; signals jsonb; work jsonb; next_id bigint; result jsonb;
begin
  g:=life_runtime.authorize(p_grant_id,'check_in');
  if p_limit is null or p_limit not between 1 and 20 then
    raise exception 'life runtime: invalid check-in bound' using errcode='22023'; end if;
  raw:=public.life_check_in_v1((select board_key from life_ops.boards where id=g.board_id),
    g.actor_ref,p_evidence_ref,p_after_signal,p_limit);
  select life_runtime.fit_rows(coalesce(jsonb_agg(jsonb_build_object(
    'id',s->'id','kind',s->'kind','evidence_ref',life_runtime.safe_ref(s->>'evidence_ref'),
    'reference_omitted',octet_length(s->>'evidence_ref')>512,
    'observed_at',s->'observed_at','valid_until',s->'valid_until',
    'matching_keys_omitted',true) order by (s->>'id')::bigint),'[]'),4096) into signals
    from jsonb_array_elements(raw->'signals') s;
  select life_runtime.fit_rows(coalesce(jsonb_agg(jsonb_build_object(
    'id',w->'id','title',w->'title','state',w->'state','version',w->'version',
    'source_ref',life_runtime.safe_ref(w->>'source_ref'),'source_ref_omitted',octet_length(w->>'source_ref')>512,
    'due_at',w->'due_at','not_before',w->'not_before') order by rank),'[]'),4096) into work
    from jsonb_array_elements(raw->'work') with ordinality r(w,rank);
  select coalesce(max((s->>'id')::bigint),p_after_signal) into next_id from jsonb_array_elements(signals) s;
  result:=jsonb_build_object('contract','life-runtime-check-in/1','generated_at',clock_timestamp(),
    'scope',life_runtime.scope(g),'checkin_id',raw->'checkin_id',
    'signals',signals,'next_signal_cursor',next_id,
    'has_more_signals',(raw->>'has_more_signals')::boolean or jsonb_array_length(signals)<jsonb_array_length(raw->'signals'),
    'work',work,'work_total',raw->'work_total',
    'coverage',jsonb_build_object('scope','One authorized board; other stores and external sources not checked.',
      'selected_signal_rows',jsonb_array_length(raw->'signals'),
      'returned_signal_rows',jsonb_array_length(signals),'matching_keys_omitted',true,
      'work_omitted',(raw->>'work_total')::bigint-jsonb_array_length(work),
      'limits','At most 20 rows per section and 4096 bytes per section; only returned signals advance the cursor.'),
    'authority','Suggestions and research only; no external execution.');
  if octet_length(result::text)>16384 then
    raise exception 'life runtime: check-in exceeds response budget' using errcode='54000'; end if;
  return result;
end $$;

create function life_runtime.claim(p_grant_id uuid,p_item_id uuid,p_lease_seconds integer default 300)
returns jsonb language plpgsql security definer set search_path='' as $$
declare g life_runtime.principal_grants; result jsonb;
begin
  g:=life_runtime.authorize(p_grant_id,'claim');
  if not exists(select 1 from life_ops.work_items where id=p_item_id and board_id=g.board_id) then
    raise exception 'life runtime: request denied' using errcode='42501'; end if;
  result:=public.life_claim_work_v1(p_item_id,g.actor_ref,p_lease_seconds);
  perform life_runtime.audit(g,p_item_id,'runtime_claim',null,(result->>'version')::bigint);
  return result||jsonb_build_object('contract','life-runtime-claim/1','scope',life_runtime.scope(g));
end $$;
create function life_runtime.submit(p_grant_id uuid,p_item_id uuid,p_lease_token uuid,
  p_finding_ref text,p_blocked boolean default false) returns jsonb
language plpgsql security definer set search_path='' as $$
declare g life_runtime.principal_grants; w life_ops.work_items;
begin
  g:=life_runtime.authorize(p_grant_id,'submit');
  select * into w from life_ops.work_items where id=p_item_id and board_id=g.board_id for update;
  if not found then
    raise exception 'life runtime: request denied' using errcode='42501'; end if;
  if w.state<>'researching' or w.lease_token is null then
    raise exception 'life runtime: stale or invalid lease' using errcode='55000'; end if;
  -- A lease belongs to one exact delegation, not merely a reusable actor label.
  -- Match the claim version so a trusted base-API reclaim cannot reuse old proof.
  if not exists(select 1 from life_ops.activity where board_id=g.board_id and item_id=w.id
    and event_kind='runtime_claim' and detail->>'grant_id'=g.id::text
    and detail->>'item_version'=w.version::text) then
    raise exception 'life runtime: request denied' using errcode='42501'; end if;
  perform public.life_submit_work_v1(p_item_id,p_lease_token,g.actor_ref,p_finding_ref,p_blocked);
  perform life_runtime.audit(g,p_item_id,'runtime_submit',p_finding_ref);
  select * into w from life_ops.work_items where id=p_item_id and board_id=g.board_id;
  return jsonb_build_object('contract','life-runtime-submit/1','scope',life_runtime.scope(g),
    'item_id',w.id,'state',w.state,'version',w.version,
    'authority','Submitted for review; no accepted outcome or external action.');
end $$;

-- Exposed functions are invoker facades, with no arbitrary function or role input.
create function public.life_runtime_context_v1(p_grant_id uuid,p_item_id uuid,p_limit integer default 10)
returns jsonb language sql security invoker set search_path='' as $$
  select life_runtime.context(p_grant_id,p_item_id,p_limit)
$$;
create function public.life_runtime_check_in_v1(p_grant_id uuid,p_evidence_ref text,
  p_after_signal bigint default 0,p_limit integer default 10) returns jsonb
language sql security invoker set search_path='' as $$
  select life_runtime.check_in(p_grant_id,p_evidence_ref,p_after_signal,p_limit)
$$;
create function public.life_runtime_claim_work_v1(p_grant_id uuid,p_item_id uuid,p_lease_seconds integer default 300)
returns jsonb language sql security invoker set search_path='' as $$
  select life_runtime.claim(p_grant_id,p_item_id,p_lease_seconds)
$$;
create function public.life_runtime_submit_work_v1(p_grant_id uuid,p_item_id uuid,p_lease_token uuid,
  p_finding_ref text,p_blocked boolean default false) returns jsonb
language sql security invoker set search_path='' as $$
  select life_runtime.submit(p_grant_id,p_item_id,p_lease_token,p_finding_ref,p_blocked)
$$;

do $$ declare f record; begin
  -- PG16+ CREATEROLE creators have ADMIN but not SET/INHERIT by default.
  -- Ownership transfer needs temporary SET and schema CREATE. The creator's
  -- automatic ADMIN-only membership may remain, without SET or INHERIT; the
  -- executor role is never granted to authenticated.
  execute format('grant life_runtime_executor to %I with inherit false,set true',current_user);
  grant create on schema life_runtime to life_runtime_executor;
  for f in select p.oid::regprocedure as signature,p.proname,n.nspname from pg_proc p
    join pg_namespace n on n.oid=p.pronamespace where n.nspname='life_runtime'
    or (n.nspname='public' and p.proname like 'life_runtime_%_v1') loop
    execute format('revoke all on function %s from public,anon,authenticated,service_role',f.signature);
    if f.nspname='life_runtime' then
      if f.proname in ('context','check_in','claim','submit') then
        execute format('grant execute on function %s to authenticated',f.signature);
        execute format('alter function %s owner to life_runtime_executor',f.signature);
      else execute format('grant execute on function %s to life_runtime_executor',f.signature); end if;
    else execute format('grant execute on function %s to authenticated',f.signature); end if;
  end loop;
  revoke create on schema life_runtime from life_runtime_executor;
  execute format('revoke life_runtime_executor from %I',current_user);
end $$;
comment on schema life_runtime is 'Optional disabled-by-default authenticated work adapter; no grants seeded; keep outside exposed API schemas.';
