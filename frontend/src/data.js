export const keyOf = date => `${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,'0')}-${String(date.getDate()).padStart(2,'0')}`;
export const parseDate = key => { const [y,m,d] = key.split('-').map(Number); return new Date(y,m-1,d,12); };
export function shiftDay(key, amount) { const date = parseDate(key); date.setDate(date.getDate()+amount); return keyOf(date); }
export function shiftMonth(key, amount) { const date = parseDate(key), day = date.getDate(); date.setDate(1); date.setMonth(date.getMonth()+amount); date.setDate(Math.min(day,new Date(date.getFullYear(),date.getMonth()+1,0).getDate())); return keyOf(date); }
export function monthCells(key) {
  const date = parseDate(key), first = new Date(date.getFullYear(),date.getMonth(),1,12);
  const offset = (first.getDay()+6)%7;
  const count = new Date(date.getFullYear(),date.getMonth()+1,0).getDate();
  return Array.from({length:Math.ceil((offset+count)/7)*7},(_,i)=> i < offset || i >= offset+count ? null : keyOf(new Date(date.getFullYear(),date.getMonth(),i-offset+1,12)));
}
export function focusRatio(record) { return record?.total > 0 ? Math.min(1,Math.max(0,record.returned/record.total)) : 0; }
export function createDemo(today) {
  const month = today.slice(0,7), day = parseDate(today).getDate();
  const focus = {};
  for (let n=1;n<=day;n++) {
    if (n%7===0 || n%9===0) continue;
    const total = 3+(n*7)%5, returned = n%4===0 ? Math.ceil(total/2) : n%3===0 ? total-1 : total;
    focus[`${month}-${String(n).padStart(2,'0')}`] = {total,returned};
  }
  focus[today] = {total:6,returned:3};
  focus[shiftDay(today,-1)] = {total:6,returned:6};
  const tasks = {
    [today]: [
      {id:'shopping',title:'出门买菜',note:'把一件大事，变成眼前的小事。',steps:[{id:'shoes',title:'穿上鞋',done:true,time:'09:12'},{id:'bag',title:'拿上购物袋',done:true,time:'09:13'},{id:'door',title:'走出家门',done:false}]},
      {id:'report',title:'开始写报告',note:'不用写完，先开始就好。',steps:[{id:'document',title:'新建一个报告文档',done:true,time:'10:06'},{id:'question',title:'写一句报告要回答的问题',done:false}]}
    ],
    [shiftDay(today,-1)]: [{id:'reading',title:'读一点书',note:'一点点，也在向前。',steps:[{id:'book',title:'把书放到桌上',done:true,time:'20:10'},{id:'page',title:'读完第一页',done:true,time:'20:12'}]}]
  };
  const events = [
    {id:'e1',date:today,title:'带上购物袋',kind:'todo',done:false,time:''},
    {id:'e2',date:today,title:'给植物浇水',kind:'todo',done:true,time:''},
    {id:'e3',date:today,title:'和小林碰一下方案',kind:'reminder',done:false,time:'15:00'},
    {id:'e4',date:shiftDay(today,1),title:'带上充电器',kind:'todo',done:false,time:''},
    {id:'e5',date:shiftDay(today,1),title:'下午的项目会议',kind:'reminder',done:false,time:'14:30'},
    {id:'e6',date:shiftDay(today,3),title:'取快递',kind:'todo',done:false,time:''},
    {id:'e7',date:shiftDay(today,-1),title:'回复小林',kind:'todo',done:true,time:''},
    {id:'e8',date:shiftDay(today,-3),title:'整理书桌',kind:'todo',done:true,time:''},
    {id:'e9',date:shiftDay(today,-5),title:'周末买水果',kind:'todo',done:true,time:''},
    {id:'e10',date:shiftDay(today,-8),title:'取洗好的衣服',kind:'reminder',done:false,time:'18:00'},
    {id:'e11',date:shiftDay(today,-10),title:'朋友的生日',kind:'reminder',done:false,time:'09:00'},
    {id:'e12',date:shiftDay(today,-13),title:'整理资料',kind:'todo',done:true,time:''}
  ];
  return {version:2,anchor:today,focus,tasks,events};
}
