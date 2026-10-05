const $ = s => document.querySelector(s);
let mode = 'hybrid', view = 'search', token = '', state = {}, offset = 0, requestId = 0;
const date = t => new Date(t * 1000).toLocaleString([], {month:'short',day:'numeric',hour:'numeric',minute:'2-digit'});
async function api(path, options = {}) {
  const response = await fetch(path, {...options, headers:{'Content-Type':'application/json','X-Seen-Token':token,...options.headers}});
  if (!response.ok) throw new Error((await response.json()).detail || 'Something went wrong. Please try again.');
  return response.json();
}
function notice(text) { $('#notice').hidden = !text; $('#notice').textContent = text || ''; }
function element(tag, className, text) { const el=document.createElement(tag); el.className=className; if(text!==undefined) el.textContent=text; return el; }
async function status() {
  try {
    state = await api('/api/status'); token = state.token;
    const recording = !state.paused && state.worker_online;
    $('#capture-toggle').classList.toggle('recording', recording);
    $('#capture-toggle span').textContent = state.paused ? 'Capture paused' : state.worker_online ? 'Capture is on' : 'Worker offline';
    $('#settings-toggle').textContent = state.paused ? 'Resume capture' : 'Pause capture';
    $('#worker-status').textContent = state.worker_online ? `Worker connected · every ${state.interval||2} seconds${state.capture_error ? ' · ' + state.capture_error : ''}${state.ocr_status ? ' · OCR: ' + state.ocr_status : ''}${state.model_error ? ' · ' + state.model_error : ''}` : 'Worker offline. Run: seen capture';
    $('#storage-status').textContent = `${state.events.toLocaleString()} moments · ${(state.disk_bytes / 1048576).toFixed(1)} MB on this computer`;
  } catch(e) { notice('Cannot reach Seen. Start the local server and refresh.'); }
}
async function toggle() {
  try { await api('/api/controls',{method:'POST',body:JSON.stringify({paused:!state.paused})}); await status(); }
  catch(e) { notice(e.message); }
}
function card(row, scored) {
  const el = element('article','card');
  const pic = element('button','image-button'); pic.setAttribute('aria-label',`View ${row.window_title}`);
  const img = element('img',''); img.src=row.thumbnail_url; img.alt=`Captured ${row.application} window`; img.loading='lazy'; pic.append(img); pic.onclick=()=>detail(row.event_id);
  const body=element('div','card-body'), meta=element('div','card-meta');
  const app=row.application.replace(/\.exe$/i,'');
  meta.append(element('span','app-badge',app[0]?.toUpperCase()||'◉'),element('span','app-name',app),element('span','',`· ${date(row.timestamp)}`));
  body.append(meta,element('h3','',row.window_title),element('p','',row.extracted_text || 'No text extracted. Open the screenshot to take a closer look.'));
  const bottom=element('div','card-bottom'); bottom.append(element('span','',scored ? `${Math.round(row.score*100)}% relevance` : 'Saved locally'));
  const button=element('button','','View moment ↗'); button.onclick=()=>detail(row.event_id); bottom.append(button); body.append(bottom); el.append(pic,body); return el;
}
async function load(append=false) {
  const id=++requestId, query=$('#query').value.trim();
  if(!append) offset=0;
  $('#results-heading').firstChild.textContent=view==='history'?'Your timeline ':query?'Matching moments ':'Recent moments ';
  try {
    const response = await api(view==='history'||!query ? `/api/history?offset=${offset}&limit=30` : `/api/search?q=${encodeURIComponent(query)}&mode=${mode}`);
    if(id!==requestId) return;
    if(!append) $('#results').replaceChildren();
    const scored=view!=='history'&&!!query;
    for(const row of response.results) $('#results').append(card(row,scored));
    offset+=response.results.length;
    $('#count').textContent=offset;
    $('#results-caption').textContent=scored?`${response.latency_ms} ms${response.time_filter?' · Filtered by the time you remembered':''} · Scores are relative relevance, not confidence.`:'A few things that crossed your screen.';
    notice(response.warning);
    $('#load-more').hidden=scored||response.results.length<30;
    if(!offset) {
      const empty=element('div','empty');
      empty.append(element('h3','',scored?'Nothing comes to mind yet.':'A fresh start for your memory.'));
      empty.append(element('p','',scored?'Try a different detail, application, or time. Semantic search needs the local model.':'Start the capture worker, then resume capture. Your meaningful moments will appear here.'));
      if(!scored) empty.append(element('code','','seen capture --start'));
      $('#results').append(empty);
    }
  } catch(e) { notice(e.message); }
}
async function detail(id) {
  try {
    const row=await api(`/api/events/${id}`);
    $('#detail-title').textContent=row.window_title;
    $('#detail-meta').textContent=`${row.application} · ${date(row.timestamp)} · Event #${row.event_id}`;
    $('#detail-image').src=row.image_url; $('#full-image').href=`/moments/${row.event_id}`;
    $('#detail-text').textContent=row.extracted_text||'No text was extracted from this moment.';
    $('#detail-ocr').textContent=`OCR: ${row.ocr_status} · ${row.has_embedding?'Semantic index ready':'Keyword index only'}`;
    $('#detail').showModal();
  } catch(e) { notice(e.message); }
}
function setView(next) {
  view=next; $('#page-name').textContent=next==='history'?'Timeline':'Search';
  $('#history-nav').classList.toggle('active',next==='history'); $('#search-nav').classList.toggle('active',next==='search');
  load();
}
$('#search-form').onsubmit=e=>{e.preventDefault();setView('search');};
document.querySelectorAll('[data-query]').forEach(b=>b.onclick=()=>{$('#query').value=b.dataset.query;setView('search');});
document.querySelectorAll('[data-mode]').forEach(b=>b.onclick=()=>{mode=b.dataset.mode;document.querySelectorAll('[data-mode]').forEach(x=>x.classList.toggle('selected',x===b));load();});
$('#search-nav').onclick=()=>setView('search'); $('#history-nav').onclick=()=>setView('history');
$('#capture-toggle').onclick=toggle; $('#settings-toggle').onclick=toggle;
$('#settings-nav').onclick=async()=>{await status();$('#exclusions').value=(state.excluded_apps||[]).join('\n');$('#settings-saved').textContent='';$('#settings').showModal();};
document.querySelectorAll('.close').forEach(b=>b.onclick=()=>b.closest('dialog').close());
$('#exclusions-form').onsubmit=async e=>{e.preventDefault();try{await api('/api/controls',{method:'POST',body:JSON.stringify({excluded_apps:$('#exclusions').value.split('\n')})});$('#settings-saved').textContent='Saved';await status();}catch(e){$('#settings-saved').textContent=e.message;}};
$('#delete-history').onclick=async()=>{if(!confirm('Permanently delete all Seen history on this computer? Capture will pause.'))return;try{await api('/api/history',{method:'DELETE'});$('#settings').close();$('#detail').close();$('#detail-image').removeAttribute('src');$('#detail-text').textContent='';await status();await load();}catch(e){notice(e.message);}};
$('#load-more').onclick=()=>load(true);
status().then(async()=>{await load();const match=location.pathname.match(/^\/moments\/(\d+)$/);if(match)detail(Number(match[1]));}); setInterval(status,5000);
