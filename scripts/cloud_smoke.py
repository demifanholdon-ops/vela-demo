"""One optional live request using synthetic engineering metadata; no user records."""
import json
import os
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.server import load_env
from backend import agents

load_env(os.environ.get('VELA_ENV_FILE',Path(__file__).resolve().parents[1]/'.env'))
fixture={'source':'synthetic_engineering_test','sample_count':3000,'coverage':1.0,
    'calibration':{'passed':True},'baseline_status':'insufficient','sync':{'status':'unknown'},'windows':[]}
result=agents.run(fixture,consent=True)
print(json.dumps({'source':result['source'],'fallback_reason':result['fallback_reason'],
    'trace':result['trace'],'sent_data':'synthetic engineering metadata only'},ensure_ascii=False,indent=2))
sys.exit(0 if result['source']=='cloud_model' else 1)
