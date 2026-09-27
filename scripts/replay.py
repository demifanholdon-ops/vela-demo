"""Generate a fresh versioned engineering report without starting HTTP."""
import argparse
import datetime
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.evidence import analyze_session
from backend.server import ROOT

parser=argparse.ArgumentParser()
parser.add_argument('--session',type=Path,default=next((ROOT/'inputs/hw/data').iterdir()))
parser.add_argument('--calibration',type=Path,default=ROOT/'inputs/report-0e27827d.json')
parser.add_argument('--output',type=Path)
args=parser.parse_args()
output=args.output or ROOT/'artifacts'/('replay-'+datetime.datetime.now().strftime('%Y%m%dT%H%M%S')+'.json')
if output.exists():raise SystemExit('Refusing to overwrite an existing report; choose a new output path.')
report=analyze_session(args.session,args.calibration)
output.parent.mkdir(parents=True,exist_ok=True)
output.write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False))
print(json.dumps({'output':str(output),'samples':report['sample_count'],'calibration_passed':report['calibration']['passed'],'windows':len(report['windows'])}))
