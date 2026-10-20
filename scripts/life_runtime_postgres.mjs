import assert from 'node:assert/strict';
import { setTimeout as delay } from 'node:timers/promises';

export function validatePostgresTarget(target,ack) {
  if (ack !== 'synthetic-disposable') {
    throw new Error('PostgreSQL qualification requires the synthetic-disposable acknowledgement');
  }
  let url;
  try { url=new URL(target); } catch { throw new Error('Invalid synthetic PostgreSQL target'); }
  if (!['localhost','127.0.0.1','[::1]'].includes(url.hostname)
      || !['/life_acceptance','/life_runtime_fixture'].includes(url.pathname)
      || !['postgres:','postgresql:'].includes(url.protocol)
      || url.search || url.hash) {
    throw new Error('PostgreSQL qualification requires a loopback synthetic fixture database');
  }
  // pg-connection-string accepts query parameters that override host/database
  // and connection options. The URL guard therefore forbids every query/hash.
  return url;
}

export async function openPostgres({env=process.env,loadClient=()=>import('pg')}={}) {
  const target = env.LIFE_RUNTIME_DATABASE_URL;
  if (!target) return null;
  validatePostgresTarget(target,env.LIFE_RUNTIME_POSTGRES_ACK);
  const { Client } = await loadClient();
  async function connect() {
    const client = new Client({ connectionString:target,connectionTimeoutMillis:5000,
      statement_timeout:15000,lock_timeout:10000,application_name:'life-runtime-synthetic' });
    await client.connect();
    return client;
  }
  const client = await connect();
  try {
    const version = Number((await client.query("select current_setting('server_version_num') as version")).rows[0].version);
    if (version<170000 || version>=180000) throw new Error('PostgreSQL 17 is required');
    const existing = await client.query("select count(*)::integer as count from pg_namespace where nspname in ('auth','life_ops','life_runtime')");
    if (existing.rows[0].count!==0) throw new Error('Fixture database must be empty; existing application schemas found');
    console.log(`# native PostgreSQL ${version}: exact migrations, no namespace shim`);
    return { native:true,connect,query:(sql,args)=>client.query(sql,args),
      exec:sql=>client.query(sql),close:()=>client.end() };
  } catch (error) { await client.end(); throw error; }
}

export async function qualifyConcurrency({db,claims,grant,board,check}) {
  const a=await db.connect();
  const b=await db.connect();
  const one=async (connection,sql,args=[])=>Object.values((await connection.query(sql,args)).rows[0])[0];
  const adminValue=async (sql,args=[])=>Object.values((await db.query(sql,args)).rows[0])[0];
  async function worker(connection) {
    await connection.query('set role authenticated');
    await connection.query("select set_config('request.jwt.claims',$1,false)",[JSON.stringify(claims)]);
  }
  async function blockedBy(waiter,holder) {
    for(let attempt=0;attempt<100;attempt++) {
      if(await adminValue('select $1::integer=any(pg_blocking_pids($2::integer))',[holder,waiter])) return true;
      await delay(25);
    }
    return false;
  }
  async function ready(key) {
    const id=await adminValue("select public.life_propose_work_v1('board-demo',$1,'Concurrent fixture','evidence:concurrency','fixture-author')",[key]);
    await db.query("select public.life_decide_work_v1($1,1,'ready','decision:concurrency')",[id]);
    return id;
  }
  try {
    await db.exec('set role postgres');
    const second=await adminValue("insert into life_runtime.principal_grants(auth_subject,upstream_client_id,board_id,actor_ref,operations,valid_until,evidence_ref,enabled) values($1,$2,$3,'agent-second',array['context','check_in','claim','submit'],now()+interval '1 day','delegation:concurrency',true) returning id",[claims.sub,claims.client_id,board]);
    const item=await ready('two-session-claim');
    await worker(a); await worker(b);
    const apid=Number(await one(a,'select pg_backend_pid()'));
    const bpid=Number(await one(b,'select pg_backend_pid()'));
    check('real PostgreSQL workers use independent sessions',apid!==bpid);
    const race=await Promise.allSettled([
      one(a,'select public.life_runtime_claim_work_v1($1,$2)',[grant,item]),
      one(b,'select public.life_runtime_claim_work_v1($1,$2)',[second,item]),
    ]);
    check('two simultaneous claims have exactly one winner',race.filter(r=>r.status==='fulfilled').length,1);
    check('losing concurrent claim reports explicit HTTP conflict',race.find(r=>r.status==='rejected')?.reason.code,'PT409');
    const winner=race.find(r=>r.status==='fulfilled').value;
    check('database retains only winning lease',await adminValue('select lease_token from life_ops.work_items where id=$1',[item]),winner.lease_token);
    check('race records only one runtime claim',Number(await adminValue("select count(*) from life_ops.activity where item_id=$1 and event_kind='runtime_claim'",[item])),1);

    // Operation-first ordering: authorization holds a shared grant-row lock
    // through commit. A concurrent revocation must wait, then block every next
    // operation. Observe actual pg_blocking_pids, not an assumed sleep interval.
    const revokeItem=await ready('revoke-during-operation');
    await a.query('begin');
    await a.query('select public.life_runtime_context_v1($1,$2)',[grant,revokeItem]);
    await b.query('set role postgres');
    const revocation=b.query('update life_runtime.principal_grants set revoked_at=clock_timestamp() where id=$1',[grant])
      .then(r=>({rowCount:r.rowCount}),e=>({error:e.code}));
    const waits=await blockedBy(bpid,apid);
    await a.query('commit');
    const revoked=await revocation;
    check('revocation waits for authorized operation transaction',waits);
    check('revocation completes after operation commits',revoked.rowCount,1);
    const deniedCalls=[
      ['select public.life_runtime_context_v1($1,$2)',[grant,revokeItem]],
      ["select public.life_runtime_check_in_v1($1,'check:after-revocation')",[grant]],
      ['select public.life_runtime_claim_work_v1($1,$2)',[grant,revokeItem]],
      ["select public.life_runtime_submit_work_v1($1,$2,$3,'finding:after-revocation')",[grant,revokeItem,winner.lease_token]],
    ];
    for(const [i,[sql,args]] of deniedCalls.entries()) {
      await assert.rejects(a.query(sql,args),e=>e.code==='42501');
      check(`committed concurrent revocation denies operation ${i+1}`,true);
    }

    // Revocation-first ordering: a call that saw the old row but waits for the
    // revoker must recheck the updated row after the revocation commits.
    await db.query('update life_runtime.principal_grants set revoked_at=null where id=$1',[grant]);
    await b.query('begin');
    await b.query('update life_runtime.principal_grants set revoked_at=clock_timestamp() where id=$1',[grant]);
    const pending=a.query('select public.life_runtime_context_v1($1,$2)',[grant,revokeItem])
      .then(()=>({allowed:true}),e=>({error:e.code}));
    const contextWaits=await blockedBy(apid,bpid);
    await b.query('commit');
    const outcome=await pending;
    check('new operation waits behind in-progress revocation',contextWaits);
    check('waiting operation rechecks revoked grant after commit',outcome.error,'42501');
    check('revocation race never claims target work',await adminValue('select state from life_ops.work_items where id=$1',[revokeItem]),'ready');
    await db.query('update life_runtime.principal_grants set revoked_at=null where id=$1',[grant]);
  } finally {
    await a.query('rollback').catch(()=>{});
    await b.query('rollback').catch(()=>{});
    await Promise.all([a.end(),b.end()]);
  }
}
