const $=(s,e=document)=>e.querySelector(s);
const $$=(s,e=document)=>[...e.querySelectorAll(s)];
const byId=id=>document.getElementById(id);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]));
let D=null;

async function getJson(url){
  const r=await fetch(url,{cache:'no-store'});
  if(!r.ok) throw new Error(`${url}: ${r.status}`);
  return r.json();
}

async function init(){
  const manifest=await getJson('./data/today.json');
  const files=(manifest.story_files||[]).slice(0,5);
  const bundles=await Promise.all(files.map(f=>getJson('./data/'+f)));
  const stories=bundles.flat();
  D={...manifest,stories};
  D.top_issue=stories.find(s=>s.title===manifest.top_issue_title)||stories[0]||{};
  const requested=(manifest.top5_titles||[]).map(t=>stories.find(s=>s.title===t)).filter(Boolean);
  const fallback=stories.filter(s=>!requested.some(x=>x.title===s.title)).slice(0,Math.max(0,5-requested.length));
  D.top5=[...requested,...fallback].slice(0,5);
  render();
}

function render(){
  const m=D.meta||{};
  byId('date').textContent=m.date||'';
  byId('generated').textContent=m.generated_at||'';
  byId('window').textContent=m.news_window||'';
  byId('marketWindow').textContent=m.market_window||'';
  renderTop5();renderTrends();renderMetrics();renderNews();renderStocks();renderVideos();renderWatch();renderSummary();
}

function renderTop5(){
  const items=D.top5||[];
  const hero=items[0]||D.top_issue||{};
  const heroEl=byId('top5Hero');
  heroEl.innerHTML=`<span class="rankBadge">TOP 1 · ${esc(hero.section||'TOP ISSUE')}</span><h3>${esc(hero.title||'오늘의 TOP ISSUE')}</h3><p>${esc(hero.summary||'')}</p><div class="metaLine">${esc(hero.source||'')} · ${esc(hero.date||'')} · ${esc(hero.read_time||'상세 브리핑')}</div>`;
  heroEl.onclick=()=>openStory(hero);
  heroEl.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();openStory(hero)}};
  const side=byId('top5Side');
  side.innerHTML=items.slice(1).map((s,i)=>`<article class="top5Card" tabindex="0" role="button" data-i="${D.stories.indexOf(s)}"><span class="rank">TOP ${i+2}</span><span class="cat">${esc(s.section||'NEWS')}</span><h4>${esc(s.title)}</h4><p>${esc(s.summary)}</p><small>${esc(s.source||'')} · ${esc(s.date||'')}</small></article>`).join('');
  $$('.top5Card',side).forEach(el=>{const open=()=>openStory(D.stories[Number(el.dataset.i)]);el.onclick=open;el.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();open()}}});
}

function renderTrends(){
  const panel=byId('trendPanel');const trends=D.trends||[];
  if(!trends.length){panel.style.display='none';return}
  panel.style.display='';
  byId('trends').innerHTML=trends.slice(0,20).map(t=>`<div class="trend"><span class="rank">${esc(t.rank)}</span><div><b>${esc(t.term)}</b><small>${esc(t.context||'')}</small></div><em>${esc(t.volume||'')}</em></div>`).join('');
}

function renderMetrics(){
  byId('metrics').innerHTML=(D.metrics||[]).map(x=>`<div class="metric"><span>${esc(x.name)}</span><strong>${esc(x.value)}</strong><em>${esc(x.change||'')}</em><small>${esc(x.note||'')}</small></div>`).join('');
}

function renderNews(){
  const order=['AI / LLM','소프트웨어 개발 / AI Agent / 자동화','과학 / 의료 / 시과학 / 검안 / 근시 연구','한국 경제 / 정부 정책 / 산업','세계 주요 뉴스','경제 · 시장','기술 제품 / 서비스'];
  const host=byId('news');host.innerHTML='';
  const topTitles=new Set((D.top5||[]).map(s=>s.title));
  for(const name of order){
    const items=(D.stories||[]).filter(s=>s.section===name&&!topTitles.has(s.title));
    if(!items.length) continue;
    const lead=items[0],rows=items.slice(1),sec=document.createElement('section');sec.className='sectionPanel';
    sec.innerHTML=`<div class="sectionHead"><div><small>PERSONAL BRIEFING</small><h3>${esc(name)}</h3></div><span>${items.length} stories</span></div><article class="leadStory" tabindex="0" role="button" data-i="${D.stories.indexOf(lead)}"><span class="tag">LEAD</span><h4>${esc(lead.title)}</h4><p>${esc(lead.summary)}</p><small>${esc(lead.source||'')} · ${esc(lead.date||'')}${lead.evidence_type?` · ${esc(lead.evidence_type)}`:''}</small></article><div class="rowList">${rows.map((s,i)=>`<article class="newsRow" tabindex="0" role="button" data-i="${D.stories.indexOf(s)}"><span class="newsNo">${String(i+2).padStart(2,'0')}</span><div class="newsRowBody"><h4>${esc(s.title)}</h4><p>${esc(s.summary)}</p>${s.evidence_type?`<span class="evidenceBadge">${esc(s.evidence_type)}</span>`:''}</div><div class="newsMeta"><b>${esc(s.source||'')}</b><span>${esc(s.date||'')}</span><em>상세보기 →</em></div></article>`).join('')}</div>`;
    host.appendChild(sec);
  }
  $$('.leadStory,.newsRow',host).forEach(el=>{const open=()=>openStory(D.stories[Number(el.dataset.i)]);el.onclick=open;el.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();open()}}});
}

