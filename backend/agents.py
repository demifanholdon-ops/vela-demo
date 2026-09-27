"""Versioned, inspectable agent graph. Rules run locally; only explanation is generative."""
import json
from datetime import datetime, timezone, timedelta
import os
import urllib.request
from urllib.parse import urlparse

VERSION='vela.agents.2'
ACTIONS={
    'high': [('pause','把下一件事先写下来，给自己留两分钟。'),('quiet','如果愿意，先把周围的声音调轻一点。')],
    'low': [('water','先把水杯拿到身边，这一步就够了。'),('curtain','如果愿意，把窗帘拉开一点点。')],
    'stable': [('note','记下一件今天想留住的小事。'),('review','回看一条记录，留意什么对自己有帮助。')]}
OBSERVATIONS={
    'hardware':'当前展示的是实采硬件会话，可以检查采样与校准依据。',
    'estimated_time':'设备采样时间经过估计，尚未与音频建立同步证据。',
    'baseline_missing':'个人基线不足，目前只展示描述统计。',
    'quality_abstain':'当前窗口质量不足，停止解释这个窗口。'}
LIMITATIONS={
    'not_clinical':'这不是疾病诊断或发作预测。',
    'no_paired_audio':'没有同步配对的本人音频，不能做多模态状态判断。',
    'calibration_only':'工程采样与校准不构成疾病或情绪判断依据。'}
QUESTIONS={'context':'你愿意补充当时正在做什么吗？','confirm':'这条记录符合你的感受吗？'}

def cloud_payload(report, window=None):
    # Deliberate allowlist. No text entries, IDs, clocks, raw arrays, voiceprints or audio.
    payload = {'source':report['source'],'sample_count':report['sample_count'],
        'coverage':round(report['coverage'],4),'calibration_passed':report['calibration']['passed'],
        'baseline_status':report['baseline_status'],'sync_status':report['sync']['status'],
        'allowed_observations':list(OBSERVATIONS),'allowed_limitations':list(LIMITATIONS),
        'allowed_questions':list(QUESTIONS)}
    if window is not None:
        w=report['windows'][window]
        payload['selected_window']={k:w.get(k) for k in ('duration_s','valid_count','coverage','accel_norm_mean_m_s2','gyro_norm_p95_rad_s','jerk_p95_m_s3')}
    return payload

def validate_model(result):
    if not isinstance(result,dict) or set(result)!={'observations','hypotheses','limitations','questions'}:
        raise ValueError('model_schema')
    for field, allowed in [('observations',OBSERVATIONS),('limitations',LIMITATIONS),('questions',QUESTIONS)]:
        vals=result[field]
        if not isinstance(vals,list) or len(vals)>4 or any(not isinstance(x,str) or x not in allowed for x in vals):
            raise ValueError('model_unsupported_claim')
    if result['hypotheses']!=[] or not {'not_clinical','no_paired_audio'}.issubset(result['limitations']):
        raise ValueError('model_missing_boundary')
    if 'quality_abstain' in result['observations']:
        raise ValueError('model_unsupported_quality_claim')
    return result

def complete_json(system, payload, max_tokens=400):
    base=os.environ.get('AI_BASE_URL','').rstrip('/')
    key=os.environ.get('AI_API_KEY','')
    model=os.environ.get('AI_MODEL','')
    if not base or not key or not model:
        raise RuntimeError('not_configured')
    if urlparse(base).scheme!='https':
        raise RuntimeError('https_required')
    body={'model':model,'temperature':0,'max_tokens':max_tokens,'response_format':{'type':'json_object'},
        'messages':[{'role':'system','content':system},{'role':'user','content':json.dumps(payload,ensure_ascii=False)}]}
    req=urllib.request.Request(base+'/chat/completions',data=json.dumps(body).encode(),
        headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
    # No redirects: credentials must never follow an unexpected endpoint.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,*args,**kwargs): return None
    with urllib.request.build_opener(NoRedirect).open(req,timeout=15) as response:
        raw=response.read(65537)
    if len(raw)>65536:
        raise ValueError('model_response_too_large')
    content=json.loads(raw)['choices'][0]['message']['content']
    return json.loads(content)

def completion(payload):
    return validate_model(complete_json('Summarize engineering evidence, never diagnose. Return only JSON with observations, hypotheses, limitations, questions arrays. Use only provided allowed IDs. hypotheses must be []. Include not_clinical and no_paired_audio in limitations. Do not output quality_abstain. No inventions or tool calls.',payload))

def run(report, mode='stable', consent=False, window=None, feedback=None, model_call=None, preferences=None, personal_plan=None):
    if mode not in ACTIONS or type(consent) is not bool:
        raise ValueError('invalid_agent_request')
    quality_ok=(bool(report['windows']) and any(w['usable'] for w in report['windows']) and report['coverage']>=.99 and not report.get('time_errors',0)) if window is None else (0<=window<len(report['windows']) and report['windows'][window]['usable'])
    trace=[{'agent':'QualityAgent','status':('session_summary' if window is None else 'pass') if quality_ok else 'abstain',
        'reason':'descriptive_evidence_only' if quality_ok else 'window_quality_insufficient'},
        {'agent':'EvidenceAgent','status':'descriptive','baseline':'insufficient','fusion':False}]
    result={'observations':['hardware','estimated_time','baseline_missing'] if quality_ok else ['quality_abstain'],
        'hypotheses':[],'limitations':list(LIMITATIONS),'questions':['context']}
    source='local_rules'
    reason='cloud_not_consented'
    if consent and quality_ok:
        try:
            result=validate_model((model_call or completion)(cloud_payload(report,window)))
            source='cloud_model';reason=None
        except Exception as exc:
            # No upstream exception content in logs or user responses: it may contain credentials.
            reason='not_configured' if str(exc)=='not_configured' else 'cloud_unavailable_or_invalid'
    elif not quality_ok:
        reason='quality_abstain'
    choices=[(x['id'],x['text']) for x in (personal_plan or []) if x['mode']==mode] or ACTIONS[mode]
    cutoff=(datetime.now(timezone.utc)-timedelta(hours=24)).isoformat()
    rejected={x['action_id'] for x in (feedback or []) if x['mode']==mode and (x['result']=='avoid' or (x['result']=='skip' and x.get('created_at',cutoff)>=cutoff))}
    rejected.update((preferences or {}).get(mode,[]))
    action=next((x for x in choices if x[0] not in rejected),None)
    trace.extend([{'agent':'ExplanationAgent','status':source,'fallback_reason':reason},
        {'agent':'SupportAgent','status':'manual_mode_only','mode':mode,'action_id':action[0] if action else None},
        {'agent':'JournalAgent','status':'await_user_confirmation'}])
    return {'schema':VERSION,'source':source,'fallback_reason':reason,'mode':mode,'mode_source':'user_selected',
        'observations':[OBSERVATIONS[x] for x in result['observations']], 'hypotheses':[],
        'limitations':[LIMITATIONS[x] for x in result['limitations']],
        'questions':[QUESTIONS[x] for x in result['questions']],
        'action':{'id':action[0],'text':action[1]} if action else None,
        'trace':trace,'device_commands':[], 'cloud_payload_fields':list(cloud_payload(report,window)) if source=='cloud_model' else []}
