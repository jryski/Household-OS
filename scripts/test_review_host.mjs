import test from 'node:test';
import assert from 'node:assert/strict';
import {webcrypto} from 'node:crypto';
import {startReviewHost,validateHostConfig,DEFAULT_HOST_CONFIG} from '../review/host.mjs';
import hostConfig from '../review/host-config.mjs';
import {b64urlEncode,b64urlDecode,PENDING_KEY} from '../review/oauth.mjs';

// Synthetic identities and keys only. Keys are generated per run; no token literal is stored.
const subtle=webcrypto.subtle;
const ORIGIN='https://fixture.supabase.co',ISSUER=ORIGIN+'/auth/v1',HOST='https://review.example.test',REDIRECT=HOST+'/callback';
const CLIENT='00000000-0000-4000-8000-000000000102',SUBJECT='00000000-0000-4000-8000-000000000001',SESSION='00000000-0000-4000-8000-000000000302';
const binding={human_grant_id:'00000000-0000-4000-8000-000000000301',auth_subject:SUBJECT,upstream_client_id:CLIENT,board_id:'00000000-0000-4000-8000-000000000401'};
const config={mode:'connected',enabled:true,origin:ORIGIN,publishableKey:'sb_publishable_synthetic',oauthClientId:CLIENT,redirectUri:REDIRECT,binding};

const ec=await subtle.generateKey({name:'ECDSA',namedCurve:'P-256'},true,['sign','verify']);
const rogue=await subtle.generateKey({name:'ECDSA',namedCurve:'P-256'},true,['sign','verify']);
const rsa=await subtle.generateKey({name:'RSASSA-PKCS1-v1_5',modulusLength:2048,publicExponent:new Uint8Array([1,0,1]),hash:'SHA-256'},true,['sign','verify']);
const pub=async(k,kid,alg)=>{const {kty,crv,x,y,n,e}=await subtle.exportKey('jwk',k.publicKey);return Object.fromEntries(Object.entries({kty,crv,x,y,n,e,kid,alg,use:'sig'}).filter(([,v])=>v!==undefined));};
const JWKS={keys:[await pub(ec,'ec-1','ES256'),await pub(rsa,'rsa-1','RS256')]};
const enc=o=>b64urlEncode(new TextEncoder().encode(JSON.stringify(o)));
async function sign(payload,{key=ec.privateKey,header={alg:'ES256',kid:'ec-1',typ:'JWT'}}={}){
  const input=enc(header)+'.'+enc(payload);
  const alg=header.alg==='RS256'?{name:'RSASSA-PKCS1-v1_5'}:{name:'ECDSA',hash:'SHA-256'};
  const sig=header.alg==='none'?new Uint8Array([0]):new Uint8Array(await subtle.sign(alg,key,new TextEncoder().encode(input)));
  return input+'.'+b64urlEncode(sig);
}
const now=()=>Date.now(),exp=()=>Math.floor(Date.now()/1000)+3600;
const accessClaims=(o={})=>({aud:'authenticated',exp:exp(),iat:Math.floor(Date.now()/1000),iss:ISSUER,sub:SUBJECT,role:'authenticated',session_id:SESSION,client_id:CLIENT,app_metadata:{provider:'email'},...o});
const idClaims=(nonce,o={})=>({iss:ISSUER,sub:SUBJECT,aud:CLIENT,exp:exp(),iat:Math.floor(Date.now()/1000),nonce,client_id:CLIENT,...o});

function storage(){const m=new Map();return {get length(){return m.size;},key:i=>[...m.keys()][i]??null,getItem:k=>m.has(k)?m.get(k):null,setItem:(k,v)=>m.set(k,String(v)),removeItem:k=>m.delete(k),dump:()=>[...m.values()].join('\n'),map:m};}
const queueGolden=()=>({contract:'life-human-review/1',generated_at:new Date().toISOString(),scope:{...binding,session_id:SESSION,board_key:'life-home',actor_ref:'human:fixture'},items:[],next_after_id:null,has_more:false,coverage:{scope:'synthetic',items_omitted:0,external_sources_checked:false,snapshot_consistent_across_pages:false}});

