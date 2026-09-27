"""Single-user local demo server. Python standard library only, no installation required."""
import argparse
import base64
import datetime
import html
import json
import mimetypes
import os
import secrets
import sys
import threading
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from . import agents, journal, speech, rhythm
from .evidence import analyze_session, analyze_wav
from .store import Store

ROOT=Path(__file__).resolve().parents[1]

def load_env(path):
    if not Path(path).is_file(): return
    for line in Path(path).read_text().splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            k,v=line.split('=',1)
            if k.strip() in ('AI_BASE_URL','AI_API_KEY','AI_MODEL','VELA_ASR_PYTHON','VELA_ASR_MODEL'):
                os.environ.setdefault(k.strip(),v.strip().strip('\"\''))

class Application:
    def __init__(self,db,session=None,calibration=None):
        self.store=Store(db)
        self.token=secrets.token_urlsafe(32)
        self.lock=threading.Lock()
        self.inflight=set()
        folder=session or next((ROOT/'inputs/hw/data').iterdir())
        self.report=analyze_session(folder,calibration or ROOT/'inputs/report-0e27827d.json')
        self.store.set_setting('cloud_consent',False)  # Every server launch starts private.

    def state(self):
        return {'token':self.token,'entries':self.store.items('entry'),
            'feedback':self.store.items('feedback'),'runs':self.store.items('run'),
            'audio':self.store.items('audio'), 'cloud_consent':self.store.setting('cloud_consent',False),
            'asr_available':speech.available(), 'plans':self.store.items('plan'),
            'help_plan':self.store.setting('help_plan',''),
            'rhythm_days':self.store.setting('rhythm_days',{}),
            'cloud_configured':all(os.environ.get(k) for k in ('AI_BASE_URL','AI_API_KEY','AI_MODEL')),
            'cloud_recipient':urlsplit(os.environ.get('AI_BASE_URL','')).hostname,
            'report':self.report,'today':datetime.date.today().isoformat()}

    def post(self,path,body):
        if path=='/api/rhythm':
            day, values = rhythm.validate(body)
            with self.lock:
                days = self.store.setting('rhythm_days',{})
                if any(values[field] is not None for field in rhythm.FIELDS):
                    days[day] = values
                else:
                    days.pop(day, None)
                self.store.set_setting('rhythm_days',days)
            return {'saved':True, 'day':values}
        if path=='/api/transcribe':
            if body.get('consent') is not True or body.get('speaker')!='self_confirmed': raise ValueError('audio_consent_required')
            raw=base64.b64decode(body.get('base64',''),validate=True)
            result=speech.transcribe(raw)
            # No audio or transcript is persisted before the user chooses to create a draft.
            return {**result,'source':'local_asr','stored':False}
        if path=='/api/drafts':
            text=body.get('text');cloud=body.get('cloud',False)
            if not isinstance(text,str) or not 1<=len(text.strip())<=2000: raise ValueError('text_length')
            date=body.get('date',datetime.date.today().isoformat())
            datetime.date.fromisoformat(date)
            if type(cloud) is not bool or (cloud and body.get('text_consent') is not True): raise ValueError('text_consent_required')
            source=body.get('source','user_text')
            if source not in ('user_text','local_asr'): raise ValueError('source')
            key=body.get('request_id','')
            if not isinstance(key,str) or not 8<=len(key)<=80: raise ValueError('request_id')
            with self.lock:
                previous=self.store.setting('draft_request:'+key)
                if previous: return previous
                if key in self.inflight: raise ValueError('draft_pending')
                self.inflight.add(key)
            try:
                if cloud:
                    self.reserve_cloud()
                    self.store.add('consent',{'enabled':True,'scope':'journal_text_classification_once','request_id':key,
                        'recipient':urlsplit(os.environ.get('AI_BASE_URL','')).hostname})
                proposal=journal.organize(text,cloud)
                with self.lock:
                    entries=self.store.add_many('entry',[{'title':x['title'],'entry_type':x['kind'],'date':date,
                        'confirmed':False,'done':False,'revision':1,'source':source,'source_quote':x['source_quote'],
                        'source_text':proposal['source_text'],'processor':proposal['processor'],'mode':'stable',
                        'audio_sha256':body.get('audio_sha256') if source=='local_asr' else None} for x in proposal['items']], 'draft_request:'+key)
                    value={'entries':entries,'processor':proposal['processor'],'fallback_reason':proposal['fallback_reason']}
                    # Keep only identifiers in the retry receipt, so deletion cannot expose old text.
                    return value
            finally:
                with self.lock: self.inflight.discard(key)
        if path=='/api/plans':
            mode=body.get('mode')
            text=body.get('text','')
            if mode not in ('high','low') or not isinstance(text,str) or not 1<=len(text.strip())<=200: raise ValueError('plan')
            return self.store.add('plan',{'mode':mode,'text':text.strip(),'source':'user_selected'})
        if path=='/api/help-plan':
            text=body.get('text','')
            if not isinstance(text,str) or len(text)>1000: raise ValueError('help_plan')
            self.store.set_setting('help_plan',text.strip());return {'saved':True}
        if path=='/api/preferences/reset':
            mode=body.get('mode')
            if mode not in agents.ACTIONS: raise ValueError('mode')
            self.store.set_setting('preferences_since:'+mode,datetime.datetime.now(datetime.timezone.utc).isoformat())
            return {'reset':True}
        if path=='/api/consent':
            if type(body.get('enabled')) is not bool: raise ValueError('enabled_requires_boolean')
            self.store.set_setting('cloud_consent',body['enabled'])
            self.store.add('consent',{'enabled':body['enabled'],'scope':'structured_engineering_summary_only'})
            return {'enabled':body['enabled']}
        if path=='/api/run':
            mode=body.get('mode','stable')
            if mode not in agents.ACTIONS: raise ValueError('invalid_mode')
            window=body.get('window')
            if window is not None and (type(window) is not int or not 0<=window<len(self.report['windows'])):
                raise ValueError('invalid_window')
            requested=body.get('cloud',False)
            if type(requested) is not bool: raise ValueError('cloud_requires_boolean')
            consent=requested and self.store.setting('cloud_consent',False)
            if consent: self.reserve_cloud()
            after=self.store.setting('preferences_since:'+mode,'')
            feedback=[x for x in self.store.items('feedback') if x['created_at']>=after]
            result=agents.run(self.report,mode,consent,window,feedback,personal_plan=self.store.items('plan'))
            with self.lock:
                if consent and not self.store.setting('cloud_consent',False):
                    result=agents.run(self.report,mode,False,window,self.store.items('feedback'))
                    result['fallback_reason']='consent_revoked'
                return self.store.add('run',{'result':result,'window':window,
                    'evidence_version':self.report['schema'],'calibration_id':self.report['calibration_id'],
                    'session_id':self.report['session_id'],'source_files':self.report['files'],
                    'window_evidence':self.report['windows'][window] if window is not None else None})
        if path=='/api/feedback':
            run=self.store.get(body['run_id'])
            if run['kind']!='run' or not run['result']['action']: raise ValueError('no_action')
            result=body['result']
            if result not in ('start','done','skip','avoid','later','helpful','unhelpful','intrusive','correct'): raise ValueError('invalid_feedback')
            with self.lock:
                existing=[x for x in self.store.items('feedback') if x['run_id']==run['id']]
                latest=existing[-1] if existing else None
                if latest and latest['result']==result: return latest
                execution=[x for x in existing if x['result'] in ('start','done','skip','avoid','later','correct')]
                closed=execution and execution[-1]['result'] in ('done','skip','avoid','later')
                if result in ('helpful','unhelpful','intrusive'):
                    if not execution or execution[-1]['result']!='done': raise ValueError('feedback_before_completion')
                elif result=='correct':
                    if not closed: raise ValueError('nothing_to_correct')
                elif closed: raise ValueError('action_already_closed')
                return self.store.add('feedback',{'run_id':run['id'],'result':result,
                    'mode':run['result']['mode'],'action_id':run['result']['action']['id'],
                    'action_text':run['result']['action']['text']})
        if path=='/api/entries':
            fields=journal.validate_entry(body)
            mode=body.get('mode','stable')
            if mode not in agents.ACTIONS: raise ValueError('invalid_mode')
            # User text remains untrusted content; never passed to the agent prompt or executed.
            return self.store.add('entry',{**fields,'mode':mode,
                'confirmed':False,'source':'user_text','done':False,'revision':1})
        if path=='/api/entries/update':
            item=self.store.get(body['id'])
            if item['kind']!='entry': raise ValueError('not_an_entry')
            with self.lock:
                item=self.store.get(body['id'])
                if 'revision' in body and body['revision']!=item.get('revision',1): raise ValueError('stale_revision')
                changes=journal.validate_entry(body,update=True)
                if not changes: raise ValueError('empty_update')
                if changes.get('done') and changes.get('entry_type',item.get('entry_type','event'))!='plan': raise ValueError('not_a_plan')
                if changes.get('entry_type',item.get('entry_type','event'))!='plan': changes['done']=False
                self.store.add('entry_revision',{'entry_id':item['id'],'previous':item})
                return self.store.update(body['id'],{**changes,'revision':item.get('revision',1)+1})
        if path=='/api/delete':
            self.store.delete(body['id'])
            return {'deleted':True}
        if path=='/api/audio':
            if body.get('consent') is not True: raise ValueError('audio_consent_required')
            encoded=body.get('base64','')
            if not isinstance(encoded,str): raise ValueError('audio_base64_required')
            blob=base64.b64decode(encoded,validate=True)
            evidence=analyze_wav(blob,body.get('speaker','unknown'))
            return self.store.add('audio',{'evidence':evidence})
        raise KeyError('route_not_found')

    def reserve_cloud(self):
        with self.lock:
            used=self.store.setting('cloud_requests',0)
            if used>=10: raise ValueError('cloud_budget_10_requests_reached')
            self.store.set_setting('cloud_requests',used+1)

