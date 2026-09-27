import test from 'node:test';
import assert from 'node:assert/strict';
import {actionRecords,dailyActions,recordDays,sampleActions,executionFor} from '../frontend/src/action-history.js';
import {actionHistoryView} from '../frontend/src/action-history-view.js';
const day='2026-09-27',stamp=(d,h=10,m=0)=>new Date(2026,8,d,h,m).toISOString();
const run=(id='r',mode='low',text='打开文档')=>({id,result:{mode,action:{text}}});
const f=(result,d=27,h=10,m=0,id='r')=>({run_id:id,result,created_at:stamp(d,h,m)});
test('offered, skipped and deferred suggestions are not adopted actions',()=>{
 for(const feedback of [[],[f('skip')],[f('avoid')],[f('later')]])assert.equal(actionRecords([run()],feedback).length,0);
});
test('repeated execution and effect feedback count one action per run',()=>{
 const records=actionRecords([run()],[f('start'),f('start',27,10,1),f('done',27,10,2),f('done',27,10,3),f('helpful',27,10,4)]);
 const group=dailyActions(records,day,'low');assert.equal(group.adopted,1);assert.equal(group.completed,1);assert.equal(group.rows[0].effect,'helpful');
});
test('same method on different runs counts distinct uses; high and low stay separate',()=>{
 const records=actionRecords([run(),run('s','high')],[f('done'),f('done',27,11,0,'s')]);
 assert.equal(dailyActions(records,day,'high').completed,1);assert.equal(dailyActions(records,day,'low').completed,1);
 assert.equal(records[0].startAt,null);
});
test('correction retracts completion and effects, then restart counts once',()=>{
 const feedback=[f('start'),f('done',27,10,1),f('helpful',27,10,2),f('correct',27,10,3)];
 assert.equal(actionRecords([run()],feedback).length,0);assert.equal(executionFor(run(),feedback).status,'offered');
 feedback.push(f('start',27,10,4));const records=actionRecords([run()],feedback);
 assert.equal(dailyActions(records,day,'low').adopted,1);assert.equal(dailyActions(records,day,'low').completed,0);assert.equal(records[0].effect,null);
});
test('cross-midnight completion belongs to completion day; previous day is not marked completed',()=>{
 const records=actionRecords([run()],[f('start',26,23,59),f('done',27,0,2)]);
 assert.equal(dailyActions(records,'2026-09-26','low').adopted,1);assert.equal(dailyActions(records,'2026-09-26','low').completed,0);
 assert.equal(dailyActions(records,day,'low').adopted,0);assert.equal(dailyActions(records,day,'low').completed,1);
 assert.deepEqual([...recordDays(records)].sort(),['2026-09-26',day]);
 assert.doesNotMatch(actionHistoryView(records,'2026-09-26'),/已完成/);assert.match(actionHistoryView(records,day),/9月26日 23:59/);
});
test('starting then deferring remains adopted but not completed',()=>{
 const group=dailyActions(actionRecords([run()],[f('start'),f('later',27,10,1)]),day,'low');
 assert.equal(group.adopted,1);assert.equal(group.completed,0);assert.equal(group.rows[0].status,'later');
});
test('invalid timestamps and unrelated runs do not pollute history',()=>{
 assert.equal(actionRecords([run()],[{...f('done'),created_at:'invalid'},f('done',27,10,0,'missing')]).length,0);
});
test('examples stay separate, display concrete actions and escape user text',()=>{
 const demo=sampleActions(day);assert.equal(dailyActions(demo,day,'high').adopted,2);assert.equal(dailyActions(demo,day,'low').completed,2);assert.equal(dailyActions(demo,day,'low').adopted,3);
 assert.equal(actionRecords([],[]).length,0);
 const html=actionHistoryView(actionRecords([run('r','low','<img onerror="alert(1)">')],[f('done')]),day);
 assert.doesNotMatch(html,/<img/);assert.match(html,/&lt;img/);
});
