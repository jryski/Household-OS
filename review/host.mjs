// Review host: example by default; optional dedicated human sign-in for the
// connected desk. Configuration comes only from the deployed host-config module,
// never from URL parameters, record text, model output or a worker.
import {mountReviewDesk} from './app.mjs';
import {createExampleClient} from './demo.mjs';
import {createHumanReviewClient,browserIntentStore} from './client.mjs';
import {uuid} from './contracts.mjs';
import {beginSignIn,completeSignIn,createJwksCache,isCallback,SignInError} from './oauth.mjs';

export const DEFAULT_HOST_CONFIG=Object.freeze({mode:'example'});
const BINDING=['human_grant_id','auth_subject','upstream_client_id','board_id'];
const CONNECTED=['mode','enabled','origin','publishableKey','oauthClientId','redirectUri','binding'];
const exactKeys=(v,keys)=>v!==null&&typeof v==='object'&&!Array.isArray(v)&&Object.keys(v).length===keys.length&&keys.every(k=>Object.hasOwn(v,k));

/** Returns {mode:'example'}, {mode:'disabled'} or a frozen connected config. Anything else throws. */
export function validateHostConfig(config=DEFAULT_HOST_CONFIG){
  if(exactKeys(config,['mode'])&&config.mode==='example')return DEFAULT_HOST_CONFIG;
  const invalid=()=>{throw new Error('review_host_config_invalid');};
  if(!exactKeys(config,CONNECTED)||config.mode!=='connected'||typeof config.enabled!=='boolean')invalid();
  if(config.enabled!==true)return Object.freeze({mode:'disabled'});
  const origin=new URL(config.origin);
  if(origin.protocol!=='https:'||!/^[a-z0-9]+\.supabase\.co$/.test(origin.hostname)||origin.port||config.origin!==origin.origin)invalid();
  if(!/^sb_publishable_[A-Za-z0-9_-]+$/.test(config.publishableKey)||!uuid(config.oauthClientId))invalid();
  const redirect=new URL(config.redirectUri);
  if(redirect.protocol!=='https:'||redirect.username||redirect.password||redirect.search||redirect.hash||redirect.href!==config.redirectUri||redirect.origin===origin.origin)invalid();
  if(!exactKeys(config.binding,BINDING)||!BINDING.every(k=>uuid(config.binding[k]))||config.binding.upstream_client_id!==config.oauthClientId)invalid();
  return Object.freeze({...config,binding:Object.freeze({...config.binding})});
}

/**
 * States: example, disabled, signed-out, connected, denied, disconnected.
 * The view renders panels; deps are injectable so offline tests need no browser.
 * The pending-decision journal is never cleared by sign-in, sign-out or expiry.
 */
export async function startReviewHost(root,rawConfig,deps={}){
  const d={mount:mountReviewDesk,createExample:createExampleClient,createClient:createHumanReviewClient,fetchImpl:globalThis.fetch,now:()=>Date.now(),setTimer:(f,ms)=>setTimeout(f,ms),clearTimer:t=>clearTimeout(t),view:domView,...deps};
  let current=null,desk=null,timer=null,state=null,config=null,keys=null,intentStore=null;
  const controller=Object.freeze({get state(){return state;},get desk(){return desk;},signIn,signOut});
  function teardown(){if(timer!==null)d.clearTimer(timer);timer=null;current=null;desk?.destroy();desk=null;}
  function show(name,detail={}){state=name;return d.view(root,name,{...detail,signIn,signOut});}
  async function signIn(){if(!keys)return;teardown();d.assign(await beginSignIn(config,{storage:d.sessionStorage,now:d.now}));}
  function signOut(reason='signed-out'){if(!keys)return;teardown();show('signed-out',{reason});}
  function connect(session){
    teardown();
    if(session.subject!==config.binding.auth_subject||session.clientId!==config.binding.upstream_client_id){show('denied',{reason:'account'});return;}
    current=session;const bound=session;
    // The client is bound to this exact verified session. Sign-out, expiry or a
    // new sign-in discards it, so a changed session always gets a fresh desk.
    const getVerifiedSession=async()=>{
      if(current!==bound)return null;
      if(bound.expiresAt<=d.now()/1000){signOut('expired');return null;}
      return bound;
    };
    const client=d.createClient({origin:config.origin,publishableKey:config.publishableKey,binding:config.binding,getVerifiedSession,intentStore,fetchImpl:d.fetchImpl});
    desk=d.mount(show('connected'),client);
    timer=d.setTimer(()=>{if(current===bound)signOut('expired');},Math.max(0,bound.expiresAt*1000-d.now()));
  }

  try{config=validateHostConfig(rawConfig);}catch{show('disconnected',{reason:'config'});return controller;}
  if(config.mode==='example'){state='example';desk=d.mount(root,await d.createExample());return controller;}
  if(config.mode==='disabled'){show('disconnected',{reason:'disabled'});return controller;}
  if(d.location.origin!==new URL(config.redirectUri).origin){show('disconnected',{reason:'origin'});return controller;}
  keys=createJwksCache({origin:config.origin,fetchImpl:d.fetchImpl});
  intentStore=browserIntentStore(d.localStorage);
  if(isCallback(config,d.location.href)){
    const href=d.location.href;
    d.replaceUrl(config.redirectUri); // strip the one-time code before any await
    try{connect(await completeSignIn(config,{href,storage:d.sessionStorage,fetchImpl:d.fetchImpl,keys,now:d.now}));}
    catch(e){const kind=e instanceof SignInError?e.kind:'denied';if(kind==='unavailable')show('disconnected',{reason:'unavailable'});else show('denied',{reason:kind});}
    return controller;
  }
  show('signed-out',{reason:'start'});
  return controller;
}

const TEXT={
  disconnected:{config:'Connected review is not configured correctly, so it stays off. No account is connected.',disabled:'Connected review is turned off. No account is connected.',origin:'This page is not the configured review host. No account is connected.',unavailable:'The sign-in service could not be reached. No account is connected.'},
  'signed-out':{start:'Sign in with the dedicated review account to see your permitted board.','signed-out':'You signed out. Sign in again to continue reviewing.',expired:'Your sign-in expired. Sign in again; open decisions stay protected.'},
  denied:{account:'This account is not the configured reviewer for this board.',refused:'Sign-in was cancelled.',stale:'That sign-in link expired or was already used. Start again.',denied:'Sign-in could not be verified. Start again.'}
};
function domView(root,name,{reason,signIn,signOut}){
  const el=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text)n.textContent=text;return n;};
  const button=(text,fn)=>{const b=el('button','button primary',text);b.type='button';b.addEventListener('click',()=>{b.disabled=true;Promise.resolve(fn()).catch(()=>{b.disabled=false;});});return b;};
  if(name==='connected'){
    const bar=el('div','host-bar');bar.append(el('span','quiet','Signed in with the dedicated review account.'),button('Sign out',()=>signOut()));
    const desk=el('div','host-desk');root.replaceChildren(bar,desk);return desk;
  }
  const panel=el('main','host-panel');panel.append(el('h1',null,'Household review'),el('p',null,TEXT[name]?.[reason]??'No account is connected.'));
  if(name==='signed-out'||name==='denied')panel.append(button('Sign in',signIn));
  root.replaceChildren(panel);
}
