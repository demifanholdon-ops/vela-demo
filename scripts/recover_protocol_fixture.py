"""Recover one known wire packet from supplied raw capture; no encoder-under-test used.
The archive omitted test/fixtures/protocol-v1.json. This adds a recorded-device
fixture, not the missing original fixture or an independently compiled MCU test.
"""
import hashlib
import json
from pathlib import Path
import struct
import zlib
root = Path(__file__).resolve().parents[1]
relative = 'inputs/hw/data/20260926T141442.230441Z-0e27827d/raw.bin'
raw = (root / relative).read_bytes()
offset = 0
for frame in raw.split(b'\0'):
    start = offset
    offset += len(frame) + 1
    if not frame:
        continue
    # Decode COBS blocks independently of wrist_imu.protocol.
    decoded = bytearray()
    position = 0
    try:
        while position < len(frame):
            code = frame[position]
            if not code or position + code > len(frame):
                raise ValueError('invalid block')
            decoded.extend(frame[position + 1:position + code])
            position += code
            if code < 255 and position < len(frame):
                decoded.append(0)
        if len(decoded) < 14:
            continue
        body, checksum = decoded[:-4], decoded[-4:]
        magic, version, kind, size, seq = struct.unpack_from('<2sBBHI', body)
        if magic != b'WI' or version != 1 or size != len(body) - 10:
            continue
        if zlib.crc32(body) & 0xffffffff != int.from_bytes(checksum, 'little'):
            continue
        result = {'kind':kind,'seq':seq,'payload_hex':body[10:].hex(),
            'wire_hex':(frame+b'\0').hex(),'provenance':{
                'source':relative,'byte_offset':start,'raw_sha256':hashlib.sha256(raw).hexdigest(),
                'note':'Recovered captured-device packet; original cross-language fixture absent from supplied archive.'}}
        path = root / 'inputs/hw/test/fixtures/protocol-v1.json'
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(result,indent=2)+'\n')
        print(f'Recovered recorded packet at offset {start}, kind {kind}, seq {seq}.')
        break
    except (ValueError, struct.error):
        continue
else:
    raise SystemExit('No valid recorded packet found.')
