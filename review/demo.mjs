import {bytes,validatePacket,validateDecision} from './contracts.mjs';
import {ReviewError} from './client.mjs';

export async function createExampleClient(fetchImpl=globalThis.fetch) {
  const response=await fetchImpl('/fixtures/furnace-baseline.json',{cache:'no-store'});
  if(!response.ok)throw new Error('example_unavailable');
  const fixture=await response.json();
  if(fixture.contract!=='household-maintenance-package/1'||fixture.synthetic!==true||fixture.preparation_only!==true)throw new Error('example_invalid');
  const scope={human_grant_id:'00000000-0000-4000-8000-000000000301',auth_subject:'00000000-0000-4000-8000-000000000001',upstream_client_id:'00000000-0000-4000-8000-000000000102',session_id:'00000000-0000-4000-8000-000000000302',board_id:fixture.item_links[0].board_id,board_key:fixture.proposal.arguments.p_board_key,actor_ref:'human:example'};
  const p=fixture.preview.item;
  const row={id:p.id,title:p.title,title_truncated:false,description:fixture.proposed_finding.summary+'\n\n'+fixture.proposed_finding.requested_evidence,description_truncated:false,state:p.state,version:String(p.version),source_ref:p.source_ref,source_ref_omitted:false,decision_ref:null,decision_ref_omitted:false,outcome_ref:null,outcome_ref_omitted:false,due_at:null,not_before:null,snoozed_until:null,updated_at:'2030-01-15T12:00:00Z'};
  const envelope=()=>({contract:'life-human-review/1',generated_at:new Date().toISOString(),scope:structuredClone(scope)});
  const evidence=fixture.preview.evidence.map(({relation,source_store,source_kind,source_key,evidence_ref,observed_at,references_omitted})=>({relation,source_store,source_kind,source_key,evidence_ref,observed_at,references_omitted}));
  return Object.freeze({
    mode:'example',binding:scope,pending:()=>null,
    async queue(){const {description,description_truncated,decision_ref,decision_ref_omitted,outcome_ref,outcome_ref_omitted,snoozed_until,...short}=row;return validatePacket({...envelope(),items:['done','dismissed'].includes(row.state)?[]:[structuredClone(short)],next_after_id:null,has_more:false,coverage:{scope:'Invented furnace baseline; one example task.',items_omitted:0,external_sources_checked:false,snapshot_consistent_across_pages:false}},'queue');},
    async item(id){if(id!==row.id)throw new ReviewError('denied','Example task unavailable.');return validatePacket({...envelope(),item:structuredClone(row),evidence:structuredClone(evidence),dependencies:[],activity:[],coverage:{scope:'Invented references only. No household source has been opened.',evidence_omitted:0,dependencies_omitted:0,activity_omitted:0,external_sources_checked:false}},'item');},
    async decide(input){validateDecision(input);if(input.itemId!==row.id||input.expectedVersion!==row.version)throw new ReviewError('conflict','This example changed. Reload it before making another choice.');row.state=input.state;row.version=String(BigInt(row.version)+1n);row.decision_ref=bytes(input.decisionRef)<=512?input.decisionRef:null;row.decision_ref_omitted=row.decision_ref===null;row.outcome_ref=input.outcomeRef===null||bytes(input.outcomeRef)<=512?input.outcomeRef:null;row.outcome_ref_omitted=input.outcomeRef!==null&&row.outcome_ref===null;row.updated_at=new Date().toISOString();return validatePacket({...envelope(),item:{id:row.id,state:row.state,version:row.version,decision_ref:row.decision_ref,decision_ref_omitted:row.decision_ref_omitted,outcome_ref:row.outcome_ref,outcome_ref_omitted:row.outcome_ref_omitted},authority:'Example choice only. No household record changed.'},'decision');}
  });
}