/** Runs begin + callback against a synthetic auth server. `tokens(nonce)` builds the token response. */
async function harness({tokens,jwks=JWKS,tokenStatus=200,cfg=config,callback=null,session=storage(),local=storage(),startHref=HOST+'/'}={}){
  const calls=[],views=[],mounts=[];let href=startHref,assigned=null,replacedBeforeExchange=null,timers=[];
  const fetchImpl=async(url,options={})=>{calls.push({url:String(url),options});
    if(url===ISSUER+'/.well-known/jwks.json')return Response.json(jwks);
    if(url===ISSUER+'/oauth/token'){replacedBeforeExchange=href;if(tokenStatus!==200)return new Response('{}',{status:tokenStatus,headers:{'Content-Type':'application/json'}});const pending=JSON.parse(lastPending);return Response.json(await tokens(pending.nonce));}
    if(url.startsWith(ORIGIN+'/rest/v1/rpc/'))return Response.json(queueGolden());
    throw new Error('unexpected '+url);};
  let lastPending=null;
  const deps={fetchImpl,now,sessionStorage:session,localStorage:local,location:{get href(){return href;},get origin(){return new URL(href).origin;}},assign:u=>{assigned=u;},replaceUrl:u=>{href=u;},
    view:(root,name,detail)=>{views.push({name,reason:detail.reason});return {deskRoot:true};},
    mount:(root,client)=>{const m={client,destroyed:false,destroy(){this.destroyed=true;}};mounts.push(m);return m;},
    setTimer:(f,ms)=>{timers.push({f,ms});return timers.length;},clearTimer:()=>{}};
  const host=await startReviewHost({},cfg,deps);
  const out={host,calls,views,mounts,session,local,timers,get assigned(){return assigned;},get replacedBeforeExchange(){return replacedBeforeExchange;},deps};
  if(callback===null)return out;
  await host.signIn();lastPending=session.getItem(PENDING_KEY);
  const state=JSON.parse(lastPending).state;
  href=REDIRECT+'?'+new URLSearchParams(callback(state));
  out.second=await startReviewHost({},cfg,deps);
  out.pending=JSON.parse(lastPending);
  return out;
}
const good=async nonce=>({access_token:await sign(accessClaims()),token_type:'bearer',expires_in:3600,refresh_token:'synthetic-refresh',id_token:await sign(idClaims(nonce))});
const okCallback=state=>({code:'synthetic-code',state});

test('default configuration is example-only and connects nothing',async()=>{
  assert.deepEqual(hostConfig,DEFAULT_HOST_CONFIG);assert.equal(validateHostConfig().mode,'example');
  const calls=[];const fetchImpl=async()=>{calls.push(1);throw Error('no network');};
  const mounts=[];const host=await startReviewHost({},hostConfig,{fetchImpl,createExample:async()=>({mode:'example'}),mount:(r,c)=>{mounts.push(c);return {destroy(){}};}});
  assert.equal(host.state,'example');assert.equal(mounts[0].mode,'example');assert.equal(calls.length,0);
});

test('disabled or invalid connected configuration stays disconnected with no network',async()=>{
  const bad=[{...config,enabled:false},{...config,extra:true},{...config,origin:'http://fixture.supabase.co'},{...config,origin:'https://fixture.example.test'},{...config,redirectUri:REDIRECT+'?next=x'},{...config,redirectUri:'http://review.example.test/callback'},{...config,binding:{...binding,upstream_client_id:'00000000-0000-4000-8000-000000000999'}},{...config,publishableKey:'service_role_key'},{...config,enabled:'true'},{mode:'connected'}];
  for(const cfg of bad){const h=await harness({cfg});assert.equal(h.host.state,'disconnected');assert.equal(h.calls.length,0);assert.equal(h.mounts.length,0);}
  const elsewhere=await harness({startHref:'https://other.example.test/'});assert.equal(elsewhere.host.state,'disconnected');assert.equal(elsewhere.views[0].reason,'origin');
});

test('sign-in uses authorization code with S256 PKCE, openid, state and nonce',async()=>{
  const h=await harness();assert.equal(h.host.state,'signed-out');assert.equal(h.calls.length,0);
  await h.host.signIn();const u=new URL(h.assigned);const pending=JSON.parse(h.session.getItem(PENDING_KEY));
  assert.equal(u.origin+u.pathname,ISSUER+'/oauth/authorize');
  assert.deepEqual(Object.fromEntries(u.searchParams),{response_type:'code',client_id:CLIENT,redirect_uri:REDIRECT,scope:'openid',state:pending.state,nonce:pending.nonce,code_challenge:b64urlEncode(new Uint8Array(await subtle.digest('SHA-256',new TextEncoder().encode(pending.verifier)))),code_challenge_method:'S256'});
  assert.equal(h.local.length,0);assert.ok(b64urlDecode(pending.verifier).length===32);
});

