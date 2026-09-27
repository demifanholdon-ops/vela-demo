import {keyOf,parseDate,shiftDay} from './data.js';
const executionStates=['start','done','skip','avoid','later'];
export const actionDay=timestamp=>{const d=new Date(timestamp);return timestamp&&Number.isFinite(d.getTime())?keyOf(d):null;};
// Corrections retract the previous execution and its effect ratings, not the suggestion.
export function executionFor(run,allFeedback=[]){
  const ordered=allFeedback.filter(f=>f.run_id===run.id).slice().sort((a,b)=>Date.parse(a.created_at)-Date.parse(b.created_at));
  const lastCorrection=ordered.findLastIndex(f=>f.result==='correct');
  const feedback=ordered.slice(lastCorrection+1);
  return {feedback,status:feedback.filter(f=>executionStates.includes(f.result)).at(-1)?.result||'offered'};
}
export function actionRecords(runs=[],feedback=[]){
  return runs.flatMap(run=>{
    const action=run.result?.action,mode=run.result?.mode;
    if(!action||!['high','low'].includes(mode))return [];
    const ex=executionFor(run,feedback),events=ex.feedback.filter(f=>actionDay(f.created_at));
    const start=events.find(f=>f.result==='start'),done=events.find(f=>f.result==='done');
    if(!start&&!done)return [];
    const terminal=events.filter(f=>executionStates.includes(f.result)).at(-1);
    return [{id:run.id,mode,text:action.text,startAt:start?.created_at||null,doneAt:done?.created_at||null,
      adoptedAt:start?.created_at||done.created_at,status:ex.status,terminalAt:terminal?.created_at,
      effect:events.filter(f=>['helpful','unhelpful','intrusive'].includes(f.result)).at(-1)?.result||null}];
  });
}
export const recordDays=records=>new Set(records.flatMap(r=>[r.adoptedAt,r.doneAt,r.terminalAt].map(actionDay).filter(Boolean)));
export function dailyActions(records,day,mode){
  const rows=records.filter(r=>r.mode===mode&&[r.adoptedAt,r.doneAt,r.terminalAt].some(t=>actionDay(t)===day));
  return {rows:rows.sort((a,b)=>Date.parse(a.adoptedAt)-Date.parse(b.adoptedAt)),
    adopted:rows.filter(r=>actionDay(r.adoptedAt)===day).length,
    completed:rows.filter(r=>actionDay(r.doneAt)===day).length};
}
export function sampleActions(today){
  const runs=[],feedback=[];
  const add=(day,mode,text,start,end,effect)=>{
    const id=`demo-action-${runs.length}`,stamp=time=>{const d=parseDate(day),[h,m]=time.split(':').map(Number);d.setHours(h,m,0,0);return d.toISOString();};
    runs.push({id,created_at:stamp(start),result:{mode,action:{id,text}}});
    feedback.push({run_id:id,result:'start',created_at:stamp(start)});
    if(end)feedback.push({run_id:id,result:'done',created_at:stamp(end)});
    if(effect)feedback.push({run_id:id,result:effect,created_at:stamp(end)});
  };
  add(today,'high','把周围的声音调轻一点','09:20','09:22','helpful');
  add(today,'high','去安静的地方坐一会儿','13:10','13:15',null);
  add(today,'low','打开文档，写下一个标题','10:05','10:07',null);
  add(today,'low','写下第一句想说的话','10:10','10:13','helpful');
  add(today,'low','把水杯拿到身边','14:30',null,null);
  add(shiftDay(today,-1),'low','把书放到桌上，读一页','19:00','19:05',null);
  return actionRecords(runs,feedback);
}
