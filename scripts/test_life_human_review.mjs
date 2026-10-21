import assert from 'node:assert/strict';
import { readFile, writeFile } from 'node:fs/promises';
import { PGlite } from '@electric-sql/pglite';

// Local SQL authorization fixtures only: no JWT signature, native concurrency,
// hosted installation, dedicated-client custody, browser or rollout acceptance.
const db = new PGlite();
let count = 0;
const query = (sql, args = []) => db.query(sql, args);
const value = async (sql, args = []) => Object.values((await query(sql, args)).rows[0])[0];
function check(name, actual, expected = true) {
  assert.deepEqual(actual, expected, name);
  console.log(`ok ${++count} - ${name}`);
}
async function denied(name, sql, args = [], code = '42501') {
  await assert.rejects(query(sql, args), error => error.code === code, name);
  console.log(`ok ${++count} - ${name}`);
}
const subject = '00000000-0000-4000-8000-000000000001';
const otherSubject = '00000000-0000-4000-8000-000000000002';
const workerClient = 'a0000000-0000-4000-8000-000000000101';
const reviewClient = 'b0000000-0000-4000-8000-000000000102';
const session = '00000000-0000-4000-8000-000000000202';
const workerSession = '00000000-0000-4000-8000-000000000201';
const claims = { sub: subject, role: 'authenticated', client_id: reviewClient,
  session_id: session, exp: Math.floor(Date.now() / 1000) + 3600 };
const workerClaims = { ...claims, client_id: workerClient, session_id: workerSession,
  app_metadata: { actor_ref: 'human:fixture', human: true } };
async function caller(payload = claims, role = 'authenticated') {
  await db.exec(`set role ${role}`);
  await query("select set_config('request.jwt.claims',$1,false)", [JSON.stringify(payload)]);
}
const admin = () => db.exec('set role postgres');
let grant, workerGrant, board, item, otherItem;
const workerInsert = `insert into life_runtime.principal_grants(auth_subject,upstream_client_id,board_id,actor_ref,
  operations,valid_until,evidence_ref) values($1,$2,$3,'worker:fixture',array['context','claim','submit'],now()+interval '1 day','fixture:worker') returning id`;
const humanInsert = `insert into life_review.human_grants(auth_subject,upstream_client_id,board_id,actor_ref,
  operations,valid_until,evidence_ref) values($1,$2,$3,'human:fixture',array['queue','item','decide'],now()+interval '1 day','fixture:human') returning id`;
const calls = () => [
  ['select public.life_human_review_queue_v1($1)', [grant]],
  ['select public.life_human_review_item_v1($1,$2)', [grant, item]],
  ["select public.life_human_decide_work_v1($1,$2,1,'ready','human-review:fixture')", [grant, item]],
];
async function denyAll(name, payload = claims) {
  await caller(payload);
  for (const [i, [sql, args]] of calls().entries()) await denied(`${name} operation ${i + 1}`, sql, args);
}