test('verified callback connects the unchanged three-RPC client with the verified token only',async()=>{
  const h=await harness({tokens:good,callback:okCallback});
  assert.equal(h.second.state,'connected');assert.equal(h.replacedBeforeExchange,REDIRECT);assert.equal(h.session.getItem(PENDING_KEY),null);
  const token=h.calls.find(c=>c.url===ISSUER+'/oauth/token');const body=new URLSearchParams(token.options.body);
  assert.deepEqual(Object.fromEntries(body),{grant_type:'authorization_code',code:'synthetic-code',client_id:CLIENT,redirect_uri:REDIRECT,code_verifier:h.pending.verifier});
  assert.equal(token.options.credentials,'omit');assert.equal(token.options.redirect,'error');
  const client=h.mounts.at(-1).client;assert.equal(client.mode,'connected');assert.deepEqual(client.binding,binding);
  await client.queue();const rpc=h.calls.at(-1);assert.equal(rpc.url,ORIGIN+'/rest/v1/rpc/life_human_review_queue_v1');
  const sent=rpc.options.headers.Authorization.slice(7);assert.equal(JSON.parse(new TextDecoder().decode(b64urlDecode(sent.split('.')[1]))).client_id,CLIENT);
  assert.ok(!h.session.dump().includes('synthetic-refresh')&&!h.local.dump().includes('synthetic-refresh')&&!h.session.dump().includes(sent));
});

test('RS256 project keys are accepted through the same verification',async()=>{
  const header={alg:'RS256',kid:'rsa-1',typ:'JWT'};
  const h=await harness({callback:okCallback,tokens:async n=>({access_token:await sign(accessClaims(),{key:rsa.privateKey,header}),token_type:'bearer',id_token:await sign(idClaims(n),{key:rsa.privateKey,header})})});
  assert.equal(h.second.state,'connected');
});

test('invalid, expired and wrong-client sessions are denied and mount nothing',async()=>{
  const cases={
    'forged signature':async n=>({...(await good(n)),access_token:await sign(accessClaims(),{key:rogue.privateKey})}),
    'unsigned token':async n=>({...(await good(n)),access_token:await sign(accessClaims(),{header:{alg:'none',kid:'ec-1'}})}),
    'symmetric algorithm':async n=>({...(await good(n)),access_token:await sign(accessClaims(),{header:{alg:'HS256',kid:'ec-1'}})}),
    'embedded key header':async n=>({...(await good(n)),access_token:await sign(accessClaims(),{header:{alg:'ES256',kid:'ec-1',jku:'https://attacker.example.test'}})}),
    'unknown key':async n=>({...(await good(n)),access_token:await sign(accessClaims(),{header:{alg:'ES256',kid:'missing'}})}),
    'expired access':async n=>({...(await good(n)),access_token:await sign(accessClaims({exp:Math.floor(Date.now()/1000)-5}))}),
    'wrong issuer':async n=>({...(await good(n)),access_token:await sign(accessClaims({iss:'https://other.supabase.co/auth/v1'}))}),
    'wrong client claim':async n=>({...(await good(n)),access_token:await sign(accessClaims({client_id:'00000000-0000-4000-8000-000000000999'}))}),
    'no client claim':async n=>{const c=accessClaims();delete c.client_id;return {...(await good(n)),access_token:await sign(c)};},
    'conflicting nested client':async n=>({...(await good(n)),access_token:await sign(accessClaims({app_metadata:{client_id:'00000000-0000-4000-8000-000000000999'}}))}),
    'service role':async n=>({...(await good(n)),access_token:await sign(accessClaims({role:'service_role'}))}),
    'no session':async n=>({...(await good(n)),access_token:await sign(accessClaims({session_id:'not-a-uuid'}))}),
    'wrong audience':async n=>({...(await good(n)),access_token:await sign(accessClaims({aud:'other'}))}),
    'id token for another client':async n=>({...(await good(n)),id_token:await sign(idClaims(n,{aud:'00000000-0000-4000-8000-000000000999'}))}),
    'id token nonce replay':async n=>({...(await good(n)),id_token:await sign(idClaims('other-nonce'))}),
    'id token other subject':async n=>({...(await good(n)),id_token:await sign(idClaims(n,{sub:'00000000-0000-4000-8000-000000000999'}))}),
    'missing id token':async n=>{const t=await good(n);delete t.id_token;return t;}
  };
  for(const [name,tokens] of Object.entries(cases)){const h=await harness({tokens,callback:okCallback});assert.equal(h.second.state,'denied',name);assert.equal(h.views.at(-1).reason,'denied',name);assert.equal(h.mounts.length,0,name);assert.ok(!h.calls.some(c=>c.url.includes('/rest/v1/')),name);}
  const other=await harness({callback:okCallback,tokens:async n=>({...(await good(n)),access_token:await sign(accessClaims({sub:'00000000-0000-4000-8000-000000000999'})),id_token:await sign(idClaims(n,{sub:'00000000-0000-4000-8000-000000000999'}))})});
  assert.equal(other.second.state,'denied');assert.equal(other.views.at(-1).reason,'account');
  const leaked=await harness({callback:okCallback,tokens:good,jwks:{keys:[{...JWKS.keys[0],d:'private'}]}});assert.equal(leaked.second.state,'denied');
});