function renderStocks(){
  const panel=byId('stockPanel'),stocks=D.stocks||[];
  if(!stocks.length){panel.style.display='none';return} panel.style.display='';
  byId('stockGrid').innerHTML=stocks.map(s=>`<article class="stock"><b>${esc(s.ticker)} · ${esc(s.name)}</b><small>${esc(s.theme||'')}</small><p><strong>촉매</strong> ${esc(s.catalyst||'')}</p><p><strong>리스크</strong> ${esc(s.risk||'')}</p><strong>${esc(s.signal||'관찰')}</strong></article>`).join('');
}

function renderVideos(){
  const panel=byId('videoPanel'),videos=D.videos||[];
  if(!videos.length){panel.style.display='none';return} panel.style.display='';
  byId('videoGrid').innerHTML=videos.map(v=>`<article class="video"><img src="${esc(v.thumbnail||'')}" alt="${esc(v.title||'')} 썸네일"><div class="body"><span>${esc(v.category||'')}</span><h4>${esc(v.title)}</h4><p>${esc(v.summary||'')}</p><a href="${esc(v.url||'#')}" target="_blank" rel="noopener">YouTube 열기 →</a></div></article>`).join('');
}

function renderWatch(){byId('todayWatch').innerHTML=(D.today_to_watch||[]).map(x=>`<article class="watchCard"><time>${esc(x.time||'')}</time><h4>${esc(x.title||'')}</h4><p>${esc(x.why||'')}</p><small>${esc(x.source||'')}</small></article>`).join('')}
function renderSummary(){byId('finalSummary').innerHTML=(D.final_three_line_summary||[]).slice(0,3).map(x=>`<li>${esc(x)}</li>`).join('')}
function fill(id,items=[]){byId(id).innerHTML=(items||[]).map(x=>`<li>${esc(x)}</li>`).join('')}

function openStory(s){
  if(!s)return;
  byId('mCategory').textContent=s.section||'';byId('mTitle').textContent=s.title||'';byId('mLead').textContent=s.summary||'';byId('mBackground').textContent=s.background||s.summary||'';byId('mDetail').textContent=s.expanded_detail||s.detail||'';byId('mWhy').textContent=s.why||'';byId('mImpact').textContent=s.impact||'';byId('mWatch').textContent=s.watch||'';fill('mPoints',s.points);fill('mChronology',s.chronology);fill('mUncertainties',s.uncertainties);
  byId('mFacts').innerHTML=(s.factcheck||[]).map(f=>`<div class="fact"><span>${esc(f.status||'확인')}</span><p><b>${esc(f.claim||'')}</b><br>${esc(f.evidence||'')}</p></div>`).join('')||'<div class="emptyPanel">추가 팩트체크 항목 없음</div>';
  byId('mSource').textContent=(s.source||'')+' · '+(s.date||'');const link=byId('mLink');link.href=s.url||'#';link.style.display=s.url?'inline-block':'none';byId('modal').classList.add('open');document.body.style.overflow='hidden';$('.modalBox').scrollTop=0;
}
function closeModal(){byId('modal').classList.remove('open');document.body.style.overflow=''}
byId('close').onclick=closeModal;byId('modal').onclick=e=>{if(e.target===byId('modal'))closeModal()};document.addEventListener('keydown',e=>{if(e.key==='Escape')closeModal()});
init().catch(err=>{console.error(err);document.body.insertAdjacentHTML('afterbegin','<div style="padding:10px;background:#fee;color:#900">뉴스 데이터를 불러오지 못했습니다.</div>')});
