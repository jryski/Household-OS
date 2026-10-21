import {validatePacket} from './contracts.mjs';
import {ReviewError} from './client.mjs';

const labels={proposed:'Suggested',ready:'Ready for research',researching:'Research in progress',blocked:'Waiting for information',review:'Ready for review',scheduled:'Scheduled',done:'Completed',dismissed:'Dismissed'};
function el(tag,attrs={},...children){const n=document.createElement(tag);for(const [k,v] of Object.entries(attrs)){if(k==='class')n.className=v;else if(k==='text')n.textContent=v;else if(k.startsWith('on'))n.addEventListener(k.slice(2),v);else if(v!==false&&v!==undefined)n.setAttribute(k,String(v));}for(const child of children.flat())if(child!==null&&child!==undefined)n.append(child instanceof Node?child:document.createTextNode(String(child)));return n;}
const icon=()=>{const s=document.createElementNS('http://www.w3.org/2000/svg','svg');s.setAttribute('viewBox','0 0 32 32');s.setAttribute('aria-hidden','true');const p=document.createElementNS(s.namespaceURI,'path');p.setAttribute('d','M5 16 16 6l11 10v11H7V16m6 11v-8h7v8');p.setAttribute('fill','none');p.setAttribute('stroke','currentColor');p.setAttribute('stroke-width','1.7');p.setAttribute('stroke-linecap','round');p.setAttribute('stroke-linejoin','round');s.append(p);return s;};
const message=e=>e instanceof ReviewError?e.message:'This record could not load. Reload it to try again.';

