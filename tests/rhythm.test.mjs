import test from 'node:test';
import assert from 'node:assert/strict';
import {reference,sampleDays,comparison} from '../frontend/src/rhythm.js';
import {shiftDay} from '../frontend/src/data.js';
import {rhythmDay} from '../frontend/src/rhythm-view.js';
const day='2026-09-27';
test('reference excludes today, future, missing days and unknown values',()=>{
  const days={};for(let i=1;i<=7;i++)days[shiftDay(day,-i)]={sleep_hours:8};
  days[day]={sleep_hours:20};days[shiftDay(day,1)]={sleep_hours:20};
  days[shiftDay(day,-8)]={sleep_hours:null};
  assert.deepEqual(reference(days,day,'sleep_hours'),{count:7,mean:8});
});
test('zero is a record, insufficient history cannot become a reference',()=>{
  assert.deepEqual(reference({[shiftDay(day,-1)]:{sleep_hours:0}},day,'sleep_hours'),{count:1,mean:null});
});
test('missing current day does not become a deviation',()=>{
  const days=sampleDays(day);delete days[day];
  assert.equal(comparison(days,day,'sleep_hours','小时'),'暂无当日数据，暂不比较');
});
test('examples are isolated, labeled and span the full reference interval',()=>{
  const days=sampleDays(day);assert.equal(Object.keys(days).length,21);
  assert.ok(Object.values(days).every(d=>d.source==='demo'));
  assert.equal(reference(days,shiftDay(day,-6),'speech_rate').count,14);
});
test('self-report labels preserve low, neutral and high values',()=>{
  for(const [value,label,energy] of [[-2,'很低落','很低'],[0,'平静','适中'],[2,'很愉快','很高']]){
    const output=rhythmDay({[day]:{mood:value,energy:value}},day,false);
    assert.ok(output.includes(`<strong>${label}</strong>`));
    assert.ok(output.includes(`<strong>${energy}</strong>`));
    assert.ok(!output.includes('undefined'));
  }
});
