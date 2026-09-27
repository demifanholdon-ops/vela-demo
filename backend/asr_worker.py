"""Optional local-only ASR worker. Accepts audio bytes on stdin; does not download models."""
import io
import json
import os
import sys

def main():
    import av
    from faster_whisper import WhisperModel
    raw=sys.stdin.buffer.read(14500001)
    if not raw or len(raw)>14500000: raise ValueError('audio_size')
    with av.open(io.BytesIO(raw)) as container:
        stream=next((s for s in container.streams if s.type=='audio'),None)
        if stream is None: raise ValueError('no_audio')
        seconds=0
        for frame in container.decode(stream):
            seconds+=frame.samples/frame.sample_rate
            if seconds>120.5: raise ValueError('audio_max_120_seconds')
    if seconds<.25: raise ValueError('audio_too_short')
    model=WhisperModel(sys.argv[1],device='cpu',compute_type='int8',cpu_threads=4,local_files_only=True)
    segments,_=model.transcribe(io.BytesIO(raw),language='zh',beam_size=3,condition_on_previous_text=False,
        vad_filter=True,temperature=0,vad_parameters={'min_speech_duration_ms':250,'min_silence_duration_ms':500})
    items=[{'start_s':round(s.start,2),'end_s':round(s.end,2),'text':s.text.strip()} for s in segments]
    text=''.join(s['text'] for s in items).strip()
    if not text: raise ValueError('no_speech_detected')
    print(json.dumps({'text':text,'segments':items,'duration_s':round(seconds,2),'model':'faster-whisper-base-local'},ensure_ascii=False))

if __name__=='__main__':
    try: main()
    except Exception: print(json.dumps({'error':'local_asr_failed'}));sys.exit(1)
