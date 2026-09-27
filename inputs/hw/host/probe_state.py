"""探针：连接设备发 hello，读取 metadata 看当前固件/校准状态。"""
import json, secrets, sys, time
import serial
from wrist_imu.protocol import Decoder, encode_packet
from wrist_imu.recorder import MESSAGE_ACK, MESSAGE_COMMAND, MESSAGE_METADATA

port = serial.Serial("/dev/ttyUSB0", 115200, timeout=0.1, write_timeout=1.0)
dec = Decoder()
rid = secrets.randbits(30) * 4 + 1
wire = encode_packet(MESSAGE_COMMAND, rid,
                     json.dumps({"request_id": rid, "command": "hello"},
                                separators=(",", ":")).encode())
deadline = time.monotonic() + 6
meta = ack = None
retry = 0.0
# 同时记录原始串口字节，判断是不是 recording 固件
raw_seen = bytearray()
while time.monotonic() < deadline and meta is None:
    now = time.monotonic()
    if now >= retry:
        port.write(wire); retry = now + 0.5
    data = port.read(port.in_waiting or 1)
    if not data:
        continue
    raw_seen += data
    for p in dec.feed(data):
        if p.kind == MESSAGE_METADATA:
            meta = json.loads(p.payload.decode())
        elif p.kind == MESSAGE_ACK:
            ack = json.loads(p.payload.decode())
print("ACK:", ack)
print("METADATA:", json.dumps(meta, ensure_ascii=False, indent=2) if meta else None)
if meta:
    print(">>> firmware:", meta.get("firmware"))
    print(">>> calibration_status:", meta.get("calibration_status"))
    print(">>> calibration_id:", meta.get("calibration_id"))
else:
    print(">>> 无 metadata 应答；可能不是 wrist-recorder 固件")
    print(">>> 原始串口前200字节:", bytes(raw_seen[:200]))
port.close()
