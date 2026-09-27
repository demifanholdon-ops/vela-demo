export const live={state:null,onState:null,onMessage:null,
  async refresh(){this.state=await api('/api/state');this.onState?.(this.state);return this.state;},
  async init(){try{await this.refresh();}catch{this.onMessage?.('暂未连接，请启动 VELA 后重试。');}}
};
export async function api(path,body){
  const r=await fetch(path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-Vela-Token':live.state?.token||''},body:JSON.stringify(body)});
  const value=await r.json();
  if(!r.ok)throw new Error(r.status===400?'暂时无法完成。请核对内容；语音请使用两分钟以内的清晰录音。':'连接未完成，请稍后重试。');
  return value;
}
