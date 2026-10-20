import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { PGlite } from '@electric-sql/pglite';

// auth shims exercise SQL authorization only. They do not verify JWT signatures,
// broker grant custody, independent-session contention, or a live deployment.
const db = new PGlite();
let count = 0;
const query = (sql, args = []) => db.query(sql, args);
const value = async (sql, args = []) => Object.values((await query(sql, args)).rows[0])[0];
function check(name, actual, expected = true) {
  assert.deepEqual(actual, expected, name);
  console.log(`ok ${++count} - ${name}`);
}
async function denied(name, sql, args = [], code = '42501') {
  await assert.rejects(query(sql,args), e => e.code === code, name);
  console.log(`ok ${++count} - ${name}`);
}
const subject = '00000000-0000-4000-8000-000000000001';
const otherSubject = '00000000-0000-4000-8000-000000000002';
const client = '00000000-0000-4000-8000-000000000101';
const session = '00000000-0000-4000-8000-000000000201';
const claims = { sub:subject, role:'authenticated', client_id:client,
  session_id:session,exp:Math.floor(Date.now()/1000)+3600 };
async function caller(payload = claims, role = 'authenticated') {
  await db.exec(`set role ${role}`);
  await query("select set_config('request.jwt.claims',$1,false)",[JSON.stringify(payload)]);
}
const admin = () => db.exec('set role postgres');
let grant, item, foreignItem, token;
function calls() {
  return [
    ["select public.life_runtime_context_v1($1,$2)",[grant,item]],
    ["select public.life_runtime_check_in_v1($1,'check:fixture')",[grant]],
    ["select public.life_runtime_claim_work_v1($1,$2)",[grant,item]],
    ["select public.life_runtime_submit_work_v1($1,$2,$3,'finding:fixture')",[grant,item,token]],
  ];
}
async function denyEvery(name,payload = claims) {
  await caller(payload);
  for (const [i,[sql,args]] of calls().entries()) await denied(`${name} operation ${i+1}`,sql,args);
}
try {
  await db.exec(`create role anon; create role authenticated; create role service_role bypassrls;
    create schema auth;
    create table auth.sessions(id uuid primary key,user_id uuid not null,
      not_after timestamptz,oauth_client_id uuid not null);
    create function auth.jwt() returns jsonb language sql stable as
      $$ select coalesce(nullif(current_setting('request.jwt.claims',true),''),'{}')::jsonb $$;
    create function auth.uid() returns uuid language sql stable as $$ select (auth.jwt()->>'sub')::uuid $$;
    create role fixture_installer createrole;
    grant usage on schema auth to fixture_installer;
    grant select on auth.sessions to fixture_installer;
    grant create on schema public to fixture_installer;`);
  // PGlite cannot GRANT database ACLs (XX000 tuple concurrently deleted).
  // Precreate only the two owned namespaces; every remaining migration statement
  // runs unchanged under a non-superuser CREATEROLE installer without auth grant
  // options. Full PostgreSQL schema creation remains a separate acceptance check.
  await db.exec('create schema life_ops authorization fixture_installer; create schema life_runtime authorization fixture_installer;');
  await db.exec('set role fixture_installer');
  for (const name of [
    '20261016111304_life_assistance_work_plane.sql',
    '20261016112522_index_life_assistance_foreign_keys.sql',
    '20261020130357_life_runtime_adapter.sql',
  ]) {
    const sql=await readFile(new URL('../supabase/migrations/'+name,import.meta.url),'utf8');
    await db.exec(sql.replace(/^create schema (life_ops|life_runtime);$/gm,''));
  }
  await admin();
  check('non-superuser installer applied SQL after fixture namespace creation',await value("select not rolsuper from pg_roles where rolname='fixture_installer'"));
  check('temporary executor SET and INHERIT removed',await value("select not pg_has_role('fixture_installer','life_runtime_executor','set') and not pg_has_role('fixture_installer','life_runtime_executor','usage')"));
  check('temporary executor schema CREATE removed',await value("select has_schema_privilege('life_runtime_executor','life_runtime','create')"),false);
  check('executor has no auth schema usage',await value("select has_schema_privilege('life_runtime_executor','auth','usage')"),false);
  await query('insert into auth.sessions(id,user_id,oauth_client_id) values($1,$2,$3)',[session,subject,client]);
  check('no runtime grants seeded',Number(await value('select count(*) from life_runtime.principal_grants')),0);
  check('executor cannot login or bypass RLS',await value("select not rolcanlogin and not rolbypassrls and not rolsuper and not rolcreaterole from pg_roles where rolname='life_runtime_executor'"));
  check('authenticated is not executor member',await value("select pg_has_role('authenticated','life_runtime_executor','member')"),false);
  check('exposed runtime functions are invokers',await value("select bool_and(not prosecdef) from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname='public' and proname like 'life_runtime_%_v1'"));
  check('work definer owner is non-admin executor',await value("select bool_and(pg_get_userbyid(proowner)='life_runtime_executor') from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname='life_runtime' and prosecdef and proname<>'request_identity'"));
  check('service role cannot call runtime wrappers',Number(await value("select count(*) from pg_proc where proname like 'life_runtime_%_v1' and has_function_privilege('service_role',oid,'execute')")),0);
  check('anonymous cannot call runtime wrappers',Number(await value("select count(*) from pg_proc where proname like 'life_runtime_%_v1' and has_function_privilege('anon',oid,'execute')")),0);
  await db.exec("insert into life_ops.boards(board_key,title) values('board-demo','Demo'),('board-other','Other');");
  const board = await value("select id from life_ops.boards where board_key='board-demo'");
  item = await value("select public.life_propose_work_v1('board-demo','work-demo','Research fixture','evidence:fixture','original-proposer',$1)",['界'.repeat(12000)]);
  foreignItem = await value("select public.life_propose_work_v1('board-other','work-other','Private other board','evidence:other','other-proposer')");
  const dependency = await value("select public.life_propose_work_v1('board-demo','dependency-demo','Prior work','evidence:dependency','proposer')");
  await query("select public.life_decide_work_v1($1,1,'done','decision:dependency','outcome:dependency')",[dependency]);
  await query("insert into life_ops.dependencies(board_id,item_id,requires_id) values($1,$2,$3)",[board,item,dependency]);
  await query("select public.life_decide_work_v1($1,1,'ready','decision:ready')",[item]);
  await query("insert into life_ops.item_links(board_id,item_id,relation,source_store,source_kind,source_key,evidence_ref,observed_at) select $1,$2,'evidence','local','fixture',i::text,'evidence:'||i,now() from generate_series(1,25) i",[board,item]);
  grant=await value("insert into life_runtime.principal_grants(auth_subject,upstream_client_id,board_id,actor_ref,operations,valid_until,evidence_ref) values($1,$3,$2,'agent-fixture',array['context','check_in','claim','submit'],now()+interval '1 day','delegation:fixture') returning id",[subject,board,client]);
  token='00000000-0000-4000-8000-000000000099';
  await denyEvery('disabled grant');
  await admin(); await query('update life_runtime.principal_grants set enabled=true where id=$1',[grant]);
  await caller();
  const context=await value('select public.life_runtime_context_v1($1,$2,20)',[grant,item]);
  check('context includes canonical description',context.item.description.length>0);
  check('context marks shortened multibyte prose',context.item.description_truncated);
  check('context prose is byte bounded',Buffer.byteLength(context.item.description)<=4096);
  check('context has evidence and explicit omitted count',context.evidence.length>0 && context.coverage.evidence_omitted>0);
  check('context includes dependency state',context.dependencies[0].state,'done');
  check('context includes attributable activity',context.activity.length>0);
  check('context does not dereference other sources',context.coverage.external_sources_checked,false);
  check('context excludes lease tokens',JSON.stringify(context).includes('lease_token'),false);
  check('context is below 16KiB',Buffer.byteLength(JSON.stringify(context))<=16384);
  check('context scope binds verified subject/client/grant/board',context.scope,
    {grant_id:grant,auth_subject:subject,upstream_client_id:client,board_id:board});
  await denied('cross-board item context denied',calls()[0][0],[grant,foreignItem]);
  await denied('cross-board claim denied',calls()[2][0],[grant,foreignItem]);
  await denied('cross-board submit denied',calls()[3][0],[grant,foreignItem,token]);
  await denied('authenticated cannot read base tables','select * from life_ops.work_items');
  await denied('authenticated cannot read grant configuration','select * from life_runtime.principal_grants');
  await denied('authenticated cannot call base actor-label API',"select public.life_claim_work_v1($1,'forged-actor')",[item]);
  await denied('authenticated cannot call internal authorization helper',"select life_runtime.authorize($1,'context')",[grant]);
  await denied('authenticated cannot call private identity helper','select life_runtime.request_identity()');
  await denied('authenticated cannot call human decision',"select public.life_decide_work_v1($1,2,'done','forged:decision','forged:outcome')",[item]);
  const checkin=await value("select public.life_runtime_check_in_v1($1,'check:fixture')",[grant]);
  await admin();
  check('check-in actor derives from grant',await value('select agent_ref from life_ops.checkins where id=$1',[checkin.checkin_id]),'agent-fixture');
  for(let i=0;i<20;i++) await query("select public.life_record_signal_v1('board-demo',$1,'notice',array['unneeded:matching'],'evidence:'||$1||repeat('x',400),now(),'source-fixture')",['signal-'+i]);
  const longRefItem=await value("select public.life_propose_work_v1('board-demo','long-reference','Reference fixture',$1,'source-fixture')",['界'.repeat(1900)]);
  await query("insert into life_ops.item_links(board_id,item_id,relation,source_store,source_kind,source_key,evidence_ref,observed_at) values($1,$2,'evidence','local','fixture',$3,$3,now())",[board,longRefItem,'界'.repeat(1000)]);
  await caller();
  const boundedSignals=await value("select public.life_runtime_check_in_v1($1,'check:signals',0,20)",[grant]);
  check('check-in result is below 16KiB',Buffer.byteLength(JSON.stringify(boundedSignals))<=16384);
  check('signal byte bound explicitly retains continuation',boundedSignals.signals.length>0 && boundedSignals.signals.length<20 && boundedSignals.has_more_signals);
  check('cursor only advances through returned rows',boundedSignals.next_signal_cursor,boundedSignals.signals.at(-1).id);
  const nextSignals=await value("select public.life_runtime_check_in_v1($1,'check:signals',$2,20)",[grant,boundedSignals.next_signal_cursor]);
  check('next signal page starts immediately after delivered cursor',nextSignals.signals[0].id,boundedSignals.next_signal_cursor+1);
  check('matching keys do not enter model context',boundedSignals.signals.every(s=>!('match_keys' in s)&&s.matching_keys_omitted));
  const longContext=await value('select public.life_runtime_context_v1($1,$2)',[grant,longRefItem]);
  check('opaque long source ref omitted rather than shortened',longContext.item.source_ref===null&&longContext.item.source_ref_omitted);
  check('opaque evidence locator omission explicit',longContext.evidence[0].source_key===null&&longContext.evidence[0].references_omitted);
  await denyEvery('wrong subject',{...claims,sub:otherSubject});
  await denyEvery('wrong upstream client',{...claims,client_id:'client-other'});
  await denyEvery('conflicting upstream client',{...claims,app_metadata:{client_id:'client-other'}});
  await denyEvery('user metadata client is not authority',{sub:subject,role:'authenticated',user_metadata:{client_id:'client-demo'}});
  const nestedClaims={...claims,app_metadata:{client_id:client}}; delete nestedClaims.client_id;
  await caller(nestedClaims);
  check('server metadata fallback works',(await value(calls()[0][0],calls()[0][1])).item.id,item);
  const noSession={...claims}; delete noSession.session_id;
  await denyEvery('missing session claim',noSession);
  await denyEvery('expired access token',{...claims,exp:Math.floor(Date.now()/1000)-1});
  await admin(); await query("update auth.sessions set not_after=now()-interval '1 second' where id=$1",[session]);
  await denyEvery('expired upstream session');
  await admin(); await query('update auth.sessions set not_after=null,user_id=$2 where id=$1',[session,otherSubject]);
  await denyEvery('session belongs to another subject');
  await admin(); await query('update auth.sessions set user_id=$2,oauth_client_id=$3 where id=$1',[session,subject,'00000000-0000-4000-8000-000000000102']);
  await denyEvery('session belongs to another OAuth client');
  await admin(); await query('delete from auth.sessions where id=$1',[session]);
  await denyEvery('deleted session denies still-unexpired JWT');
  await admin(); await query('insert into auth.sessions(id,user_id,oauth_client_id) values($1,$2,$3)',[session,subject,client]);
  for(const malformed of [null,42,[],{},'', ' client-demo ', 'x'.repeat(257)]) {
    await caller({...claims,client_id:malformed});
    await denied('malformed upstream client denied',calls()[0][0],calls()[0][1]);
  }
  await denyEvery('unusable subject',{...claims,sub:'bad-uuid'});
  await denyEvery('service JWT is not delegated user',{...claims,role:'service_role'});
  await admin(); await query("update life_runtime.principal_grants set valid_from=now()-interval '2 days',valid_until=now()-interval '1 day' where id=$1",[grant]);
  await denyEvery('expired grant');
  await admin(); await query("update life_runtime.principal_grants set valid_until=now()+interval '1 day',revoked_at=now() where id=$1",[grant]);
  await denyEvery('revoked grant');
  await admin(); await query("update life_runtime.principal_grants set revoked_at=null,operations=array['context'] where id=$1",[grant]);
  await caller();
  for(const [sql,args] of calls().slice(1)) await denied('ungranted operation denied',sql,args);
  await admin(); await query("update life_runtime.principal_grants set operations=array['context','check_in','claim','submit'] where id=$1",[grant]);
  await caller();
  const lease=await value(calls()[2][0],calls()[2][1]); token=lease.lease_token;
  check('claim response carries verified scope',lease.scope,context.scope);
  await admin();
  check('lease actor derives from grant',await value('select leased_by from life_ops.work_items where id=$1',[item]),'agent-fixture');
  check('claim audit preserves verified request provenance',await value("select detail->>'auth_subject' from life_ops.activity where item_id=$1 and event_kind='runtime_claim'",[item]),subject);
  const alternateGrant=await value("insert into life_runtime.principal_grants(auth_subject,upstream_client_id,board_id,actor_ref,operations,valid_until,evidence_ref,enabled) values($1,$3,$2,'agent-fixture',array['submit'],now()+interval '1 day','delegation:other',true) returning id",[subject,board,client]);
  await caller();
  await denied('same actor label on another delegation cannot submit lease',calls()[3][0],[alternateGrant,item,token]);
  await admin();
  await query('update life_runtime.principal_grants set revoked_at=now() where id=$1',[grant]);
  await caller(); await denied('revocation after claim prevents submission',calls()[3][0],calls()[3][1]);
  await admin(); await query('update life_runtime.principal_grants set revoked_at=null where id=$1',[grant]);
  await caller();
  await denied('wrong lease token rejected',calls()[3][0],[grant,item,'00000000-0000-4000-8000-000000000098'],'55000');
  const submitted=await value(calls()[3][0],calls()[3][1]);
  check('submission response carries verified scope',submitted.scope,context.scope);
  check('submission response explicitly ends at review',submitted.state,'review');
  await denied('consumed submission cannot replay',calls()[3][0],calls()[3][1],'55000');
  await admin();
  check('submission stops at review',await value('select state from life_ops.work_items where id=$1',[item]),'review');
  check('submission cannot fabricate accepted outcome',await value('select outcome_ref from life_ops.work_items where id=$1',[item]),null);
  await db.exec('set role life_runtime_executor');
  await denied('executor cannot call human decision',"select public.life_decide_work_v1($1,4,'done','forged:decision','forged:outcome')",[item]);
  await denied('executor cannot rewrite board policy','update life_ops.boards set enabled=false where id=$1',[board]);
  await denied('executor cannot rewrite delegation','update life_runtime.principal_grants set revoked_at=now() where id=$1',[grant]);
  await admin(); await query('update life_ops.boards set enabled=false where id=$1',[board]);
  await denyEvery('disabled board');
  console.log(`1..${count}`);
} catch (error) {
  console.error(`${error.code ?? error.name}: ${error.message}\n${error.where ?? ''}`);
  process.exitCode=1;
} finally { await db.close(); }