test('callback state, replay, refusal and outage handling',async()=>{
  const wrongState=await harness({tokens:good,callback:()=>({code:'synthetic-code',state:'forged'})});assert.equal(wrongState.second.state,'denied');assert.equal(wrongState.views.at(-1).reason,'stale');assert.ok(!wrongState.calls.some(c=>c.url.endsWith('/oauth/token')));
  const refused=await harness({tokens:good,callback:s=>({error:'access_denied',state:s})});assert.equal(refused.views.at(-1).reason,'refused');
  const injected=await harness({tokens:good,callback:s=>({code:'synthetic-code',state:s,client_id:'00000000-0000-4000-8000-000000000999'})});assert.equal(injected.second.state,'denied');
  const replay=await harness({tokens:good,callback:okCallback});const again=await startReviewHost({},config,{...replay.deps,location:{href:REDIRECT+'?code=synthetic-code&state='+replay.pending.state,origin:HOST}});assert.equal(again.state,'denied');
  for(const status of [500,503]){const down=await harness({tokens:good,callback:okCallback,tokenStatus:status});assert.equal(down.second.state,'disconnected');}
  const rejected=await harness({tokens:good,callback:okCallback,tokenStatus:400});assert.equal(rejected.second.state,'denied');
});

test('logout or a new session discards the client but never clears the decision journal',async()=>{
  const h=await harness({tokens:good,callback:okCallback});const first=h.mounts.at(-1);
  const journalKey='household-review/1/'+Object.values(binding).join('/')+'/00000000-0000-4000-8000-000000000501/00000000-0000-4000-8000-000000000601';
  h.local.setItem(journalKey,JSON.stringify({attemptId:'00000000-0000-4000-8000-000000000601',itemId:'00000000-0000-4000-8000-000000000501',expectedVersion:'1',state:'ready',startedAt:new Date().toISOString()}));
  h.second.signOut();assert.equal(h.second.state,'signed-out');assert.equal(first.destroyed,true);
  const before=h.calls.length;await assert.rejects(first.client.queue(),e=>e.kind==='denied');assert.equal(h.calls.length,before);
  assert.ok(h.local.getItem(journalKey));
  await h.second.signIn();assert.ok(h.local.getItem(journalKey));
  const pending=JSON.parse(h.session.getItem(PENDING_KEY));
  const next=await startReviewHost({},config,{...h.deps,location:{href:REDIRECT+'?code=synthetic-code-2&state='+pending.state,origin:HOST},fetchImpl:async(url,o)=>url.endsWith('/oauth/token')?Response.json(await good(pending.nonce)):h.deps.fetchImpl(url,o)});
  assert.equal(next.state,'connected');const fresh=h.mounts.at(-1);assert.notEqual(fresh.client,first.client);
  assert.ok(fresh.client.pending('00000000-0000-4000-8000-000000000501'));
  await assert.rejects(fresh.client.decide({itemId:'00000000-0000-4000-8000-000000000501',expectedVersion:'1',state:'ready',decisionRef:'human-review:synthetic',outcomeRef:null}),e=>e.kind==='uncertain');
  assert.ok(h.local.getItem(journalKey));
});

test('expiry signs out, destroys the desk and dispatches nothing further',async()=>{
  const h=await harness({tokens:good,callback:okCallback});const desk=h.mounts.at(-1);
  assert.ok(h.timers.at(-1).ms>3500000);h.timers.at(-1).f();
  assert.equal(h.second.state,'signed-out');assert.equal(h.views.at(-1).reason,'expired');assert.equal(desk.destroyed,true);
  const before=h.calls.length;await assert.rejects(desk.client.queue(),e=>e.kind==='denied');assert.equal(h.calls.length,before);
});