def handler_for(app):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,fmt,*args):
            # Deliberately avoid request bodies, tokens and file contents in logs.
            return

        def reply(self,status,payload,kind='application/json; charset=utf-8',download=None):
            if not isinstance(payload,bytes): payload=json.dumps(payload,ensure_ascii=False,allow_nan=False).encode()
            self.send_response(status)
            self.send_header('Content-Type',kind)
            self.send_header('Content-Length',str(len(payload)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'")
            if download: self.send_header('Content-Disposition','attachment; filename="'+download+'"')
            self.end_headers();self.wfile.write(payload)

        def allowed_host(self):
            return self.headers.get('Host','') in (f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}')

        def do_GET(self):
            if not self.allowed_host(): return self.reply(403,{'error':'loopback_host_required'})
            path=urlsplit(self.path).path
            if path=='/api/health': return self.reply(200,{'ok':True,'version':'0.2.0','offline_ready':True})
            if path=='/api/state': return self.reply(200,app.state())
            if path=='/api/evidence': return self.reply(200,app.report)
            if path=='/api/export':
                data=app.state();data.pop('token')
                return self.reply(200,data,download='vela-evidence.json')
            if path=='/api/report.html':
                data=app.state();data.pop('token')
                document='<!doctype html><meta charset="utf-8"><title>VELA evidence</title><h1>VELA 可追溯报告</h1><p>真实校准数据；无疾病判定；音频不同步。</p><pre>'+html.escape(json.dumps(data,ensure_ascii=False,indent=2))+'</pre>'
                return self.reply(200,document.encode(),'text/html; charset=utf-8',download='vela-report.html')
            aliases={'/':'index.html','/lab':'lab.html'}
            file=(ROOT/'frontend'/aliases.get(path,path.lstrip('/'))).resolve()
            if not file.is_relative_to(ROOT/'frontend') or not file.is_file(): return self.reply(404,{'error':'not_found'})
            return self.reply(200,file.read_bytes(),mimetypes.guess_type(str(file))[0] or 'application/octet-stream')

        def do_POST(self):
            if not self.allowed_host(): return self.reply(403,{'error':'loopback_host_required'})
            origin=self.headers.get('Origin')
            if origin and origin not in (f'http://localhost:{self.server.server_port}',f'http://127.0.0.1:{self.server.server_port}'):
                return self.reply(403,{'error':'cross_origin_denied'})
            if not secrets.compare_digest(self.headers.get('X-Vela-Token',''),app.token):
                return self.reply(403,{'error':'token_required'})
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<=20000000: return self.reply(413,{'error':'body_limit'})
                if self.headers.get('Content-Type','').split(';')[0]!='application/json':
                    return self.reply(415,{'error':'json_required'})
                self.connection.settimeout(20)
                body=json.loads(self.rfile.read(size),parse_constant=lambda _: (_ for _ in ()).throw(ValueError('non_finite_json')))
                if not isinstance(body,dict): raise ValueError('object_required')
                result=app.post(urlsplit(self.path).path,body)
                return self.reply(200,result)
            except KeyError:
                return self.reply(404,{'error':'not_found_or_missing_field'})
            except (ValueError,TypeError,OverflowError,EOFError,wave.Error):
                return self.reply(400,{'error':'invalid_input'})
            except Exception:
                return self.reply(500,{'error':'local_processing_failed'})
    return Handler

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--port',type=int,default=4186)
    parser.add_argument('--db',default=str(ROOT/'runtime/vela.sqlite3'))
    parser.add_argument('--session',type=Path)
    parser.add_argument('--calibration',type=Path)
    args=parser.parse_args()
    load_env(os.environ.get('VELA_ENV_FILE',ROOT/'.env'))
    app=Application(args.db,args.session,args.calibration)
    server=ThreadingHTTPServer(('127.0.0.1',args.port),handler_for(app))
    server.daemon_threads=True
    print(f'VELA ready: http://127.0.0.1:{args.port} | evidence: /lab',flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()

if __name__=='__main__': main()
