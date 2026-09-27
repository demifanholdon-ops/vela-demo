import {shiftDay} from './data.js';

export const moodNames=['很低落','偏低落','平静','偏愉快','很愉快'];
export const energyNames=['很低','偏低','适中','偏高','很高'];
export const valuePresent=v=>typeof v==='number'&&Number.isFinite(v);

// A descriptive reference; seven days is a demo display gate, not a clinical cutoff.
export function reference(days,day,field){
  const values=Array.from({length:14},(_,i)=>days[shiftDay(day,-i-1)]?.[field]).filter(valuePresent);
  return {count:values.length,mean:values.length>=7?values.reduce((a,b)=>a+b,0)/values.length:null};
}

export function sampleDays(today){
  const days={};
  for(let i=20;i>=0;i--){
    const date=shiftDay(today,-i),last=i<7,idx=6-i;
    days[date]={date,source:'demo',sleep_hours:last?[7.6,7.2,7.4,6.8,6.4,6.7,6.2][idx]:7.4+(i%3-1)*.2,
      speech_rate:last?[184,190,187,200,210,205,218][idx]:188+(i%3-1)*4,
      mood:last?[0,0,1,0,-1,0,1][idx]:0,energy:last?[0,0,0,1,1,0,1][idx]:0,
      sleep_start:last&&i===0?'00:40':'23:40',sleep_end:last&&i===0?'07:10':'07:20',
      speech_seconds:60,speech_samples:1};
  }
  return days;
}

export function comparison(days,day,field,unit){
  const current=days[day]?.[field],ref=reference(days,day,field);
  if(!valuePresent(current))return '暂无当日数据，暂不比较';
  if(ref.mean===null)return `个人参考积累中 · ${ref.count}/7 天`;
  const delta=current-ref.mean;
  const amount=field==='speech_rate'?Math.round(Math.abs(delta)):Math.abs(delta).toFixed(1);
  return Number(amount)===0?'与近 14 天有效记录的均值接近':`比近期均值${delta>0?'多':'少'} ${amount} ${unit}`;
}
