// Dedicated human sign-in for the review host: Supabase Auth OAuth 2.1
// authorization code flow with PKCE as a public client. Tokens are verified
// with WebCrypto against the pinned project's JWKS. Decoding alone never
// produces a verified session, and no token is persisted or logged.
import {uuid} from './contracts.mjs';

export const PENDING_KEY='household-review-signin/1';
export const MAX_TOKEN=12288;
const MAX_JSON=32768,PENDING_MAX_AGE_MS=10*60*1000,SKEW_S=60;
const ALGS=Object.freeze({
  ES256:{kty:'EC',crv:'P-256',sigBytes:64,importAlg:{name:'ECDSA',namedCurve:'P-256'},verifyAlg:{name:'ECDSA',hash:'SHA-256'}},
  RS256:{kty:'RSA',sigBytes:null,importAlg:{name:'RSASSA-PKCS1-v1_5',hash:'SHA-256'},verifyAlg:{name:'RSASSA-PKCS1-v1_5'}}
});

export class SignInError extends Error {
  constructor(kind){super('sign_in_'+kind);this.name='SignInError';this.kind=kind;}
}
const fail=kind=>{throw new SignInError(kind);};
const plainObject=v=>v!==null&&typeof v==='object'&&!Array.isArray(v);

export function b64urlDecode(s){
  if(typeof s!=='string'||!/^[A-Za-z0-9_-]+$/.test(s)||s.length%4===1)fail('denied');
  const bin=atob(s.replaceAll('-','+').replaceAll('_','/')+'='.repeat((4-s.length%4)%4));
  return Uint8Array.from(bin,c=>c.charCodeAt(0));
}
export function b64urlEncode(bytes){let s='';for(const b of bytes)s+=String.fromCharCode(b);return btoa(s).replaceAll('+','-').replaceAll('/','_').replace(/=+$/,'');}
const json=bytes=>{try{return JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(bytes));}catch{return fail('denied');}};

async function readJson(response,max=MAX_JSON){
  if(!/^application\/json(?:\s*;|\s*$)/i.test(response.headers.get('Content-Type')||''))fail('unavailable');
  const text=await response.text();if(new TextEncoder().encode(text).length>max)fail('unavailable');
  try{return JSON.parse(text);}catch{return fail('unavailable');}
}
const fetchOptions={credentials:'omit',redirect:'error',cache:'no-store',referrerPolicy:'no-referrer'};

/** Pinned-origin JWKS cache. An unknown key id triggers at most one refetch per lookup. */
export function createJwksCache({origin,fetchImpl=globalThis.fetch,subtle=globalThis.crypto.subtle}){
  const url=origin+'/auth/v1/.well-known/jwks.json';let keys=null;const imported=new Map();
  async function load(){
    let response;try{response=await fetchImpl(url,{method:'GET',headers:{Accept:'application/json'},...fetchOptions});}catch{fail('unavailable');}
    if(!response.ok)fail('unavailable');const body=await readJson(response,16384);
    if(!plainObject(body)||!Array.isArray(body.keys)||body.keys.length>16)fail('unavailable');keys=body.keys;imported.clear();
  }
  return Object.freeze({async get(kid,alg){
    const spec=ALGS[alg];
    for(let attempt=0;attempt<2;attempt++){
      if(!keys||attempt===1)await load();
      const jwk=keys.find(k=>plainObject(k)&&k.kid===kid);if(!jwk)continue;
      if('d' in jwk||'k' in jwk||jwk.kty!==spec.kty||(spec.crv&&jwk.crv!==spec.crv)||(jwk.alg!==undefined&&jwk.alg!==alg)||(jwk.use!==undefined&&jwk.use!=='sig'))fail('denied');
      const cacheKey=alg+'/'+kid;if(!imported.has(cacheKey)){
        const pub=spec.kty==='EC'?{kty:'EC',crv:jwk.crv,x:jwk.x,y:jwk.y}:{kty:'RSA',n:jwk.n,e:jwk.e};
        try{imported.set(cacheKey,await subtle.importKey('jwk',pub,spec.importAlg,false,['verify']));}catch{fail('denied');}
      }
      return imported.get(cacheKey);
    }
    return fail('denied');
  }});
}

/** Verify JWS signature, issuer and time claims. Returns the payload only after WebCrypto verification. */
export async function verifyJwt(token,{keys,issuer,now=()=>Date.now(),subtle=globalThis.crypto.subtle}){
  if(typeof token!=='string'||token.length>MAX_TOKEN)fail('denied');
  const parts=token.split('.');if(parts.length!==3)fail('denied');
  const header=json(b64urlDecode(parts[0]));
  if(!plainObject(header)||!Object.keys(header).every(k=>['alg','kid','typ'].includes(k))||!Object.hasOwn(ALGS,header.alg)||typeof header.kid!=='string'||header.kid.length<1||header.kid.length>256||(header.typ!==undefined&&header.typ!=='JWT'))fail('denied');
  const spec=ALGS[header.alg];const signature=b64urlDecode(parts[2]);if(spec.sigBytes&&signature.length!==spec.sigBytes)fail('denied');
  const key=await keys.get(header.kid,header.alg);
  let ok=false;try{ok=await subtle.verify(spec.verifyAlg,key,signature,new TextEncoder().encode(parts[0]+'.'+parts[1]));}catch{ok=false;}
  if(!ok)fail('denied');
  const payload=json(b64urlDecode(parts[1]));const t=now()/1000;
  if(!plainObject(payload)||payload.iss!==issuer||!Number.isSafeInteger(payload.exp)||payload.exp<=t||(payload.nbf!==undefined&&(!Number.isFinite(payload.nbf)||payload.nbf>t+SKEW_S))||(payload.iat!==undefined&&(!Number.isFinite(payload.iat)||payload.iat>t+SKEW_S)))fail('denied');
  return payload;
}
const audienceIs=(aud,value)=>aud===value||(Array.isArray(aud)&&aud.length===1&&aud[0]===value);

