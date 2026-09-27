import hashlib
import json
import os
import subprocess
import threading
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
LOCK=threading.Lock()

def config():
    python=Path(os.environ.get('VELA_ASR_PYTHON',str(ROOT/'.venv/bin/python')))
    model=Path(os.environ.get('VELA_ASR_MODEL',str(ROOT/'models/whisper-base')))
    return python,model

def available():
    python,model=config()
    return python.is_file() and (model/'model.bin').is_file()

def transcribe(raw):
    if not available(): raise ValueError('asr_not_configured')
    if not raw or len(raw)>14500000: raise ValueError('audio_size')
    if not LOCK.acquire(blocking=False): raise ValueError('asr_busy')
    try:
        python,model=config()
        env={k:v for k,v in os.environ.items() if k in ('PATH','HOME','TMPDIR','LANG','SYSTEMROOT')}
        env.update({'HF_HUB_OFFLINE':'1','TOKENIZERS_PARALLELISM':'false','PYTHONDONTWRITEBYTECODE':'1'})
        result=subprocess.run([str(python),'-B',str(ROOT/'backend/asr_worker.py'),str(model)],input=raw,
            stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=100,env=env)
        if result.returncode or len(result.stdout)>100000: raise ValueError('asr_failed')
        value=json.loads(result.stdout)
        if not isinstance(value.get('text'),str) or not value['text'].strip(): raise ValueError('no_speech')
        value['sha256']=hashlib.sha256(raw).hexdigest()
        return value
    finally: LOCK.release()
