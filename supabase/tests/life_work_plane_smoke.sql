-- Run through an administrative SQL connection after migration.
-- All synthetic rows roll back. Sequence gaps are expected and harmless.
begin;
do $$
declare b text:='smoke-'||gen_random_uuid(); w uuid; l jsonb; c jsonb; s bigint;
begin
  if (select count(*) from pg_class t join pg_namespace n on n.oid=t.relnamespace
      where n.nspname='life_ops' and t.relkind='r' and t.relrowsecurity) <> 8 then
    raise exception 'smoke: expected eight RLS-enabled tables'; end if;
  if exists(select 1 from pg_proc p join pg_namespace n on n.oid=p.pronamespace
    where n.nspname='public' and p.proname like 'life_%_v1' and
      (p.prosecdef or has_function_privilege('anon',p.oid,'execute') or
       has_function_privilege('authenticated',p.oid,'execute'))) then
    raise exception 'smoke: unsafe RPC permissions'; end if;
  insert into life_ops.boards(board_key,title) values(b,'Synthetic smoke board');
  w:=public.life_propose_work_v1(b,'demo-work','Synthetic research','source:demo','agent-demo');
  if w is distinct from public.life_propose_work_v1(b,'demo-work','Synthetic research','source:demo','agent-demo') then
    raise exception 'smoke: proposal retry duplicated'; end if;
  perform public.life_decide_work_v1(w,1,'ready','decision:demo');
  execute 'set local role service_role';
  l:=public.life_claim_work_v1(w,'agent-demo');
  perform public.life_submit_work_v1(w,(l->>'lease_token')::uuid,'agent-demo','finding:demo');
  s:=public.life_record_signal_v1(b,'purchase-demo','purchase',array['gtin:00000000000001'],'receipt:demo',now(),'agent-demo');
  perform public.life_record_signal_v1(b,'recall-demo','recall',array['gtin:00000000000001'],'recall:demo',now(),'agent-demo');
  if public.life_match_recall_signals_v1(b,'agent-demo',clock_timestamp()) <> 1 then
    raise exception 'smoke: expected one possible recall match'; end if;
  c:=public.life_check_in_v1(b,'agent-demo','check:demo',0,1);
  if jsonb_array_length(c->'signals') <> 1 or not (c->>'has_more_signals')::boolean then
    raise exception 'smoke: bounded incremental check-in failed'; end if;
  begin
    perform public.life_decide_work_v1(w,3,'done','decision:forbidden','outcome:forbidden');
    raise exception 'smoke: service role unexpectedly accepted work';
  exception when insufficient_privilege then null;
  end;
  execute 'reset role';
  if (select state from life_ops.work_items where id=w) <> 'review' then
    raise exception 'smoke: submission bypassed review'; end if;
  perform public.life_decide_work_v1(w,(select version from life_ops.work_items where id=w),'done','decision:accepted','outcome:demo');
end $$;
rollback;
select 'life-work-plane smoke passed; synthetic rows rolled back' as result;
