import {MAX_BYTES,bytes,uuid,validatePacket,validateDecision,version} from './contracts.mjs';

export class ReviewError extends Error {
  constructor(kind, message) { super(message);this.name='ReviewError';this.kind=kind; }
}
const messages={denied:'Your review access is unavailable. Sign in again or ask the operator to check your permission.',conflict:'This task changed. Reload it and review the current record before deciding.',rejected:'The decision was rejected. Check its details before making a new decision.',unavailable:'The review connection is unavailable. Try loading the record again.',invalid:'The response did not match the review contract. No decision has been confirmed.',uncertain:'The decision result is unknown. Inspect the current record before taking another action.'};
const internalErrors=new WeakSet();
function error(kind){const e=new ReviewError(kind,messages[kind]);internalErrors.add(e);return e;}
async function readBounded(response) {
  if(!/^application\/json(?:\s*;|\s*$)/i.test(response.headers.get('Content-Type')||''))throw error('invalid');
  if(!response.body?.getReader)throw error('invalid');
  const reader=response.body.getReader();const chunks=[];let size=0;
  try{while(true){const {value,done}=await reader.read();if(done)break;size+=value.byteLength;if(size>MAX_BYTES)throw error('invalid');chunks.push(value);}}
  finally{try{await reader.cancel();}catch{}}
  const all=new Uint8Array(size);let offset=0;for(const c of chunks){all.set(c,offset);offset+=c.byteLength;}
  return JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(all));
}

/**
 * Connect only from a trusted host with a dedicated human OAuth session.
 * This browser module does not establish peer identity or authenticate humans.
 * The host verifies the session; the SQL boundary independently checks it.
 */
