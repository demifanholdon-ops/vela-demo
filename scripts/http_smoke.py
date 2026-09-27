"""Exercise the real HTTP routes against an isolated temporary database."""
import json
import tempfile
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.server import Application, handler_for

def main():
    with tempfile.TemporaryDirectory() as tmp:
        app=Application(Path(tmp)/'smoke.sqlite3')
        server=ThreadingHTTPServer(('127.0.0.1',0),handler_for(app))
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base='http://127.0.0.1:'+str(server.server_port)
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        def request(path,body=None,headers=None):
            req=urllib.request.Request(base+path,data=json.dumps(body).encode() if body is not None else None,
                headers=headers or {'Content-Type':'application/json','X-Vela-Token':app.token})
            try:
                with opener.open(req,timeout=10) as r:return r.status,r.read()
            except urllib.error.HTTPError as e:return e.code,e.read()
        checks=[]
        def check(name,value):
            assert value,name
            checks.append(name)
        try:
            check('home_served',request('/')[0]==200)
            check('lab_served',request('/lab')[0]==200)
            check('secret_path_denied',request('/../.env')[0]==404)
            check('post_without_token_denied',request('/api/run',{'mode':'low'},{'Content-Type':'application/json'})[0]==403)
            check('cross_origin_denied',request('/api/run',{'mode':'low'},{'Content-Type':'application/json','X-Vela-Token':app.token,'Origin':'https://evil.example'})[0]==403)
            check('invalid_input_returns_400',request('/api/entries',{'title':''})[0]==400)
            check('rhythm_invalid_value',request('/api/rhythm',{'date':'2026-09-27','sleep_hours':25})[0]==400)
            check('rhythm_saved',request('/api/rhythm',{'date':'2026-09-27','sleep_hours':7.5,'mood':0})[0]==200)
            rhythm=json.loads(request('/api/state')[1])['rhythm_days']['2026-09-27']
            check('rhythm_source_and_value',rhythm['source']=='self_report' and rhythm['sleep_hours']==7.5 and rhythm['mood']==0)
            check('rhythm_cleared',request('/api/rhythm',{'date':'2026-09-27'})[0]==200 and not json.loads(request('/api/state')[1])['rhythm_days'])
            status,body=request('/api/run',{'mode':'low'})
            run=json.loads(body);check('agent_returns_run',status==200 and run['result']['action'] is not None)
            check('done_persisted',request('/api/feedback',{'run_id':run['id'],'result':'done'})[0]==200)
            _,body=request('/api/entries',{'title':'HTTP smoke draft','date':'2026-09-27'})
            entry=json.loads(body)
            check('draft_requires_confirmation',entry['confirmed'] is False)
            check('confirm_persisted',request('/api/entries/update',{'id':entry['id'],'confirmed':True})[0]==200)
            check('invalid_wav_is_client_error',request('/api/audio',{'consent':True,'base64':'YWJj','speaker':'unknown'})[0]==400)
            exported=json.loads(request('/api/export')[1])
            check('export_has_no_token','token' not in exported)
            check('export_contains_confirmation',any(e['id']==entry['id'] and e['confirmed'] for e in exported['entries']))
            check('offline_html',b'VELA' in request('/api/report.html')[1])
        finally:
            server.shutdown();server.server_close()
        print(json.dumps({'passed':len(checks),'checks':checks},indent=2))

if __name__=='__main__':main()