/** Host supplies a trusted client. URL parameters and record text cannot bind it. */
export function mountReviewDesk(root,client) {
  if(!root||!client.binding||!['example','connected'].includes(client?.mode)||!['queue','item','decide','pending'].every(k=>typeof client[k]==='function'))throw new Error('review_host_invalid');
  let selected=null,queueItems=[],queueCursor=null,detailGeneration=0,queueGeneration=0,detailController=null,queueController=null,currentPacket=null,uncertain=new Set(),busy=false;
  const example=client.mode==='example';
  const shell=el('main',{class:'shell'});
  const top=el('header',{class:'top'},el('div',{class:'brand'},icon(),el('h1',{text:'Household review'})),el('span',{class:'mode'+(example?'':' connected'),text:example?'Example workspace':'Connected workspace'}));
  const intro=el('p',{class:'intro',text:example?'Invented records for a walkthrough. Choices here do not change your household.':'Review the available evidence, then make a deliberate decision. This screen does not carry out household work.'});
  const list=el('div',{class:'queue-list'}),queueStatus=el('p',{class:'quiet','role':'status','aria-live':'polite'});
  const reload=el('button',{class:'button small',type:'button',text:'Reload tasks',onclick:()=>loadQueue(false)});
  const more=el('button',{class:'button small',type:'button',text:'Load more',hidden:true,onclick:()=>loadQueue(true)});
  const queue=el('aside',{class:'queue','aria-label':'Tasks'},el('h2',{text:'Needs a decision'}),el('p',{class:'quiet queue-description',text:example?'Home maintenance · example':'Open work in your permitted board'}),list,queueStatus,el('div',{class:'queue-tools'},reload,more));
  const detail=el('section',{class:'detail',id:'task-detail','aria-label':'Selected task',tabindex:'-1'});
  shell.append(top,intro,el('div',{class:'workbench'},queue,detail),el('footer',{class:'footer',text:example?'No account is connected. The maintenance example leaves service timing unknown.':'Only the permitted records shown here are included. Listed sources have not been opened or independently verified.'}));root.replaceChildren(shell);

  function showQueue(){shell.classList.remove('show-detail');list.querySelector(`[data-item="${selected}"]`)?.focus();}
  function renderList(){list.replaceChildren();for(const item of queueItems){const status=el('span',{class:'task-status '+item.state},el('span',{class:'dot'}),labels[item.state]);list.append(el('button',{type:'button',class:'task-button','data-item':item.id,'aria-current':item.id===selected?'true':'false',onclick:()=>loadItem(item.id,true)},el('span',{class:'task-name',text:item.title}),status));}if(!queueItems.length)list.append(el('p',{class:'empty',text:'Nothing is waiting here. Reload when a new suggestion is available.'}));}
  async function loadQueue(append){
    if(busy)return;const generation=++queueGeneration;queueController?.abort();queueController=new AbortController();reload.disabled=true;more.disabled=true;queueStatus.textContent='Loading tasks…';
    try{const packet=validatePacket(await client.queue({after:append?queueCursor:null,signal:queueController.signal}),'queue',client.binding);if(generation!==queueGeneration)return;
      queueItems=append?[...queueItems,...packet.items.filter(x=>!queueItems.some(y=>x.id===y.id))]:packet.items;queueCursor=packet.next_after_id;more.hidden=!packet.has_more;queueStatus.textContent=packet.has_more?'More tasks are available. The list is a page of current work.':(packet.coverage.items_omitted?'Some tasks are not included in this page.':'');renderList();
      if(!selected&&queueItems.length){selected=queueItems[0].id;renderList();await loadItem(selected,false);}else if(!selected)detail.replaceChildren(el('p',{class:'empty',text:'Choose a task to review its available evidence.'}));
    }catch(e){if(generation===queueGeneration)queueStatus.textContent=message(e);}finally{if(generation===queueGeneration){reload.disabled=false;more.disabled=false;}}
  }
  async function loadItem(id,focus){
    if(busy)return;const generation=++detailGeneration;detailController?.abort();detailController=new AbortController();selected=id;currentPacket=null;renderList();detail.replaceChildren(el('p',{class:'loading',role:'status',text:'Loading the task…'}));if(focus)shell.classList.add('show-detail');
    try{const packet=validatePacket(await client.item(id,{signal:detailController.signal}),'item',client.binding);if(generation!==detailGeneration)return;if(packet.item.id!==id)throw new Error('scope_mismatch');currentPacket=packet;if(client.pending(id))uncertain.add(id);renderDetail(packet);if(focus){detail.focus({preventScroll:true});if(matchMedia('(max-width:850px)').matches)detail.scrollIntoView({block:'start'});}}
    catch(e){if(generation===detailGeneration)detail.replaceChildren(el('button',{class:'button text mobile-back',type:'button',text:'Back to tasks',onclick:showQueue}),el('p',{class:'status error',role:'alert',text:message(e)}),el('button',{class:'button',type:'button',text:'Reload task',onclick:()=>loadItem(id,false)}));}
  }
  function renderDetail(packet){
    const {item}=packet;const title=el('h2',{text:item.title});const content=el('div',{class:'task-enter'},el('div',{class:'detail-status'},el('span',{class:'dot'}),labels[item.state]),title,el('p',{class:'description',text:item.description||'No description is included.'}));
    if(item.title_truncated||item.description_truncated||item.source_ref_omitted||item.decision_ref_omitted||item.outcome_ref_omitted||packet.evidence.some(e=>e.references_omitted)||packet.activity.some(a=>a.reference_omitted)||packet.dependencies.some(d=>d.title_truncated))content.append(el('div',{class:'coverage'},el('p',{text:'Some task information was shortened or omitted. Review the complete source before relying on it.'})));
    const evidence=el('ul',{class:'evidence-list'});
    for(const row of packet.evidence)evidence.append(el('li',{},el('span',{class:'evidence-kind',text:row.source_kind==='maintenance-workflow'?'Maintenance request':row.source_kind||'Supporting record'}),el('span',{class:'reference',text:row.evidence_ref??(row.references_omitted?'Reference omitted':'Reference not provided')})));
    const section=el('section',{class:'section'},el('h3',{text:'Available evidence'}),evidence,el('p',{class:'quiet source-note',text:packet.evidence.length?'These are record references. Their contents have not been opened by this screen.':'No supporting record is included yet.'}));
    if(item.source_ref)section.append(el('span',{class:'reference',text:'Suggestion source: '+item.source_ref}));content.append(section);
    if(item.decision_ref||item.outcome_ref){const recorded=el('section',{class:'section'},el('h3',{text:'Recorded decision'}));if(item.decision_ref)recorded.append(el('p',{class:'reference',text:item.decision_ref}));if(item.outcome_ref)recorded.append(el('p',{class:'reference',text:'Completion record: '+item.outcome_ref}));content.append(recorded);}
    const omitted=packet.coverage.evidence_omitted+packet.coverage.dependencies_omitted+packet.coverage.activity_omitted;
    if(omitted)content.append(el('div',{class:'coverage'},el('p',{text:`This view omits ${omitted} supporting entries. It does not establish that the record is complete.`})));
    if(packet.dependencies.length){const ul=el('ul',{class:'history-list'});for(const d of packet.dependencies)ul.append(el('li',{text:d.title+' · '+labels[d.state]}));content.append(el('section',{class:'section'},el('h3',{text:'Other work this depends on'}),ul));}
    const history=el('ul',{class:'history-list'});for(const a of packet.activity)history.append(el('li',{},el('span',{text:a.event_kind.replaceAll('_',' ')+' · '+a.actor_ref}),el('span',{class:'reference',text:a.evidence_ref??(a.reference_omitted?'Reference omitted':'No reference included')})));
    content.append(el('details',{class:'details'},el('summary',{text:'Show recorded activity'}),packet.activity.length?history:el('p',{class:'quiet',text:'No activity is included in this view.'})));
    const status=el('div',{class:'status',role:'status','aria-live':'polite'});
    if(uncertain.has(item.id)){status.classList.add('error');status.textContent='A previous decision has an unknown result. You can inspect this record, but another decision is blocked until the operator reconciles it.';}
    if(!['done','dismissed'].includes(item.state))content.append(decisionForm(packet,status));else content.append(el('p',{class:'status',text:example?'This example choice is complete. Reload the preview page to start over.':'This task is closed. A correction needs a new proposal.'}));
    content.append(status,el('button',{class:'button text',type:'button',text:'Reload this record',onclick:()=>loadItem(item.id,false)}));
    detail.replaceChildren(el('button',{class:'button text mobile-back',type:'button',text:'Back to tasks',onclick:showQueue}),content);
  }
  function decisionForm(packet,status){
    const rendered=Object.freeze({id:packet.item.id,version:packet.item.version});
    const select=el('select',{id:'decision-action',required:true},el('option',{value:'',text:'Choose an action'}),el('option',{value:'ready',text:'Allow research'}),el('option',{value:'done',text:'Record completion'}),el('option',{value:'dismissed',text:'Dismiss suggestion'}));
    const note=el('textarea',{id:'decision-note',rows:'3',required:true,maxlength:'2000',placeholder:'Add your reason or a supporting record reference.'});
    const outcome=el('textarea',{id:'outcome-note',rows:'3',maxlength:'2000',placeholder:'Describe what was completed, or provide the outcome record reference.'});
    const outcomeField=el('div',{class:'field',hidden:true},el('label',{for:'outcome-note',text:'Completion record'}),outcome,el('span',{class:'help',text:'Completion needs evidence of an outcome, not a plan.'}));
    const submit=el('button',{class:'button primary',type:'submit',text:example?'Try this decision':'Record decision'});
    const fieldset=el('fieldset',{class:'decision-fields'},el('div',{class:'field'},el('label',{for:'decision-action',text:'Your action'}),select),el('div',{class:'field'},el('label',{for:'decision-note',text:'Decision record'}),note),outcomeField,el('div',{class:'decision-actions'},submit,el('span',{class:'decision-note',text:example?'This only changes the example in this tab.':'This records a decision. It does not buy, book, schedule or carry out work.'})));
    fieldset.disabled=uncertain.has(rendered.id);
    for(const control of [note,outcome])control.addEventListener('input',()=>control.setCustomValidity(new TextEncoder().encode(control.value.trim()).length>2048?'Use a shorter note or a reference to the complete record.':''));
    select.addEventListener('change',()=>{outcomeField.hidden=select.value!=='done';outcome.required=select.value==='done';if(!outcome.required){outcome.value='';outcome.setCustomValidity('');}});
    const form=el('form',{class:'decision'},el('h3',{text:'Your decision'}),el('p',{class:'quiet',text:'Choose an action after reviewing what is known and what is missing.'}),fieldset);
    form.addEventListener('submit',async event=>{
      event.preventDefault();if(busy||uncertain.has(rendered.id)||!form.reportValidity()||selected!==rendered.id||currentPacket?.item.version!==rendered.version)return;
      // Deliberate form input only. Record text never chooses or fills an action.
      const input={itemId:rendered.id,expectedVersion:rendered.version,state:select.value,decisionRef:note.value.trim(),outcomeRef:select.value==='done'?outcome.value.trim():null};
      busy=true;fieldset.disabled=true;reload.disabled=true;more.disabled=true;status.classList.remove('error');status.textContent=example?'Trying the example decision…':'Recording your decision…';
      try{const result=validatePacket(await client.decide(input),'decision',client.binding);if(result.item.id!==rendered.id||result.item.state!==input.state||BigInt(result.item.version)!==BigInt(rendered.version)+1n)throw new ReviewError('uncertain','The decision result did not match the request. Inspect the current record before taking another action.');
        busy=false;await loadItem(rendered.id,false);const current=detail.querySelector('.status[role=status]');if(current)current.textContent=example?'Example choice applied. No household record changed.':'Decision recorded. No external action was performed.';await loadQueue(false);
      }catch(e){busy=false;status.classList.add('error');status.textContent=message(e);let pending=true;try{pending=!!client.pending(rendered.id);}catch{}if(e.kind==='uncertain'||pending){uncertain.add(rendered.id);fieldset.disabled=true;}else if(e.kind==='conflict'){fieldset.disabled=true;}else fieldset.disabled=false;}
      finally{busy=false;reload.disabled=false;more.disabled=false;}
    });return form;
  }
  detail.append(el('p',{class:'empty',text:'Choose a task to review its available evidence.'}));loadQueue(false);
  return Object.freeze({reload:()=>loadQueue(false),destroy(){detailController?.abort();queueController?.abort();root.replaceChildren();}});
}
