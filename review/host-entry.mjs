import config from './host-config.mjs';
import {startReviewHost} from './host.mjs';
const root=document.querySelector('#review-root');
try{
  await startReviewHost(root,config,{location:window.location,sessionStorage:window.sessionStorage,localStorage:window.localStorage,assign:url=>window.location.assign(url),replaceUrl:url=>window.history.replaceState(null,'',url)});
}catch{const p=document.createElement('p');p.className='boot-error';p.textContent='The review page could not start. No account is connected.';root.replaceChildren(p);}