try {
  await db.exec(`create role anon; create role authenticated; create role service_role bypassrls;
    revoke create on schema public from public;
    create schema auth;
    create table auth.sessions(id uuid primary key,user_id uuid not null,not_after timestamptz,oauth_client_id uuid not null);
    create function auth.jwt() returns jsonb language sql stable as
      $$ select coalesce(nullif(current_setting('request.jwt.claims',true),''),'{}')::jsonb $$;
    create function auth.uid() returns uuid language sql stable as $$ select (auth.jwt()->>'sub')::uuid $$;
    create role fixture_installer createrole;
    grant usage on schema auth to fixture_installer;
    grant select on auth.sessions to fixture_installer;
    grant create on schema public to fixture_installer;
    create schema life_ops authorization fixture_installer;
    create schema life_runtime authorization fixture_installer;
    create schema life_review authorization fixture_installer;`);
  await db.exec('set role fixture_installer');
  for (const name of ['20261016111304_life_assistance_work_plane.sql',
    '20261016112522_index_life_assistance_foreign_keys.sql',
    '20261020130357_life_runtime_adapter.sql', '20261021020036_life_human_review_adapter.sql']) {
    const sql = await readFile(new URL('../supabase/migrations/' + name, import.meta.url), 'utf8');
    if (name.includes('life_human_review')) {
      // Deliberately hostile pre-existing installer defaults must not leak new
      // human-schema/table/function authority to the worker executor.
      await db.exec(`alter default privileges grant usage,create on schemas to life_runtime_executor;
        alter default privileges grant all on tables to life_runtime_executor;
        alter default privileges grant execute on functions to life_runtime_executor;`);
    }
    // Same PGlite namespace shim as the established runtime suite; native
    // unchanged-migration/managed-role acceptance is deferred for this slice.
    await db.exec(sql.replace(/^create schema (life_ops|life_runtime|life_review);$/gm, ''));
  }
  await admin();
  check('human grants are not seeded', Number(await value('select count(*) from life_review.human_grants')), 0);
  check('worker grants are not seeded', Number(await value('select count(*) from life_runtime.principal_grants')), 0);
  check('review role is isolated', await value("select not rolcanlogin and not rolinherit and not rolsuper and not rolbypassrls and not rolcreaterole from pg_roles where rolname='life_review_executor'"));
  for (const role of ['authenticated', 'anon', 'service_role', 'life_runtime_executor']) {
    check(`${role} has no review membership`, await value('select pg_has_role($1,\'life_review_executor\',\'member\')', [role]), false);
  }
  for (const schema of ['auth', 'public', 'life_ops', 'life_review']) {
    check(`review executor cannot CREATE in ${schema}`, await value("select has_schema_privilege('life_review_executor',$1,'create')", [schema]), false);
  }
  check('review executor has no auth usage', await value("select has_schema_privilege('life_review_executor','auth','usage')"), false);
  check('installer temporary SET and INHERIT removed', await value("select not pg_has_role('fixture_installer','life_review_executor','set') and not pg_has_role('fixture_installer','life_review_executor','usage')"));
  check('human facades are invokers', await value("select count(*)=3 and bool_and(not prosecdef) from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname='public' and p.proname like 'life_human_%_v1'"));
  check('decision-capable definer is isolated review role', await value("select pg_get_userbyid(proowner)='life_review_executor' and prosecdef from pg_proc where oid='life_review.decide(uuid,uuid,bigint,text,text,text)'::regprocedure"));
  check('identity-only definer stays installer-owned', await value("select pg_get_userbyid(proowner)='fixture_installer' and prosecdef from pg_proc where oid='life_review.request_identity()'::regprocedure"));
  for (const role of ['anon', 'service_role', 'life_runtime_executor']) {
    check(`${role} cannot execute human entry points`, Number(await value("select count(*) from pg_proc where proname like 'life_human_%_v1' and has_function_privilege($1,oid,'execute')", [role])), 0);
  }
  check('worker executor has no base decision execute', await value("select has_function_privilege('life_runtime_executor','public.life_decide_work_v1(uuid,bigint,text,text,text)','execute')"), false);
  check('installer defaults cannot give worker review-schema usage', await value("select has_schema_privilege('life_runtime_executor','life_review','usage')"), false);
  check('installer defaults cannot give worker human-table access', await value("select has_table_privilege('life_runtime_executor','life_review.human_grants','select,insert,update,delete,truncate')"), false);
  check('worker definers cannot reach review decision authority', await value("select not exists(select 1 from pg_proc where prosecdef and pg_get_userbyid(proowner)='life_runtime_executor' and (has_function_privilege(proowner,'public.life_decide_work_v1(uuid,bigint,text,text,text)'::regprocedure,'execute') or has_function_privilege(proowner,'life_review.decide(uuid,uuid,bigint,text,text,text)'::regprocedure,'execute')))"));
  await db.exec("insert into life_ops.boards(board_key,title) values('review-demo','Review fixture'),('review-other','Other fixture')");
  board = await value("select id from life_ops.boards where board_key='review-demo'");
  item = await value("select public.life_propose_work_v1('review-demo','example','Review fixture','wiki:fixture','source:fixture',$1)", ['界'.repeat(12000)]);
  otherItem = await value("select public.life_propose_work_v1('review-other','foreign','Other board','wiki:other','source:other')");
  const dependency = await value("select public.life_propose_work_v1('review-demo','dependency','Prerequisite fixture','wiki:dependency','source:fixture')");
  await query("select public.life_decide_work_v1($1,1,'done','decision:prerequisite','outcome:prerequisite')", [dependency]);
  await query('insert into life_ops.dependencies(board_id,item_id,requires_id) values($1,$2,$3)', [board, item, dependency]);
  await query("insert into life_ops.item_links(board_id,item_id,relation,source_store,source_kind,source_key,evidence_ref,observed_at) values($1,$2,'evidence','HOUSE','wiki','fixture','wiki:fixture',now())", [board, item]);
  await query('insert into auth.sessions(id,user_id,oauth_client_id) values($1,$2,$3),($4,$2,$5)', [session, subject, reviewClient, workerSession, workerClient]);
  workerGrant = await value(workerInsert, [subject, workerClient, board]);
  for (const client of [workerClient.toUpperCase(), workerClient.replaceAll('-', '')]) {
    await denied('worker client aliases cannot become human grants', humanInsert, [subject, client, board], '23514');
  }
  grant = await value(humanInsert, [subject, reviewClient, board]);
  for (const client of [reviewClient.toUpperCase(), reviewClient.replaceAll('-', '')]) {
    await denied('disabled human client aliases cannot become worker grants', workerInsert, [subject, client, board], '23514');
    await denied('worker client reassignment to human alias denied', 'update life_runtime.principal_grants set upstream_client_id=$1 where id=$2', [client, workerGrant], '55000');
  }
  await denied('human client reassignment denied', 'update life_review.human_grants set upstream_client_id=$1 where id=$2', [workerClient, grant], '55000');
  await denied('worker client history cannot be deleted', 'delete from life_runtime.principal_grants where id=$1', [workerGrant], '55000');
  await denied('human client history cannot be deleted', 'delete from life_review.human_grants where id=$1', [grant], '55000');
  for (const table of ['life_review.human_grants', 'life_runtime.principal_grants']) {
    await denied('client history cannot be truncated', `truncate ${table}`, [], '55000');
    for (const isolation of ['repeatable read', 'serializable']) {
      await db.exec(`begin isolation level ${isolation}`);
      await denied('configuration rejects retained transaction snapshot', `update ${table} set revoked_at=now()`, [], '22023');
      await db.exec('rollback');
    }
  }
  await denyAll('disabled human grant');
  await admin(); await query('update life_review.human_grants set enabled=true where id=$1', [grant]);
  await denyAll('same-principal worker token and forged human label', workerClaims);
  await caller();
  for (const [sql, args] of calls()) await denied('worker grant UUID conveys no human authority', sql, [workerGrant, ...args.slice(1)]);
  const queue = await value(calls()[0][0], calls()[0][1]);
  const context = await value(calls()[1][0], calls()[1][1]);
  check('human scope derives from verified grant and current session', context.scope, {
    human_grant_id: grant, auth_subject: subject, upstream_client_id: reviewClient,
    session_id: session, board_id: board, board_key: 'review-demo', actor_ref: 'human:fixture',
  });
  check('terminal-free queue includes proposed item', queue.items.some(row => row.id === item && row.state === 'proposed'));
  check('queue versions are strings', queue.items.every(row => typeof row.version === 'string'));
  check('final queue page has no continuation', queue.has_more === false && queue.next_after_id === null);
  check('description UTF8 bound and omission explicit', Buffer.byteLength(context.item.description) <= 4096 && context.item.description_truncated);
  check('item includes evidence and string dependency versions', context.evidence.length === 1 && context.dependencies[0].version === '2');
  check('item response is below 16KiB', Buffer.byteLength(JSON.stringify(context)) <= 16384);
  check('references are not dereferenced', context.coverage.external_sources_checked, false);
  check('no lease token in human reads', JSON.stringify([queue, context]).includes('lease_token'), false);
  await denied('cross-board item denied', calls()[1][0], [grant, otherItem]);
  await denied('cross-board decision denied', calls()[2][0], [grant, otherItem]);
  await denied('foreign-board queue cursor denied', 'select public.life_human_review_queue_v1($1,$2)', [grant, otherItem]);
  for (const limit of [0, 21, null]) await denied('queue bounds', 'select public.life_human_review_queue_v1($1,null,$2)', [grant, limit], '22023');
  for (const limit of [0, 21, null]) await denied('item bounds', 'select public.life_human_review_item_v1($1,$2,$3)', [grant, item, limit], '22023');
  for (const payload of [
    { ...claims, sub: otherSubject }, { ...claims, client_id: workerClient },
    { ...claims, client_id: null }, { ...claims, client_id: 'bad-uuid' },
    { ...claims, app_metadata: { client_id: workerClient } },
    { sub: subject, role: 'authenticated', session_id: session, exp: claims.exp, user_metadata: { client_id: reviewClient, human: true } },
    { ...claims, session_id: null }, { ...claims, exp: Math.floor(Date.now() / 1000) - 1 },
  ]) await denyAll('unverified/mismatched identity', payload);
  await admin(); await query('delete from auth.sessions where id=$1', [session]);
  await denyAll('deleted session');
  await admin(); await query('insert into auth.sessions(id,user_id,oauth_client_id) values($1,$2,$3)', [session, subject, reviewClient]);
  for (const update of ["revoked_at=now()", "valid_from=now()-interval '2 days',valid_until=now()-interval '1 day'"]) {
    await admin(); await query(`update life_review.human_grants set ${update} where id=$1`, [grant]);
    await denyAll('revoked/expired grant');
    await admin();
    await denied('revoked/expired human client remains reserved', workerInsert, [subject, reviewClient.replaceAll('-', ''), board], '23514');
    await query("update life_review.human_grants set revoked_at=null,valid_until=now()+interval '1 day' where id=$1", [grant]);
  }
  await query("update life_runtime.principal_grants set revoked_at=now(),valid_from=now()-interval '2 days',valid_until=now()-interval '1 day' where id=$1", [workerGrant]);
  await denied('revoked/expired worker client remains reserved', humanInsert, [subject, workerClient.replaceAll('-', ''), board], '23514');
  await query('update life_ops.boards set enabled=false where id=$1', [board]);
  await denyAll('disabled board');
  await admin(); await query('update life_ops.boards set enabled=true where id=$1', [board]);
  await query("update life_review.human_grants set operations=array['item'] where id=$1", [grant]);
  await caller();
  await denied('queue operation not granted', calls()[0][0], calls()[0][1]);
  await denied('decision operation not granted', calls()[2][0], calls()[2][1]);
  await admin(); await query("update life_review.human_grants set operations=array['queue','item','decide'] where id=$1", [grant]);
  await caller();
  await denied('authenticated cannot call base decision', "select public.life_decide_work_v1($1,1,'done','forged:decision','forged:outcome')", [item]);
  await denied('authenticated cannot read base work', 'select * from life_ops.work_items');
  await denied('authenticated cannot read human grants', 'select * from life_review.human_grants');
  await denied('authenticated cannot invoke identity helper', 'select life_review.request_identity()');
  await denied('authenticated cannot invoke authorizer', "select life_review.authorize($1,'decide')", [grant]);
  await caller(claims, 'life_review_executor');
  await denied('review executor cannot edit grants', 'update life_review.human_grants set revoked_at=now() where id=$1', [grant]);
  await denied('review executor cannot change board policy', 'update life_ops.boards set enabled=false where id=$1', [board]);
  await denied('review executor cannot edit proposal title', "update life_ops.work_items set title='forged' where id=$1", [item]);
  await caller(workerClaims, 'life_runtime_executor');
  await denied('worker executor cannot directly decide', "select public.life_decide_work_v1($1,1,'done','forged:decision','forged:outcome')", [item]);
  await denied('worker executor still cannot accept by table mutation', "update life_ops.work_items set state='done' where id=$1", [item]);
  await caller();
  for (const [version, state, decision, outcome] of [
    [null, 'ready', 'decision:fixture', null], ['0', 'ready', 'decision:fixture', null],
    ['1', null, 'decision:fixture', null], ['1', 'scheduled', 'decision:fixture', null],
    ['1', 'researching', 'decision:fixture', null], ['1', 'ready', '', null],
    ['1', 'ready', ' decision:fixture ', null], ['1', 'done', 'decision:fixture', null],
    ['1', 'ready', 'decision:fixture', 'unexpected:outcome'],
    ['1', 'ready', '界'.repeat(1000), null],
  ]) await denied('invalid decision input fails closed', 'select public.life_human_decide_work_v1($1,$2,$3,$4,$5,$6)', [grant, item, version, state, decision, outcome], '22023');
  await admin();
  const auditBefore = await value("select count(*) from life_ops.activity where event_kind='human_decision'");
  await caller();
  const decision = await value(calls()[2][0], calls()[2][1]);
  check('human decision returns canonical state and string version', decision.item.state === 'ready' && decision.item.version === '2');
  await denied('stale version is typed conflict', calls()[2][0], calls()[2][1], 'PT409');
  await admin();
  check('exactly one successful decision audit', Number(await value("select count(*) from life_ops.activity where event_kind='human_decision'")) - Number(auditBefore), 1);
  check('decision audit derives subject/client/session/actor', await value("select actor_ref='human:fixture' and detail->>'auth_subject'=$2 and detail->>'upstream_client_id'=$3 and detail->>'session_id'=$4 and detail->>'expected_version'='1' from life_ops.activity where item_id=$1 and event_kind='human_decision'", [item, subject, reviewClient, session]));
  await query("update life_runtime.principal_grants set revoked_at=null,enabled=true,valid_until=now()+interval '1 day' where id=$1", [workerGrant]);
  await caller(workerClaims);
  const lease = await value('select public.life_runtime_claim_work_v1($1,$2)', [workerGrant, item]);
  await caller();
  const leased = await value(calls()[1][0], calls()[1][1]);
  const finished = await value("select public.life_human_decide_work_v1($1,$2,$3,'done','human-review:done','outcome:fixture')", [grant, item, leased.item.version]);
  check('human completion records explicit outcome', finished.item.state === 'done' && finished.item.outcome_ref === 'outcome:fixture');
  await admin();
  check('human decision atomically clears worker lease', await value('select lease_token is null and leased_by is null and lease_until is null from life_ops.work_items where id=$1', [item]));
  await caller();
  await denied('terminal state requires a correction proposal', "select public.life_human_decide_work_v1($1,$2,$3,'ready','human-review:again')", [grant, item, finished.item.version], 'PT409');
  await caller(workerClaims);
  await denied('old worker lease cannot submit after human decision', "select public.life_runtime_submit_work_v1($1,$2,$3,'finding:late')", [workerGrant, item, lease.lease_token], 'PT409');
  await admin();
  const huge = await value("insert into life_ops.work_items(board_id,item_key,title,source_ref,proposed_by,version) values($1,'huge-version','Exact version','source:fixture','source:fixture',9007199254740993) returning id", [board]);
  await caller();
  check('versions beyond JS safe integer retain exact decimal string', (await value(calls()[1][0], [grant, huge])).item.version, '9007199254740993');
  const hugeDecision = await value("select public.life_human_decide_work_v1($1,$2,$3,'dismissed','human-review:exact')", [grant, huge, '9007199254740993']);
  check('CAS preserves large version exactly', hugeDecision.item.version, '9007199254740994');
  await admin();
  const longRef = await value("select public.life_propose_work_v1('review-demo','long-reference','Reference fixture',$1,'source:fixture')", ['界'.repeat(1000)]);
  await query("insert into life_ops.item_links(board_id,item_id,relation,source_store,source_kind,source_key,evidence_ref,observed_at) select $1,$2,'evidence','HOUSE','fixture',i::text,$3,now() from generate_series(1,25) i", [board, longRef, '界'.repeat(1000)]);
  await query("insert into life_ops.activity(board_id,item_id,actor_ref,event_kind,evidence_ref) select $1,$2,'fixture','notice',$3 from generate_series(1,25)", [board, longRef, '界'.repeat(1000)]);
  await caller();
  const bounded = await value('select public.life_human_review_item_v1($1,$2,20)', [grant, longRef]);
  check('long source locator omitted without changing it', bounded.item.source_ref === null && bounded.item.source_ref_omitted);
  check('long evidence locator omissions explicit', bounded.evidence.every(row => row.evidence_ref === null && row.references_omitted));
  check('recent activity ordering is numeric with string transport', bounded.activity.every((row, i) => typeof row.id === 'string' && (i === 0 || BigInt(bounded.activity[i - 1].id) > BigInt(row.id))));
  check('row and byte omissions are explicit', bounded.coverage.evidence_omitted > 0 && bounded.coverage.activity_omitted > 0);
  check('bounded long-reference item is below 16KiB', Buffer.byteLength(JSON.stringify(bounded)) <= 16384);
  const omittedDecision = await value("select public.life_human_decide_work_v1($1,$2,1,'dismissed',$3)", [grant, longRef, 'x'.repeat(1000)]);
  check('long decision reference omitted explicitly in response', omittedDecision.item.decision_ref === null && omittedDecision.item.decision_ref_omitted);
  await admin();
  check('canonical decision locator preserved in database', (await value('select decision_ref from life_ops.work_items where id=$1', [longRef])).length, 1000);
  await query("insert into life_ops.work_items(board_id,item_key,title,source_ref,proposed_by) select $1,'page-'||i,repeat('界',300),repeat('x',512),'source:fixture' from generate_series(1,35) i", [board]);
  await caller();
  const seen = [];
  let after = null, more = true, pages = 0;
  while (more) {
    const page = await value('select public.life_human_review_queue_v1($1,$2,20)', [grant, after]);
    check('queue page byte bound', Buffer.byteLength(JSON.stringify(page)) <= 16384);
    check('queue omissions nonnegative', page.coverage.items_omitted >= 0);
    check('queue cursor follows only delivered rows', page.next_after_id, page.has_more ? page.items.at(-1).id : null);
    seen.push(...page.items.map(row => row.id));
    after = page.next_after_id; more = page.has_more; pages++;
    assert.ok(pages < 10, 'finite page traversal');
  }
  check('byte-limited queue requires multiple pages', pages > 1);
  check('pagination loses or duplicates no fixture items', seen.length === 35 && new Set(seen).size === 35);
  if (process.env.LIFE_HUMAN_REVIEW_GOLDEN_OUTPUT) {
    await writeFile(process.env.LIFE_HUMAN_REVIEW_GOLDEN_OUTPUT, JSON.stringify({ queue, item: context, decision }, null, 2) + '\n');
  }
  console.log(`PASS ${count} human review SQL assertions (PGlite synthetic only)`);
} finally { await db.close(); }
