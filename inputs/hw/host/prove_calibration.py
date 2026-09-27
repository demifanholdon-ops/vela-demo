"""证据：start 设备，抓实时样本，主机端对比 raw vs 校准后数值。
证明校准真实改变了输出，并让屏幕进入活动刷新状态。"""
import json, secrets, time
import numpy as np
import serial
from wrist_imu.protocol import Decoder, encode_packet
from wrist_imu.recorder import (MESSAGE_ACK, MESSAGE_COMMAND, MESSAGE_SAMPLES,
                                BATCH_HEAD, SAMPLE)
from wrist_imu.calibration import apply_calibration

G = 9.80665
ACCEL_LSB = 8192.0 / G   # per m/s^2 (±4g)
GYRO_LSB = 32768.0 / 500.0

report = json.loads(open("data/calibration/report-0e27827d.json").read())
cal = report["calibration"]

port = serial.Serial("/dev/ttyUSB0", 115200, timeout=0.1, write_timeout=1.0)
dec = Decoder()
rid = secrets.randbits(30) * 4

def cmd(name, rid):
    return encode_packet(MESSAGE_COMMAND, rid,
                         json.dumps({"request_id": rid, "command": name},
                                    separators=(",", ":")).encode())

# hello + start，保持活动（不发 stop，让屏幕持续刷新）
for name, r in [("hello", rid+1), ("start", rid+2)]:
    wire = cmd(name, r)
    deadline = time.monotonic() + 5
    retry = 0
    acked = False
    while time.monotonic() < deadline and not acked:
        if time.monotonic() >= retry:
            port.write(wire); retry = time.monotonic() + 0.5
        data = port.read(port.in_waiting or 1)
        for p in dec.feed(data or b""):
            if p.kind == MESSAGE_ACK:
                b = json.loads(p.payload.decode())
                if b.get("request_id") == r and b.get("status") == "ok":
                    acked = True
    print(f"{name}: {'ok' if acked else 'FAILED'}")

# 抓 ~2 秒样本
acc_raw, gyr_raw = [], []
end = time.monotonic() + 2.0
while time.monotonic() < end:
    data = port.read(port.in_waiting or 1)
    if not data: continue
    for p in dec.feed(data):
        if p.kind != MESSAGE_SAMPLES: continue
        if len(p.payload) < BATCH_HEAD.size: continue
        _,_,_,count = BATCH_HEAD.unpack_from(p.payload)
        if count > 10 or len(p.payload) != BATCH_HEAD.size + count*SAMPLE.size: continue
        off = BATCH_HEAD.size
        for _ in range(count):
            v = SAMPLE.unpack_from(p.payload, off); off += SAMPLE.size
            if v[9] & 1: continue   # skip invalid placeholder
            acc_raw.append((v[3], v[4], v[5]))
            gyr_raw.append((v[6], v[7], v[8]))
port.close()   # 关闭串口但设备保持 active（屏幕继续刷新）

acc_raw = np.array(acc_raw, float); gyr_raw = np.array(gyr_raw, float)
print(f"\n抓到 {len(acc_raw)} 个样本")
acc_ms2 = acc_raw / 8192.0 * G            # ±4g: 8192 LSB/g -> m/s^2
gyr_dps = gyr_raw / GYRO_LSB

raw_mean_a = acc_ms2.mean(axis=0)
raw_mean_g = gyr_dps.mean(axis=0)
ca, cg = apply_calibration(raw_mean_a, raw_mean_g, cal)

print("\n当前姿态(静止)加速度均值 m/s²:")
print(f"  RAW : AX={raw_mean_a[0]:+.3f} AY={raw_mean_a[1]:+.3f} AZ={raw_mean_a[2]:+.3f}  |a|={np.linalg.norm(raw_mean_a):.3f}")
print(f"  CAL : AX={ca[0]:+.3f} AY={ca[1]:+.3f} AZ={ca[2]:+.3f}  |a|={np.linalg.norm(ca):.3f}")
print("\n陀螺仪均值 deg/s:")
print(f"  RAW : GX={raw_mean_g[0]:+.4f} GY={raw_mean_g[1]:+.4f} GZ={raw_mean_g[2]:+.4f}")
print(f"  CAL : GX={cg[0]:+.4f} GY={cg[1]:+.4f} GZ={cg[2]:+.4f}")
print("\n说明: 设备已 start, 屏幕现在应显示 RECORDING + 实时(校准后)六轴数值。")
