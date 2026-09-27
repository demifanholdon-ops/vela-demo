import {actionDay,dailyActions} from './action-history.js';
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const time=(timestamp,day)=>{const d=new Date(timestamp);return `${actionDay(timestamp)!==day?`${d.getMonth()+1}月${d.getDate()}日 `:''}${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`;};
const statusNames={start:'已开始',done:'已完成',later:'暂时放下',skip:'换了一个方式',avoid:'不再使用这个方式'};
const effects={helpful:'有一点帮助',unhelpful:'不太适合',intrusive:'让我有压力'};
function row(r,day){
  // A later completion must not appear as already completed on an earlier calendar day.
  const endedOnOrBefore=actionDay(r.terminalAt)<=day;
  const status=endedOnOrBefore?r.status:'start';
  return `<li class="action-timeline-row"><div class="action-row-heading"><span class="action-status ${status==='done'?'is-done':''}">${statusNames[status]||'已开始'}</span><span>${r.startAt?`${time(r.startAt,day)} 开始`:'开始时间未记录'}</span></div><p>${esc(r.text)}</p>${r.doneAt&&actionDay(r.doneAt)<=day?`<div class="action-row-note">${time(r.doneAt,day)} 完成${r.effect?` · ${effects[r.effect]}`:''}</div>`:endedOnOrBefore&&['later','skip','avoid'].includes(status)?`<div class="action-row-note">${time(r.terminalAt,day)} ${statusNames[status]}</div>`:''}</li>`;
}
export function actionHistoryView(records,day,demo=false){
  const groups=[['high','缓一缓','让自己停一停，用了哪些方式'],['low','做一小步','从开始到完成，留下具体的小步']].map(([mode,title,subtitle])=>({mode,title,subtitle,...dailyActions(records,day,mode)}));
  return `<section class="daily-actions" aria-label="每日行动"><div class="daily-actions-heading"><h2>这一天，我做了什么</h2><span class="sample-tag">${Number(day.slice(5,7))}月${Number(day.slice(8))}日${demo?' · 示例':''}</span></div><p class="action-section-note">开始和完成，都会自动留在这里。</p><div class="action-day-summary">${groups.map(g=>`<div class="action-summary ${g.mode}"><span>${g.title}</span><strong>${g.mode==='high'?g.adopted:g.completed}<small>${g.mode==='high'?'次采用':'小步完成'}</small></strong><p>${g.mode==='high'?`${g.completed} 次完成`:`${g.adopted} 小步开始`}</p></div>`).join('')}</div>${groups.map(g=>`<section class="action-group ${g.mode}"><h3>${g.title}</h3><p class="action-group-caption">${g.subtitle}</p>${g.rows.length?`<ol class="action-timeline">${g.rows.map(r=>row(r,day)).join('')}</ol>`:`<p class="action-empty">这一天还没有${g.title}的行动记录。</p>`}</section>`).join('')}<p class="action-section-note action-count-note">只看过或跳过的建议不计入行动；次数按开始、完成当天分别记录。</p></section>`;
}
