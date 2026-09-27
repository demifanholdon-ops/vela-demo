"""Local signal evidence. No mood classifier; all clocks and units stay explicit."""
import csv
import hashlib
import io
import json
import math
import statistics as stats
import struct
import wave
from collections import Counter, defaultdict
from pathlib import Path

VERSION = 'vela.evidence.1'
G = 9.80665

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def percentile(values, q):
    if not values:
        return None
    values = sorted(values)
    x = (len(values) - 1) * q
    a = int(x)
    return values[a] + (values[min(a + 1, len(values) - 1)] - values[a]) * (x - a)

def read_json(path):
    return json.loads(Path(path).read_text())

def verify_calibration(cal, board):
    if cal['board_id'] != board:
        raise ValueError('calibration_board_mismatch')
    fields = ('version','board_id','units','accel_bias','accel_scale','gyro_bias','axis_map','temperature_range')
    digest = hashlib.sha256(json.dumps({k:cal[k] for k in fields}, sort_keys=True,
        separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()).hexdigest()
    if digest != cal['calibration_id'] or not cal['validation']['passed']:
        raise ValueError('calibration_invalid')
    if cal['units'] != {'accel':'m/s^2','gyro':'deg/s'}:
        raise ValueError('calibration_units_mismatch')

def corrected(raw, device, cal):
    a = [(raw[i] * device['accel_range_g'] / 32768 * G - cal['accel_bias'][i]) * cal['accel_scale'][i] for i in range(3)]
    g = [(raw[i+3] * device['gyro_range_dps'] / 32768 - cal['gyro_bias'][i]) * math.pi / 180 for i in range(3)]
    return ([sum(m[i]*a[i] for i in range(3)) for m in cal['axis_map']],
            [sum(m[i]*g[i] for i in range(3)) for m in cal['axis_map']])

def analyze_session(folder, calibration_file):
    folder = Path(folder)
    meta = read_json(folder/'metadata.json')
    supplied = read_json(calibration_file)
    cal = supplied['calibration']
    devices = {int(c['connection_id']):c['device'] for c in meta['connections']}
    for device in devices.values():
        verify_calibration(cal, device['board_id'])
        if device['sensor'] != 'BMI323' or device['accel_unit'] != 'raw_int16' or device['gyro_unit'] != 'raw_int16':
            raise ValueError('unsupported_device_contract')
    with (folder/'samples.csv').open(newline='') as f:
        rows = [{k:int(v) for k,v in row.items()} for row in csv.DictReader(f)]
    if not rows:
        raise ValueError('empty_session')
    groups = defaultdict(list)
    previous = {}
    gaps = 0
    time_errors = 0
    for r in rows:
        key = (r['connection_id'], r['segment_id'])
        if r['connection_id'] not in devices:
            raise ValueError('missing_connection_metadata')
        p = previous.get(key)
        if p:
            gaps += max(0, r['sample_seq'] - p['sample_seq'] - 1)
            time_errors += int(r['sample_est_us'] <= p['sample_est_us'] or r['sample_seq'] <= p['sample_seq'])
        previous[key] = r
        groups[key].append(r)
    windows = []
    expected = 0
    for key, rs in groups.items():
        device = devices[key[0]]
        start = rs[0]['sample_est_us']
        expected += max(len(rs), round((rs[-1]['sample_est_us']-start)/1e6*device['odr_hz'])+1)
        bins = defaultdict(list)
        for r in rs:
            bins[(r['sample_est_us']-start)//30000000].append(r)
        for index, chunk in sorted(bins.items()):
            acc, gyro, jerk = [], [], []
            last = None
            valid = 0
            for r in chunk:
                raw = [r[k+'_raw'] for k in ('accel_x','accel_y','accel_z','gyro_x','gyro_y','gyro_z')]
                if any(abs(v) > 32768 or v > 32767 for v in raw):
                    raise ValueError('raw_not_int16')
                if r['flags'] & 7:
                    last = None
                    continue
                a, g = corrected(raw, device, cal)
                acc.append(math.sqrt(sum(x*x for x in a)))
                gyro.append(math.sqrt(sum(x*x for x in g)))
                if last and r['sample_seq']==last[0]+1:
                    dt = (r['sample_est_us']-last[1])/1e6
                    if 0 < dt <= 2/device['odr_hz']:
                        jerk.append(math.sqrt(sum((a[i]-last[2][i])**2 for i in range(3)))/dt)
                last=(r['sample_seq'],r['sample_est_us'],a)
                valid += 1
            duration = (chunk[-1]['sample_est_us']-chunk[0]['sample_est_us'])/1e6 + 1/device['odr_hz']
            continuity = min(1, valid/max(1,round(duration*device['odr_hz'])))
            coverage = min(1,valid/(30*device['odr_hz']))
            local_time_errors=sum(int(b['sample_est_us']<=a['sample_est_us'] or b['sample_seq']<=a['sample_seq']) for a,b in zip(chunk,chunk[1:]))
            windows.append({'connection_id':key[0], 'segment_id':key[1], 'window_index':index,
                'start_device_us':chunk[0]['sample_est_us'], 'end_device_us':chunk[-1]['sample_est_us'],
                'duration_s':round(duration,3), 'sample_count':len(chunk), 'valid_count':valid,
                'coverage':round(coverage,6), 'continuity':round(continuity,6), 'expected_window_s':30, 'partial':duration<29.7, 'usable':coverage >= .99 and valid >= 100 and not local_time_errors and not any(r['flags'] & 8 or r['flags'] & ~31 for r in chunk),
                'accel_norm_mean_m_s2':stats.mean(acc) if acc else None,
                'accel_norm_sd_m_s2':stats.pstdev(acc) if acc else None,
                'gyro_norm_p95_rad_s':percentile(gyro,.95), 'jerk_p95_m_s3':percentile(jerk,.95),
                'time_estimated':any(r['flags']&16 for r in chunk),
                'time_degraded':any(r['flags']&8 for r in chunk)})
    events = [json.loads(x) for x in (folder/'events.jsonl').read_text().splitlines() if x.strip()]
    # Recompute all six face means from raw counts, rather than merely displaying supplied JSON.
    spans, opened = {}, {}
    for event in events:
        if event.get('event')=='face_label':
            opened[event['face']] = event['host_ns']
        if event.get('event')=='face_end' and event['face'] in opened:
            spans[event['face']] = (opened[event['face']],event['host_ns'])
        if event.get('event')=='face_void':
            spans.pop(event['face'],None)
    face_check = {}
    for face, (a,b) in spans.items():
        rs = [r for r in rows if a<=r['host_ns']<b and not r['flags']&1]
        vectors=[]
        for r in rs:
            raw=[r[k+'_raw'] for k in ('accel_x','accel_y','accel_z','gyro_x','gyro_y','gyro_z')]
            vectors.append(corrected(raw,devices[r['connection_id']],cal)[0])
        if not vectors: continue
        means=[stats.mean(v[i] for v in vectors) for i in range(3)]
        face_check[face]={'samples':len(rs),'gravity_error_fraction':abs(math.sqrt(sum(v*v for v in means))/G-1)}
    return {'schema':VERSION,'source':'real_hardware_calibration' if spans else 'real_hardware_session','session_id':folder.name,
        'sensor':next(iter(devices.values()))['sensor'], 'odr_hz':next(iter(devices.values()))['odr_hz'],
        'board_id':cal['board_id'],'calibration_id':cal['calibration_id'],
        'sample_count':len(rows),'expected_samples':expected,'sequence_missing':gaps,
        'coverage':len(rows)/expected,'flags':dict(Counter(str(r['flags']) for r in rows)),
        'time_errors':time_errors,'event_counts':dict(Counter(e.get('event') for e in events)),
        'calibration':{'validation_kind':'six_face_replay' if spans else 'stored_calibration_only','passed':len(face_check)==6 and max(x['gravity_error_fraction'] for x in face_check.values())<=.02,
            'max_gravity_error_fraction':max((x['gravity_error_fraction'] for x in face_check.values()),default=None),'faces':face_check},
        'windows':windows,'baseline_status':'insufficient','sync':{'status':'unknown','fusion_allowed':False},
        'files':{name:sha(folder/name) for name in ('metadata.json','samples.csv','events.jsonl','raw.bin')},
        'limitations':['六面台架校准，不是佩戴/情绪语料','设备时间为估计值；host_ns 仅为接收时间',
            '无配对音频、无个人基线；不推断情绪、睡眠或疾病','重力误差是校准集回代误差，不是独立临床验证']}

def analyze_wav(blob, speaker):
    if speaker not in ('self_confirmed','unknown','overlap'):
        raise ValueError('invalid_speaker_status')
    with wave.open(io.BytesIO(blob),'rb') as w:
        rate, channels, width, frames = w.getframerate(),w.getnchannels(),w.getsampwidth(),w.getnframes()
        if width!=2 or channels not in (1,2) or not 8000<=rate<=48000 or not 0<frames/rate<=120:
            raise ValueError('wav_requires_pcm16_8_to_48khz_max120s')
        raw=w.readframes(frames)
    if len(raw)!=frames*channels*2:
        raise ValueError('truncated_wav')
    values=struct.unpack('<'+'h'*(len(raw)//2),raw)
    mono=[sum(values[i:i+channels])/channels/32768 for i in range(0,len(values),channels)]
    rms=math.sqrt(sum(v*v for v in mono)/len(mono))
    clipped=sum(abs(v)>=32760 for v in values)/len(values)
    eligible=rms>.002 and clipped<.01 and speaker=='self_confirmed'
    return {'schema':'vela.audio.1','sha256':hashlib.sha256(blob).hexdigest(),
        'source':'file_import','sample_rate':rate,'channels':channels,'sample_count':frames,
        'duration_s':frames/rate,'rms':rms,'clipping_fraction':clipped,'speaker':speaker,
        'quality':'usable_descriptive' if eligible else 'abstain',
        'sync':{'status':'unknown','fusion_allowed':False},
        'limitations':['本人身份为用户确认，未经声纹验证','未运行 ASR，不输出语速/语义/情绪','音频与 IMU 并列，不伪造同步','原始文件仅在内存分析后丢弃']}

def fit_clock(anchors):
    if len(anchors)<3:
        return {'status':'unknown','fusion_allowed':False}
    xs=[float(x['device_us'])/1000 for x in anchors]
    ys=[float(x['host_ns'])/1e6 for x in anchors]
    uncertainty=max(float(x['uncertainty_ms']) for x in anchors)
    if not all(math.isfinite(x) for x in xs+ys+[uncertainty]) or uncertainty<0 or any(xs[i]<=xs[i-1] or ys[i]<=ys[i-1] for i in range(1,len(xs))):
        raise ValueError('invalid_clock_anchors')
    xm,ym=stats.mean(xs),stats.mean(ys)
    a=sum((x-xm)*(y-ym) for x,y in zip(xs,ys))/sum((x-xm)**2 for x in xs)
    b=ym-a*xm
    error=max(abs(a*x+b-y) for x,y in zip(xs,ys))+uncertainty
    ok=error<=100 and .99<=a<=1.01
    return {'status':'measured' if ok else 'rejected','a':a,'b_ms':b,'sync_error_ms':error,
        'fusion_allowed':ok,'valid_device_us':[xs[0]*1000,xs[-1]*1000]}
