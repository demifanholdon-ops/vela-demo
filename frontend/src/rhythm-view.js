import {shiftDay,parseDate} from './data.js';
import {moodNames,energyNames,valuePresent,reference,comparison} from './rhythm.js';

const safe=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const number=v=>Number.isInteger(v)?String(v):v.toFixed(1);
function trend(days,day,field,label,unit){
  const dates=Array.from({length:7},(_,i)=>shiftDay(day,i-6));
  const ceiling=Math.max(field==='sleep_hours'?12:300,...dates.map(d=>days[d]?.[field]).filter(valuePresent));
  return `<div class="rhythm-trend" role="group" aria-label="近七天${label}">${dates.map(date=>{
    const value=days[date]?.[field],known=valuePresent(value),height=known?Math.max(2,value/ceiling*44):0;
    return `<div class="trend-day ${date===day?'chosen':''}" aria-label="${date}，${known?number(value)+unit:'无数据'}"><span class="trend-number">${known?number(value):'—'}</span><div class="trend-track">${known?`<i style="height:${height}px"></i>`:'<span>·</span>'}</div><span>${parseDate(date).getDate()}日</span></div>`;
  }).join('')}</div>`;
}
function baseline(days,day,field,unit){
  const ref=reference(days,day,field);
  return `<p class="metric-comparison">${comparison(days,day,field,unit)}</p>${ref.mean!==null?`<p class="metric-source">近 14 天参考：${field==='speech_rate'?Math.round(ref.mean):ref.mean.toFixed(1)} ${unit} · ${ref.count} 个有效日</p>`:''}`;
}
function moodReference(days,day){
  const values=Array.from({length:14},(_,i)=>days[shiftDay(day,-i-1)]?.mood).filter(valuePresent);
  if(values.length<7)return `近期心情记录积累中 · ${values.length}/7 天`;
  const counts=moodNames.map((_,i)=>values.filter(v=>v===i-2).length),max=Math.max(...counts);
  return `近 14 天常见心情：${moodNames.filter((_,i)=>counts[i]===max).join(' / ')}`;
}
export function rhythmDay(days,day,demo){
  const d=days[day]||{},sleep=valuePresent(d.sleep_hours),speech=valuePresent(d.speech_rate);
  const mood=valuePresent(d.mood),energy=valuePresent(d.energy);
  const source=demo?'示例数据':'本人填写';
  return `<div class="rhythm-cards">
  <article class="rhythm-card sleep-card"><div class="metric-heading"><h3>睡眠</h3><span>${sleep?source:'尚未记录'}</span></div>
  <div class="metric-value">${sleep?`${number(d.sleep_hours)}<small>小时</small>`:'<span class="metric-missing">暂无数据</span>'}</div>
  <p class="metric-context">${d.sleep_start||d.sleep_end?`${safe(d.sleep_start)||'—'} 入睡 · ${safe(d.sleep_end)||'—'} 醒来`:'睡眠时长 · 入睡与醒来时间'}</p>
  ${baseline(days,day,'sleep_hours','小时')}${trend(days,day,'sleep_hours','睡眠时长','小时')}
  <p class="metric-source">${demo?'示例时长不包含夜间清醒时间':'按醒来的日期归档；时长为本人估计，非设备检测'}</p></article>
  <article class="rhythm-card speech-card"><div class="metric-heading"><h3>说话语速</h3><span>${speech?'示例 · 片段估计':'等待声音数据'}</span></div>
  <div class="metric-value">${speech?`${Math.round(d.speech_rate)}<small>字 / 分钟</small>`:'<span class="metric-missing">暂无数据</span>'}</div>
  <p class="metric-context">${speech?`当日 ${d.speech_samples} 段 · ${d.speech_seconds} 秒示例语音`:'需有本人语音、有效时长和可靠转写'}</p>
  ${baseline(days,day,'speech_rate','字 / 分钟')}${trend(days,day,'speech_rate','片段语速','字/分钟')}
  <p class="metric-source">${demo?'示例口径：中文转写字数 ÷ 录音分钟，含停顿；不代表全天语速':'当前未接入语速分析，不从文字长度猜测语速'}</p></article>
  <article class="rhythm-card feeling-card"><div class="metric-heading"><h3>情绪与精力</h3><span>${mood||energy?source:'尚未记录'}</span></div>
  <div class="feeling-pair"><div><span>心情</span><strong>${mood?moodNames[d.mood+2]:'未记录'}</strong></div><div><span>精力</span><strong>${energy?energyNames[d.energy+2]:'未记录'}</strong></div></div>
  <p class="metric-comparison">${moodReference(days,day)}</p><div class="feeling-week" role="group" aria-label="近七天本人心情记录">${Array.from({length:7},(_,i)=>shiftDay(day,i-6)).map(date=>{
    const value=days[date]?.mood,known=valuePresent(value);
    return `<div class="feeling-day"><span>${parseDate(date).getDate()}日</span><strong>${known?moodNames[value+2]:'—'}</strong></div>`;
  }).join('')}</div>
  <p class="metric-context">声音中的情绪表现：${demo?'本例未提供':'尚未接入分析'}</p><p class="metric-source">本人感受与声音表现分开记录，不互相代替</p></article>
  </div><details class="rhythm-method"><summary>这些比较怎么看？</summary><p>与所选日期之前 14 天的有效记录均值比较，至少积累 7 个有效日才显示参考。7 天是当前展示规则，不是医学标准；均值也不等于健康目标。没有数据的日子留空，不按零计算。</p><p>睡眠、语速与情绪是观察线索，变化不能直接判定躁狂或抑郁。语速需在相近语言和场景下比较，单个片段不能代表全天。</p></details>`;
}