/** Start the supported authorization request. Only the one-time PKCE verifier, state and nonce are stored. */
export async function beginSignIn(config,{storage,cryptoImpl=globalThis.crypto,now=()=>Date.now()}){
  const random=n=>b64urlEncode(cryptoImpl.getRandomValues(new Uint8Array(n)));
  const verifier=random(32),state=random(16),nonce=random(16);
  const challenge=b64urlEncode(new Uint8Array(await cryptoImpl.subtle.digest('SHA-256',new TextEncoder().encode(verifier))));
  storage.setItem(PENDING_KEY,JSON.stringify({state,verifier,nonce,clientId:config.oauthClientId,redirectUri:config.redirectUri,createdAt:now()}));
  const url=new URL(config.origin+'/auth/v1/oauth/authorize');
  for(const [k,v] of Object.entries({response_type:'code',client_id:config.oauthClientId,redirect_uri:config.redirectUri,scope:'openid',state,nonce,code_challenge:challenge,code_challenge_method:'S256'}))url.searchParams.set(k,v);
  return url.href;
}

/** True only for the exact pinned redirect path carrying an OAuth response. */
export function isCallback(config,href){
  const url=new URL(href);return url.origin+url.pathname===config.redirectUri&&(url.searchParams.has('code')||url.searchParams.has('error'));
}

/**
 * Finish the redirect: one-time state check, PKCE code exchange, then verify the
 * access token (client_id, session_id, subject, role, audience) and the OIDC ID
 * token (audience = dedicated client, nonce, same subject). The refresh token is
 * discarded; a new sign-in is required when the access token expires.
 */
export async function completeSignIn(config,{href,storage,fetchImpl=globalThis.fetch,keys,now=()=>Date.now(),subtle=globalThis.crypto.subtle}){
  const url=new URL(href);let pending=null;
  try{pending=JSON.parse(storage.getItem(PENDING_KEY));}catch{pending=null;}finally{storage.removeItem(PENDING_KEY);}
  const params=[...url.searchParams.keys()];
  if(url.origin+url.pathname!==config.redirectUri||new Set(params).size!==params.length)fail('denied');
  if(!plainObject(pending)||pending.clientId!==config.oauthClientId||pending.redirectUri!==config.redirectUri||!Number.isFinite(pending.createdAt)||now()-pending.createdAt>PENDING_MAX_AGE_MS||now()<pending.createdAt||typeof pending.state!=='string'||url.searchParams.get('state')!==pending.state)fail('stale');
  if(url.searchParams.has('error')){if(!params.every(k=>['error','error_description','state'].includes(k)))fail('denied');fail(url.searchParams.get('error')==='access_denied'?'refused':'denied');}
  if(!params.every(k=>['code','state'].includes(k)))fail('denied');
  const code=url.searchParams.get('code');if(!code||code.length>2048)fail('denied');
  let response;
  try{response=await fetchImpl(config.origin+'/auth/v1/oauth/token',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded',Accept:'application/json'},body:new URLSearchParams({grant_type:'authorization_code',code,client_id:config.oauthClientId,redirect_uri:config.redirectUri,code_verifier:pending.verifier}).toString(),...fetchOptions});}catch{fail('unavailable');}
  if(!response.ok)fail([400,401,403].includes(response.status)?'denied':'unavailable');
  const body=await readJson(response);
  if(!plainObject(body)||typeof body.access_token!=='string'||typeof body.id_token!=='string'||String(body.token_type).toLowerCase()!=='bearer')fail('denied');
  const issuer=config.origin+'/auth/v1';
  const access=await verifyJwt(body.access_token,{keys,issuer,now,subtle});
  const id=await verifyJwt(body.id_token,{keys,issuer,now,subtle});
  const nested=plainObject(access.app_metadata)?access.app_metadata.client_id:undefined;
  if(access.role!=='authenticated'||!audienceIs(access.aud,'authenticated')||!uuid(access.sub)||access.client_id!==config.oauthClientId||(nested!==undefined&&nested!==config.oauthClientId)||!uuid(access.session_id))fail('denied');
  if(!audienceIs(id.aud,config.oauthClientId)||id.sub!==access.sub||id.nonce!==pending.nonce||(id.client_id!==undefined&&id.client_id!==config.oauthClientId))fail('denied');
  return Object.freeze({verified:true,role:'authenticated',subject:access.sub,clientId:access.client_id,sessionId:access.session_id,expiresAt:access.exp,accessToken:body.access_token});
}
