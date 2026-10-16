import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { PGlite } from '@electric-sql/pglite';

const db = new PGlite();
let count = 0;
const query = (sql, args = []) => db.query(sql, args);
async function value(sql, args = []) {
  const r = await query(sql, args);
  return Object.values(r.rows[0])[0];
}
function check(name, actual, expected = true) {
  assert.deepEqual(actual, expected, name);
  console.log(`ok ${++count} - ${name}`);
}
async function rejects(name, sql, args, code) {
  await assert.rejects(query(sql, args), e => e.code === code, name);
  console.log(`ok ${++count} - ${name}`);
}
async function role(name) { await db.exec(`set role ${name}`); }
async function propose(key, board = 'board-demo', title = 'Research maintenance') {
  return value(`select public.life_propose_work_v1($1,$2,$3,'evidence:demo','agent-1')`, [board,key,title]);
}
async function decide(id, state, outcome = null) {
  const version = await value('select version from life_ops.work_items where id=$1',[id]);
  await query(`select public.life_decide_work_v1($1,$2,$3,'decision:demo',$4)`,[id,version,state,outcome]);
}
async function signal(key,kind,keys,board='board-demo',until=null) {
  return value(`select public.life_record_signal_v1($1,$2,$3,$4,'source:'||$2,
    '2026-01-01T12:00:00Z','agent-1',$5)`,[board,key,kind,keys,until]);
}
try {
  await db.exec('create role anon; create role authenticated; create role service_role bypassrls;');
  await db.exec(await readFile(new URL('../supabase/migrations/20261016111304_life_assistance_work_plane.sql',import.meta.url),'utf8'));
  console.log(`# ${await value('select version()')}`);
  check('all eight tables have RLS',Number(await value(`select count(*) from pg_class c
    join pg_namespace n on n.oid=c.relnamespace where n.nspname='life_ops' and c.relkind='r' and c.relrowsecurity`)),8);
  check('all RPCs use invoker security',await value(`select bool_and(not prosecdef) from pg_proc
    where proname like 'life_%_v1'`));
  for(const denied of ['anon','authenticated']) {
    check(`${denied} cannot use internal schema`,await value(`select has_schema_privilege($1,'life_ops','usage')`,[denied]),false);
    check(`${denied} cannot call any work-plane RPC`,Number(await value(`select count(*) from pg_proc p
      join pg_namespace n on n.oid=p.pronamespace where n.nspname='public' and p.proname like 'life_%_v1'
      and has_function_privilege($1,p.oid,'execute')`,[denied])),0);
    await role(denied);
    await rejects(`${denied} actually denied`,"select public.life_check_in_v1('board-demo','agent-1','source:demo')",[],'42501');
    await role('postgres');
  }
  await db.exec(`insert into life_ops.boards(board_key,title) values
    ('board-demo','Demo work'),('board-other','Other trust scope');`);
  const board=await value("select id from life_ops.boards where board_key='board-demo'");
  await role('service_role');
  const item=await propose('maintenance-demo');
  check('new work is only proposed',await value('select state from life_ops.work_items where id=$1',[item]),'proposed');
  check('proposal retry deduplicates',await propose('maintenance-demo'),item);
  await rejects('conflicting idempotency payload rejected',
    "select public.life_propose_work_v1('board-demo','maintenance-demo','Different','evidence:demo','agent-1')",[],'22023');
  await rejects('proposal cannot be claimed before acceptance',
    "select public.life_claim_work_v1($1,'agent-1')",[item],'55000');
  await rejects('service role cannot call human decision',
    "select public.life_decide_work_v1($1,1,'ready','decision:demo')",[item],'42501');
  await rejects('service role cannot mark done directly',
    "update life_ops.work_items set state='done' where id=$1",[item],'42501');
  await rejects('service role cannot change board policy',
    "update life_ops.boards set enabled=false where id=$1",[board],'42501');
  await rejects('source proposal cannot be rewritten',
    "update life_ops.work_items set title='rewritten' where id=$1",[item],'42501');
  await role('postgres');
  await rejects('stale acceptance version rejected',
    "select public.life_decide_work_v1($1,999,'ready','decision:demo')",[item],'40001');
  await decide(item,'ready');
  await role('service_role');
  const lease=await value("select public.life_claim_work_v1($1,'agent-1')",[item]);
  check('research lease has a token',typeof lease.lease_token,'string');
  await rejects('second claimant cannot take live lease',
    "select public.life_claim_work_v1($1,'agent-2')",[item],'55000');
  await rejects('invalid lease duration rejected',
    "select public.life_claim_work_v1($1,'agent-2',0)",[item],'22023');
  await rejects('wrong lease token rejected',
    "select public.life_submit_work_v1($1,gen_random_uuid(),'agent-1','finding:demo')",[item],'55000');
  await rejects('wrong actor cannot submit lease',
    "select public.life_submit_work_v1($1,$2,'agent-2','finding:demo')",[item,lease.lease_token],'55000');
  await query("select public.life_submit_work_v1($1,$2,'agent-1','finding:demo')",[item,lease.lease_token]);
  check('submitted finding needs review',await value('select state from life_ops.work_items where id=$1',[item]),'review');
  await rejects('submitted lease cannot be replayed',
    "select public.life_submit_work_v1($1,$2,'agent-1','finding:demo')",[item,lease.lease_token],'55000');
  await role('postgres');
  await rejects('done requires outcome evidence',
    "select public.life_decide_work_v1($1,(select version from life_ops.work_items where id=$1),'done','decision:demo')",[item],'22023');
  await decide(item,'done','outcome:demo');
  check('accepted outcome is done',await value('select state from life_ops.work_items where id=$1',[item]),'done');
  await rejects('terminal outcomes require correction proposal',
    "select public.life_decide_work_v1($1,(select version from life_ops.work_items where id=$1),'ready','decision:demo')",[item],'55000');

  const blocked=await propose('blocked-demo'); const prerequisite=await propose('prerequisite-demo');
  await decide(blocked,'ready');
  await query('insert into life_ops.dependencies values($1,$2,$3)',[board,blocked,prerequisite]);
  await rejects('dependency cycles rejected','insert into life_ops.dependencies values($1,$2,$3)',[board,prerequisite,blocked],'23514');
  const foreignItem=await propose('foreign-demo','board-other');
  await rejects('cross-board dependency rejected','insert into life_ops.dependencies values($1,$2,$3)',[board,blocked,foreignItem],'23503');
  await role('service_role');
  await rejects('unfinished prerequisite blocks claiming',"select public.life_claim_work_v1($1,'agent-1')",[blocked],'55000');
  await role('postgres'); await decide(prerequisite,'done','outcome:prerequisite');
  await role('service_role');
  const oldLease=await value("select public.life_claim_work_v1($1,'agent-1')",[blocked]);
  await role('postgres');
  await query("update life_ops.work_items set lease_until=clock_timestamp()-interval '1 second' where id=$1",[blocked]);
  await role('service_role');
  const newLease=await value("select public.life_claim_work_v1($1,'agent-2')",[blocked]);
  check('expired lease can be reclaimed',newLease.lease_token!==oldLease.lease_token);
  await rejects('old token fails after reclaim',
    "select public.life_submit_work_v1($1,$2,'agent-1','finding:stale')",[blocked,oldLease.lease_token],'55000');
  await query("select public.life_submit_work_v1($1,$2,'agent-2','finding:blocker',true)",[blocked,newLease.lease_token]);
  check('blocker is preserved',await value('select state from life_ops.work_items where id=$1',[blocked]),'blocked');

  const purchase=await signal('purchase-demo','purchase',['gtin:00000000000001']);
  check('signal retries deduplicate',await signal('purchase-demo','purchase',['gtin:00000000000001']),purchase);
  await rejects('signal revision conflict rejected',
    "select public.life_record_signal_v1('board-demo','purchase-demo','purchase',array['other'],'source:purchase-demo','2026-01-01T12:00:00Z','agent-1')",[],'22023');
  await rejects('null matching key rejected',
    "select public.life_record_signal_v1('board-demo','bad-demo','purchase',array[null::text],'source:bad','2026-01-01T12:00:00Z','agent-1')",[],'22023');
  await signal('recall-demo','recall',['gtin:00000000000001']);
  await signal('unrelated-demo','recall',['gtin:00000000000002']);
  await signal('expired-demo','recall',['gtin:00000000000001'],'board-demo','2026-01-02T00:00:00Z');
  await signal('other-scope-demo','recall',['gtin:00000000000001'],'board-other');
  check('matching creates only one valid same-board possible match',
    await value("select public.life_match_recall_signals_v1('board-demo','agent-1','2026-02-01T00:00:00Z')"),1);
  check('matching retry creates no duplicates',
    await value("select public.life_match_recall_signals_v1('board-demo','agent-2','2026-02-01T00:00:00Z')"),0);
  check('recall match remains proposed',await value("select state from life_ops.work_items where item_key like 'recall:%'"),'proposed');
  check('both sources linked',Number(await value("select count(*) from life_ops.item_links where relation='possible_match'")),2);
  const page1=await value("select public.life_check_in_v1('board-demo','agent-1','check:demo',0,2)");
  check('check-in returns bounded signal page',page1.signals.length,2);
  check('pagination exposes continuation',page1.has_more_signals);
  const page2=await value("select public.life_check_in_v1('board-demo','agent-1','check:demo',$1,2)",[page1.next_signal_cursor]);
  check('cursor progresses without overlap',page2.signals.every(s=>s.id>page1.next_signal_cursor));
  check('second page ends local history',page2.has_more_signals,false);
  const empty=await value("select public.life_check_in_v1('board-demo','agent-1','check:demo',$1,2)",[page2.next_signal_cursor]);
  check('empty page preserves cursor',empty.next_signal_cursor,page2.next_signal_cursor);
  check('coverage is explicit',page1.coverage.includes('other stores have not been checked'));
  await rejects('unbounded check-in rejected',"select public.life_check_in_v1('board-demo','agent-1','check:demo',0,999)",[],'22023');
  await rejects('future cursor rejected',"select public.life_check_in_v1('board-demo','agent-1','check:demo',99999,2)",[],'22023');
  await rejects('append-only signals cannot be rewritten',"update life_ops.signals set kind='changed' where id=$1",[purchase],'42501');
  await role('postgres');
  await rejects('append-only activity rejects admin rewrites',"update life_ops.activity set event_kind='changed'",[],'55000');
  await rejects('append-only check-ins reject rewrites',"delete from life_ops.checkins",[],'55000');
  await query(`insert into life_ops.routines(board_id,routine_key,title,evidence_ref,cadence,interval_days,next_due_at,enabled)
    values($1,'daily-demo','Review supplies','routine:demo','interval',1,'2025-01-01T00:00:00Z',true)`,[board]);
  await query(`insert into life_ops.routines(board_id,routine_key,title,evidence_ref,cadence,month,day,next_due_at,enabled)
    values($1,'season-demo','Seasonal inspection','routine:season','annual',2,29,'2024-02-29T00:00:00Z',true)`,[board]);
  await query(`insert into life_ops.routines(board_id,routine_key,title,evidence_ref,cadence,interval_days,next_due_at)
    values($1,'disabled-demo','Disabled routine','routine:disabled','interval',1,'2025-01-01T00:00:00Z')`,[board]);
  await role('service_role');
  check('missed daily and annual occurrences coalesce into two proposals',
    await value("select public.life_materialize_routines_v1('board-demo','2026-02-01T00:00:00Z')"),2);
  check('same routine evaluation is idempotent',
    await value("select public.life_materialize_routines_v1('board-demo','2026-02-01T00:00:00Z')"),0);
  check('leap date clamps to month end',await value("select to_char(next_due_at,'YYYY-MM-DD') from life_ops.routines where routine_key='season-demo'"),'2026-02-28');
  check('existing open routines do not create a recurring backlog',
    await value("select public.life_materialize_routines_v1('board-demo','2026-03-01T00:00:00Z')"),0);
  check('disabled routine stays disabled',await value("select enabled from life_ops.routines where routine_key='disabled-demo'"),false);
  check('service cannot enable routines',await value("select has_column_privilege('service_role','life_ops.routines','enabled','update')"),false);
  const deferred=await value("select public.life_propose_work_v1('board-demo','future-demo','Future work','evidence:future','agent-1','',array[]::text[],null,clock_timestamp()+interval '1 day')");
  await role('postgres'); await decide(deferred,'ready'); await role('service_role');
  await rejects('not-before blocks early claiming',"select public.life_claim_work_v1($1,'agent-1')",[deferred],'55000');
  await role('postgres');
  await query('update life_ops.boards set enabled=false where id=$1',[board]);
  await role('service_role');
  await rejects('disabled board rejects check-ins',"select public.life_check_in_v1('board-demo','agent-1','check:demo')",[],'P0002');
  check('no cron jobs or external effects installed',Number(await value("select count(*) from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname='cron'")),0);
  console.log(`1..${count}`);
} finally { await db.close(); }