export function createHumanReviewClient({origin,publishableKey,binding,getVerifiedSession,intentStore,fetchImpl=globalThis.fetch,deadlineMs=10000}) {
  const url=new URL(origin);
  if(url.protocol!=='https:'||!/^([a-z0-9]+)\.supabase\.co$/.test(url.hostname)||url.port||url.pathname!=='/'||url.search||url.hash||url.username||url.password)throw error('invalid');
  if(!/^sb_publishable_[A-Za-z0-9_-]+$/.test(publishableKey)||typeof getVerifiedSession!=='function'||!['list','set','remove'].every(k=>typeof intentStore?.[k]==='function')||!Number.isInteger(deadlineMs)||deadlineMs<100||deadlineMs>30000)throw error('invalid');
  const expected=Object.freeze({...binding});
  const keys=['human_grant_id','auth_subject','upstream_client_id','board_id'];
  if(Object.keys(expected).length!==keys.length||!keys.every(k=>uuid(expected[k])))throw error('invalid');
  const journalKey=id=>'household-review/1/'+keys.map(k=>expected[k]).join('/')+'/'+id;
  function pending(id){if(!uuid(id))throw error('invalid');try{const entries=intentStore.list(journalKey(id)+'/');if(!Array.isArray(entries)||entries.length>64)throw error('invalid');for(const {key,value} of entries){const v=JSON.parse(value);if(!v||Object.keys(v).sort().join(',')!=='attemptId,expectedVersion,itemId,startedAt,state'||v.itemId!==id||!uuid(v.attemptId)||key!==journalKey(id)+'/'+v.attemptId||!version(v.expectedVersion)||!['ready','done','dismissed'].includes(v.state)||!Number.isFinite(Date.parse(v.startedAt)))throw error('invalid');}return entries.length?JSON.parse(entries[0].value):null;}catch{throw error('unavailable');}}
  async function call(name,args,kind,{signal}={}) {
    const controller=new AbortController();let dispatched=false;
    const abort=()=>controller.abort();signal?.addEventListener('abort',abort,{once:true});if(signal?.aborted)abort();
    let timer;const stop=new Promise((_,reject)=>{timer=setTimeout(()=>{abort();reject(error(dispatched&&kind==='decision'?'uncertain':'unavailable'));},deadlineMs);controller.signal.addEventListener('abort',()=>reject(error(dispatched&&kind==='decision'?'uncertain':'unavailable')),{once:true});});
    const work=async()=>{
      const session=await getVerifiedSession();
      if(controller.signal.aborted)throw error('unavailable');
      if(!session||session.verified!==true||session.role!=='authenticated'||session.subject!==expected.auth_subject||session.clientId!==expected.upstream_client_id||!uuid(session.sessionId)||!Number.isFinite(session.expiresAt)||session.expiresAt<=Date.now()/1000||typeof session.accessToken!=='string'||session.accessToken.length>12288||!/^[-A-Za-z0-9_]+\.[-A-Za-z0-9_]+\.[-A-Za-z0-9_]+$/.test(session.accessToken))throw error('denied');
      const scope={...expected,session_id:session.sessionId};
      const payload=JSON.stringify({p_human_grant_id:expected.human_grant_id,...args});if(bytes(payload)>8192)throw error('invalid');
      dispatched=true;
      const response=await fetchImpl(url.origin+'/rest/v1/rpc/'+name,{method:'POST',headers:{apikey:publishableKey,Authorization:'Bearer '+session.accessToken,'Content-Type':'application/json',Accept:'application/json'},body:payload,signal:controller.signal,credentials:'omit',redirect:'error',cache:'no-store',referrerPolicy:'no-referrer'});
      if(!response.ok){if([401,403].includes(response.status))throw error('denied');if(response.status===409)throw error('conflict');if(response.status===400)throw error('rejected');throw error(kind==='decision'?'uncertain':'unavailable');}
      const result=validatePacket(await readBounded(response),kind,scope);
      if(controller.signal.aborted)throw error(kind==='decision'?'uncertain':'unavailable');
      return result;
    };
    try{return await Promise.race([work(),stop]);}
    catch(e){let safe=internalErrors.has(e)?error(e.kind):error(dispatched&&kind==='decision'?'uncertain':'invalid');if(dispatched&&kind==='decision'&&safe.kind==='invalid')safe=error('uncertain');safe.dispatched=dispatched;throw safe;}
    finally{clearTimeout(timer);signal?.removeEventListener('abort',abort);}
  }
  return Object.freeze({
    mode:'connected',binding:expected,
    pending,
    queue:({after=null,signal}={})=>{if(after!==null&&!uuid(after))throw error('invalid');return call('life_human_review_queue_v1',{p_after_id:after,p_limit:10},'queue',{signal});},
    item:(id,{signal}={})=>{if(!uuid(id))throw error('invalid');return call('life_human_review_item_v1',{p_item_id:id,p_limit:10},'item',{signal});},
    decide:async(input,{signal}={})=>{
      try{validateDecision(input);}catch{throw error('rejected');}if(pending(input.itemId))throw error('uncertain');
      // Each attempt has its own journal key. A concurrent rejected tab cannot
      // erase another tab's unknown result. Server version CAS remains final.
      const attemptId=globalThis.crypto.randomUUID();const key=journalKey(input.itemId)+'/'+attemptId;const intent=JSON.stringify({attemptId,itemId:input.itemId,expectedVersion:input.expectedVersion,state:input.state,startedAt:new Date().toISOString()});
      try{intentStore.set(key,intent);if(!intentStore.list(journalKey(input.itemId)+'/').some(x=>x.key===key&&x.value===intent))throw error('unavailable');}catch{throw error('unavailable');}
      try{
        const result=await call('life_human_decide_work_v1',{p_item_id:input.itemId,p_expected_version:input.expectedVersion,p_state:input.state,p_decision_ref:input.decisionRef,p_outcome_ref:input.outcomeRef},'decision',{signal});
        if(result.item.id!==input.itemId||result.item.state!==input.state||BigInt(result.item.version)!==BigInt(input.expectedVersion)+1n)throw error('uncertain');
        intentStore.remove(key);return result;
      }catch(e){try{if(e.dispatched===false||['denied','conflict','rejected'].includes(e.kind))intentStore.remove(key);}catch{throw error('uncertain');}throw e instanceof ReviewError?e:error('uncertain');}
    }
  });
}

// Stores only minimal pending-decision metadata, never credentials or note text.
export function browserIntentStore(storage) {
  if(!storage||!['key','getItem','setItem','removeItem'].every(k=>typeof storage[k]==='function'))throw error('invalid');
  return Object.freeze({list:prefix=>{if(storage.length>10000)throw error('unavailable');const found=[];for(let i=0;i<storage.length;i++){const key=storage.key(i);if(key?.startsWith(prefix))found.push({key,value:storage.getItem(key)});}return found;},set:(key,value)=>storage.setItem(key,value),remove:key=>storage.removeItem(key)});
}

export function safeDecision(input) { return validateDecision(input); }
