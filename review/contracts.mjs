// Fixed human-review wire contract. Source records are data, never commands.
export const MAX_BYTES = 16_384;
export const STATES = ['proposed','ready','researching','blocked','review','scheduled','done','dismissed'];
const encoder = new TextEncoder();
export const bytes = value => encoder.encode(typeof value === 'string' ? value : JSON.stringify(value)).length;
const fail = () => { throw new Error('review_contract_invalid'); };
const check = value => { if (!value) fail(); };
const object = (v, keys) => { check(v && typeof v === 'object' && !Array.isArray(v)); check(Object.keys(v).length === keys.length && keys.every(k => Object.hasOwn(v,k))); };
const text = (v, max=512, nullable=false) => { if (nullable && v===null) return; check(typeof v==='string' && bytes(v)<=max && !v.includes('\0')); };
const bool = v => check(typeof v==='boolean');
const count = v => check(Number.isSafeInteger(v) && v>=0);
export const uuid = v => typeof v==='string' && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(v);
export const version = v => typeof v==='string' && /^[1-9][0-9]{0,18}$/.test(v) && BigInt(v)<=9223372036854775807n;
const instant = (v, nullable=false) => { if (nullable && v===null) return; check(typeof v==='string' && /^\d{4}-\d{2}-\d{2}T/.test(v) && Number.isFinite(Date.parse(v))); };
function ref(row,key,flag) { text(row[key],512,true); bool(row[flag]); if(row[flag])check(row[key]===null); }
function scope(v, expected) {
  object(v,['human_grant_id','auth_subject','upstream_client_id','session_id','board_id','board_key','actor_ref']);
  for(const k of ['human_grant_id','auth_subject','upstream_client_id','session_id','board_id'])check(uuid(v[k]));
  text(v.board_key,120); text(v.actor_ref,120);
  if(expected)for(const k of Object.keys(expected))check(v[k]===expected[k]);
}
function item(v, detail=false) {
  const base=['id','title','title_truncated','state','version','source_ref','source_ref_omitted','due_at','not_before','updated_at'];
  object(v,detail?[...base,'description','description_truncated','decision_ref','decision_ref_omitted','outcome_ref','outcome_ref_omitted','snoozed_until']:base);
  check(uuid(v.id)); text(v.title,512); bool(v.title_truncated); check(STATES.includes(v.state)); check(version(v.version));
  ref(v,'source_ref','source_ref_omitted'); instant(v.due_at,true);instant(v.not_before,true);instant(v.updated_at);
  if(detail){text(v.description,4096);bool(v.description_truncated);ref(v,'decision_ref','decision_ref_omitted');ref(v,'outcome_ref','outcome_ref_omitted');instant(v.snoozed_until,true);}
}
export function validatePacket(v, kind, expected) {
  check(bytes(v)<=MAX_BYTES);
  const extra=kind==='queue'?['items','next_after_id','has_more','coverage']:kind==='item'?['item','evidence','dependencies','activity','coverage']:['item','authority'];
  object(v,['contract','generated_at','scope',...extra]);check(v.contract==='life-human-review/1');instant(v.generated_at);scope(v.scope,expected);
  if(kind==='queue'){
    check(Array.isArray(v.items)&&v.items.length<=20);v.items.forEach(x=>item(x));
    check(new Set(v.items.map(x=>x.id)).size===v.items.length);
    check(v.items.every((x,i)=>i===0||v.items[i-1].id<x.id));
    bool(v.has_more);check(v.next_after_id===null||uuid(v.next_after_id));
    check(v.has_more ? v.items.length>0 && v.next_after_id===v.items.at(-1).id : v.next_after_id===null);
    object(v.coverage,['scope','items_omitted','external_sources_checked','snapshot_consistent_across_pages']);text(v.coverage.scope,2000);count(v.coverage.items_omitted);check(v.coverage.external_sources_checked===false&&v.coverage.snapshot_consistent_across_pages===false);
  }else if(kind==='item'){
    item(v.item,true);
    for(const name of ['evidence','dependencies','activity'])check(Array.isArray(v[name])&&v[name].length<=20);
    for(const e of v.evidence){object(e,['relation','source_store','source_kind','source_key','evidence_ref','observed_at','references_omitted']);text(e.relation,120);for(const k of ['source_store','source_kind','source_key','evidence_ref'])text(e[k],512,true);instant(e.observed_at,true);bool(e.references_omitted);}
    for(const d of v.dependencies){object(d,['id','title','title_truncated','state','version']);check(uuid(d.id));text(d.title,512);bool(d.title_truncated);check(STATES.includes(d.state)&&version(d.version));}
    for(const a of v.activity){object(a,['id','actor_ref','event_kind','evidence_ref','reference_omitted','recorded_at']);check(version(a.id));text(a.actor_ref,120);text(a.event_kind,120);ref(a,'evidence_ref','reference_omitted');instant(a.recorded_at);}
    object(v.coverage,['scope','evidence_omitted','dependencies_omitted','activity_omitted','external_sources_checked']);text(v.coverage.scope,2000);for(const k of ['evidence_omitted','dependencies_omitted','activity_omitted'])count(v.coverage[k]);check(v.coverage.external_sources_checked===false);
  }else if(kind==='decision'){
    object(v.item,['id','state','version','decision_ref','decision_ref_omitted','outcome_ref','outcome_ref_omitted']);check(uuid(v.item.id)&&version(v.item.version));check(['ready','done','dismissed'].includes(v.item.state));ref(v.item,'decision_ref','decision_ref_omitted');ref(v.item,'outcome_ref','outcome_ref_omitted');text(v.authority,2000);
  }else fail();
  return v;
}
export function validateDecision(v) {
  object(v,['itemId','expectedVersion','state','decisionRef','outcomeRef']);check(uuid(v.itemId)&&version(v.expectedVersion));check(['ready','done','dismissed'].includes(v.state));
  for(const k of ['decisionRef',...(v.state==='done'?['outcomeRef']:[])]){text(v[k],2048);check(v[k].trim().length>0&&v[k].trim()===v[k]&&[...v[k]].length<=2000);}
  if(v.state!=='done')check(v.outcomeRef===null);
  return v;
}
