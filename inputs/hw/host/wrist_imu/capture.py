"""六面校准引导采集：实时倾角提示 + 自动打标签。

流程（每个面）：
1. 对准阶段：实时显示当前面倾角与质量等级，用户按回车确认开始
2. 采集阶段：写 face_label 事件，持续采集 >= min_seconds，期间监测静止；
   若中途大幅移动则自动延长；写 face_end 事件（含实测倾角/时长/质量）
3. 全部面完成后进入 gyro 静止段（模块平放不动 >= gyro_seconds）

事件写入会话 events.jsonl（host 时间轴，与 samples.csv 一致），
之后用 `wrist-imu calibrate --session PATH` 拟合验证。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import struct
import sys
import threading
import time

import numpy as np
import serial

from .orientation import (FACE_ORDER, best_face, grade, gravity_magnitude,
                          is_still, tilt_deg)
from .protocol import Decoder, encode_packet
from .recorder import (BATCH_HEAD, MESSAGE_ACK, MESSAGE_COMMAND,
                       MESSAGE_METADATA, MESSAGE_SAMPLES, SAMPLE,
                       SessionWriter)

ACCEL_LSB_PER_MS2 = 8192.0 / 9.80665   # ±4g: 8192 LSB/g


class _EnterFlag:
    def __init__(self):
        self.pressed = threading.Event()
        self._stop = False

    def start(self):
        def reader():
            while not self._stop:
                line = sys.stdin.readline()
                if not line:
                    time.sleep(0.2)
                    continue
                self.pressed.set()
                return
        self._t = threading.Thread(target=reader, daemon=True)
        self._t.start()


def _decode_samples(payload: bytes):
    if len(payload) < BATCH_HEAD.size:
        return []
    _, _, _, count = BATCH_HEAD.unpack_from(payload)
    if count > 10 or len(payload) != BATCH_HEAD.size + count * SAMPLE.size:
        return []
    out = []
    offset = BATCH_HEAD.size
    for _ in range(count):
        values = SAMPLE.unpack_from(payload, offset)
        offset += SAMPLE.size
        segment, seq, est_us, ax, ay, az, gx, gy, gz, flags = values
        out.append((ax, ay, az, gx, gy, gz, flags))
    return out


def _exchange(port, writer, decoder, request_id: int, command: str,
              timeout: float = 5.0):
    wire = encode_packet(MESSAGE_COMMAND, request_id,
                         json.dumps({"request_id": request_id, "command": command},
                                    separators=(",", ":")).encode())
    deadline = time.monotonic() + timeout
    retry_at = 0.0
    acked = False
    got_metadata = False
    while time.monotonic() < deadline and not (acked and got_metadata):
        now = time.monotonic()
        if now >= retry_at:
            port.write(wire)
            retry_at = now + 0.5
        data = port.read(port.in_waiting or 1)
        if not data:
            continue
        writer.ingest(data, time.monotonic_ns())
        for packet in decoder.feed(data):
            if packet.kind == MESSAGE_METADATA:
                got_metadata = True
            elif packet.kind == MESSAGE_ACK:
                try:
                    body = json.loads(packet.payload.decode())
                except Exception:
                    continue
                if body.get("request_id") == request_id and body.get("status") == "ok":
                    acked = True
    if not acked:
        raise TimeoutError(f"{command} 握手超时")


def capture_faces(args) -> int:
    writer = SessionWriter(args.output, {"hand": "calibration",
                                         "label": args.label or "six-face-capture"})
    port = None
    decoder = Decoder()
    import secrets
    base = secrets.randbits(30) * 4
    exit_code = 0
    try:
        port = serial.Serial(args.port, 115200, timeout=0.1, write_timeout=1.0)
        print("连接设备并握手 ...")
        _exchange(port, writer, decoder, base + 1, "hello")
        # hello 已带 metadata；start 开新段
        _exchange(port, writer, decoder, base + 2, "start")
        print("设备已启动数据流。\n")

        accel_window: list = []
        gyro_window: list = []
        faces_done = []

        def pump(duration_s: float, on_tick=None):
            """读取串口 duration_s 秒；维护最近1秒的加速度/角速度窗口。"""
            end = time.monotonic() + duration_s
            while time.monotonic() < end:
                data = port.read(port.in_waiting or 1)
                if data:
                    writer.ingest(data, time.monotonic_ns())
                    for packet in decoder.feed(data):
                        if packet.kind != MESSAGE_SAMPLES:
                            continue
                        for ax, ay, az, gx, gy, gz, flags in _decode_samples(packet.payload):
                            if flags & 1:      # invalid placeholder
                                continue
                            accel_window.append((ax / ACCEL_LSB_PER_MS2,
                                                 ay / ACCEL_LSB_PER_MS2,
                                                 az / ACCEL_LSB_PER_MS2))
                            gyro_window.append((gx, gy, gz))
                if len(accel_window) > 150:
                    del accel_window[:len(accel_window) - 150]
                if len(gyro_window) > 150:
                    del gyro_window[:len(gyro_window) - 150]
                if on_tick:
                    on_tick()

        enter = _EnterFlag()
        enter.start()

        face_queue = list(FACE_ORDER)
        while face_queue:
            face = face_queue.pop(0)
            print("=" * 56)
            print(f"【{face}】请把模块摆成 {face} 面朝上（重力指向该面外侧）")
            print("  实时倾角会显示在下面；<=5° 优秀，<=12° 可接受。")
            print("  摆好后按【回车】开始该面 12 秒采集。")

            # 对准阶段：实时反馈直到用户回车
            last_print = [0.0]

            def show():
                now = time.monotonic()
                if now - last_print[0] < 0.5 or len(accel_window) < 10:
                    return
                last_print[0] = now
                mean = np.mean(np.array(accel_window[-50:]), axis=0)
                tilt = tilt_deg(mean, face)
                detected, _ = best_face(mean)
                g = grade(tilt)
                mark = {"good": "✅", "ok": "🆗", "bad": "❌", "unknown": "❓"}[g]
                still = is_still(np.array(accel_window[-50:]))
                tilt_s = f"{tilt:5.1f}°" if tilt is not None else "  ---"
                print(f"\r  {mark} 倾角 {tilt_s}  等级 {g:7s} 检测到朝上面: {detected:3s} "
                      f"静止: {'是' if still else '否'}   ", end="", flush=True)

            while not enter.pressed.is_set():
                pump(0.2, on_tick=show)
            enter.pressed.clear()
            print()

            # 采集阶段
            t0 = time.monotonic_ns()
            writer.log_host_event("face_label", face=face, host_ns_device="n/a")
            print(f"  采集中 {args.face_seconds:.0f}s，请保持不动 ...")
            seg_start = time.monotonic()
            moved = False

            def watch():
                nonlocal moved
                if len(accel_window) >= 30:
                    recent = np.array(accel_window[-30:])
                    if not is_still(recent, max_std=0.35):
                        moved = True

            pump(args.face_seconds, on_tick=watch)
            # 若期间有移动，补采直到安静 3 秒（最多再补 10 秒）
            extra_deadline = time.monotonic() + 10.0
            while moved and time.monotonic() < extra_deadline:
                print("  检测到移动，补采至安静 ...")
                moved = False
                pump(3.0, on_tick=watch)
            t1 = time.monotonic_ns()

            mean = np.mean(np.array(accel_window), axis=0) if accel_window else np.zeros(3)
            tilt = tilt_deg(mean, face)
            duration = (t1 - t0) / 1e9
            g = grade(tilt)
            writer.log_host_event("face_end", face=face,
                                  tilt_deg=None if tilt is None else round(tilt, 2),
                                  duration_s=round(duration, 2), grade=g,
                                  gravity_ms2=round(gravity_magnitude(mean), 3))
            faces_done.append({"face": face, "tilt_deg": tilt, "grade": g,
                               "duration_s": round(duration, 2),
                               "gravity_ms2": round(gravity_magnitude(mean), 3)})
            mark = {"good": "✅", "ok": "🆗", "bad": "❌", "unknown": "❓"}[g]
            print(f"  {mark} {face} 完成: 倾角 {tilt if tilt is None else round(tilt,1)}°, "
                  f"时长 {duration:.1f}s, |g|={gravity_magnitude(mean):.2f} m/s²\n")
            if g == "bad" and not args.force:
                print("  ⚠️ 该面倾角过大，建议重采（输入 r 重采该面，回车继续下一面）")
                line = input("  > ").strip().lower()
                if line == "r":
                    faces_done.pop()
                    # 重写事件：标记该面作废，重新排队
                    writer.log_host_event("face_void", face=face, reason="tilt_too_large")
                    face_queue.insert(0, face)
                    continue

        # gyro 静止段
        print("=" * 56)
        print(f"最后：请把模块平放（任意面）完全静止 {args.gyro_seconds:.0f}s，"
              "用于陀螺仪零偏。按回车开始。")
        enter.pressed.clear()
        while not enter.pressed.is_set():
            pump(0.2)
        g0 = time.monotonic_ns()
        writer.log_host_event("gyro_still")
        pump(args.gyro_seconds)
        g1 = time.monotonic_ns()
        writer.log_host_event("gyro_still_end")
        print(f"  ✅ 陀螺仪静止段完成 ({(g1-g0)/1e9:.1f}s)")

        writer.log_host_event("capture_summary", faces=faces_done)
        print("\n采集汇总:")
        for f in faces_done:
            tilt = f["tilt_deg"]
            print(f"  {f['face']:3s} 倾角 {tilt if tilt is None else round(tilt,1)}° "
                  f"[{f['grade']}] {f['duration_s']:.1f}s |g|={f['gravity_ms2']}")
        print(f"\n会话目录: {writer.path}")
        print("下一步: .venv/bin/python -m wrist_imu.cli calibrate "
              f"--session {writer.path} --output data/calibration/report.json")
    except (OSError, serial.SerialException, TimeoutError) as exc:
        print(f"采集失败: {exc}", file=sys.stderr)
        exit_code = 1
    except KeyboardInterrupt:
        print("\n用户中断", file=sys.stderr)
        exit_code = 1
    finally:
        if port is not None:
            try:
                _exchange(port, writer, decoder, base + 3, "stop", timeout=2.0)
            except Exception:
                pass
            port.close()
        writer.close()
    return exit_code


def add_subcommand(sub):
    cap = sub.add_parser("capture-faces", help="引导式六面校准采集（实时倾角提示）")
    cap.add_argument("--port", required=True)
    cap.add_argument("--output", type=Path, default=Path("data/sessions"))
    cap.add_argument("--face-seconds", type=float, default=12.0,
                     help="每面采集秒数（>=10）")
    cap.add_argument("--gyro-seconds", type=float, default=15.0,
                     help="陀螺仪静止段秒数")
    cap.add_argument("--label", default="")
    cap.add_argument("--force", action="store_true",
                     help="倾角过大也不询问重采")
    cap.set_defaults(func=lambda args: capture_faces(args))
