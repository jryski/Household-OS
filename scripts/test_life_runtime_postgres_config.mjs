import assert from 'node:assert/strict';
import { test } from 'node:test';
import { openPostgres,validatePostgresTarget } from './life_runtime_postgres.mjs';

const base='postgresql://postgres@127.0.0.1:55432/life_acceptance';
const ack='synthetic-disposable';

test('explicit loopback fixture targets validate',()=>{
  for(const target of [base,'postgres://postgres@localhost/life_runtime_fixture',
    'postgresql://postgres@[::1]/life_acceptance']) {
    assert.equal(validatePostgresTarget(target,ack).pathname.startsWith('/life_'),true);
  }
});

test('unsafe target, query overrides and missing acknowledgement never load the driver',async()=>{
  const denied=[
    [base+'?host=remote.invalid',ack],
    [base+'?dbname=production',ack],
    [base+'?database=production',ack],
    [base+'?options=-c%20search_path%3Dpublic',ack],
    [base+'#host=remote.invalid',ack],
    ['postgresql://postgres@remote.invalid/life_acceptance',ack],
    ['postgresql://postgres@127.0.0.1/production',ack],
    ['https://postgres@127.0.0.1/life_acceptance',ack],
    [base,undefined],
    ['not a URL',ack],
  ];
  for(const [target,acknowledgement] of denied) {
    let loaded=false;
    await assert.rejects(openPostgres({env:{LIFE_RUNTIME_DATABASE_URL:target,
      LIFE_RUNTIME_POSTGRES_ACK:acknowledgement},loadClient:()=>{loaded=true;throw new Error('must not load');}}));
    assert.equal(loaded,false);
  }
});

test('no native target leaves PGlite mode without a driver load',async()=>{
  assert.equal(await openPostgres({env:{},loadClient:()=>{throw new Error('must not load');}}),null);
});
