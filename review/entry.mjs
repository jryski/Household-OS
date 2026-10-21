import {mountReviewDesk} from './app.mjs';
import {createExampleClient} from './demo.mjs';
const root=document.querySelector('#review-root');
try { mountReviewDesk(root,await createExampleClient()); }
catch { const p=document.createElement('p');p.className='boot-error';p.textContent='The example could not load. Restart the local preview and reload this page.';root.replaceChildren(p); }
