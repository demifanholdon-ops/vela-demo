"""六面校准采集守护进程（由外部 agent 通过 stdin 驱动，无键鼠环境）。

启动即连接设备、握手、开始数据流；持续把样本写入会话并维护实时窗口。
从 stdin 逐行读取命令，结果以单行 "@@RESP <json>" 输出到 stdout。

命令：
  TILT <face>            当前对准该面的实时倾角/等级/是否静止
  STATUS                 当前最接近朝上的面 + 倾角
  CAPTURE <face> <secs>  写 face_label，采集 secs 秒（监测静止），写 face_end，返回统计
  GYRO <secs>            陀螺仪静止段（gyro_still / gyro_still_end）
  DONE                   停止采集、关闭会话，返回会话目录路径
  PING                   健康检查
"""

from __future__ import annotations

import argparse
import collections
import json
import secrets
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


def _resp(obj: dict):
    print("@@RESP " + json.dumps(obj, ensure_ascii=False), flush=True)


class Daemon:
    def __init__(self, port_path: str, output_root, label: str):
        self.port_path = port_path
        self.port: serial.Serial | None = None
        self.writer = SessionWriter(output_root, {"hand": "calibration",
                                                  "label": label})
        self.decoder = Decoder()
        self.base = secrets.randbits(30) * 4
        self.lock = threading.Lock()
        # 实时窗口：(host_ns, accel[3] m/s², gyro[3] raw, flags)
        self.recent = collections.deque(maxlen=4000)
        self.port = None
        self.running = False
        self.error = None
        self.metadata = None

    # ---- serial + handshake ----
    def _exchange(self, request_id, command, timeout=6.0):
        wire = encode_packet(MESSAGE_COMMAND, request_id,
                             json.dumps({"request_id": request_id, "command": command},
                                        separators=(",", ":")).encode())
        deadline = time.monotonic() + timeout
        retry_at = 0.0
        acked = got_meta = False
        while time.monotonic() < deadline and not (acked and got_meta):
            now = time.monotonic()
            if now >= retry_at:
                self.port.write(wire)
                retry_at = now + 0.5
            data = self.port.read(self.port.in_waiting or 1)
            if not data:
                continue
            self.writer.ingest(data, time.monotonic_ns())
            for packet in self.decoder.feed(data):
                if packet.kind == MESSAGE_METADATA:
                    got_meta = True
                    try:
                        self.metadata = json.loads(packet.payload.decode())
                    except Exception:
                        pass
                elif packet.kind == MESSAGE_ACK:
                    try:
                        body = json.loads(packet.payload.decode())
                    except Exception:
                        continue
                    if body.get("request_id") == request_id and body.get("status") == "ok":
                        acked = True
        if command == "hello" and not (acked and got_meta):
            raise TimeoutError("hello 握手超时")
        if command != "hello" and not acked:
            raise TimeoutError(f"{command} 握手超时")

    def connect(self):
        self.port = serial.Serial(self.port_path, 115200, timeout=0.1,
                                  write_timeout=1.0)
        self._exchange(self.base + 1, "hello")
        self._exchange(self.base + 2, "start")
        self.running = True
        self.thread = threading.Thread(target=self._read_loop, daemon=True)
        self.thread.start()

    def _read_loop(self):
        while self.running:
            try:
                data = self.port.read(self.port.in_waiting or 1)
            except (OSError, serial.SerialException) as exc:
                self.error = str(exc)
                self.running = False
                break
            if not data:
                continue
            ns = time.monotonic_ns()
            try:
                self.writer.ingest(data, ns)
            except OSError as exc:
                self.error = f"write failed: {exc}"
                self.running = False
                break
            for packet in self.decoder.feed(data):
                if packet.kind != MESSAGE_SAMPLES:
                    continue
                for (seg, seq, est, ax, ay, az, gx, gy, gz, flags) in self._samples(packet.payload):
                    with self.lock:
                        self.recent.append((
                            ns,
                            (ax / ACCEL_LSB_PER_MS2, ay / ACCEL_LSB_PER_MS2,
                             az / ACCEL_LSB_PER_MS2),
                            (gx, gy, gz), flags))

    @staticmethod
    def _samples(payload):
        """解析 samples 包，返回 [(segment,seq,est_us,ax,ay,az,gx,gy,gz,flags), ...]。

        SAMPLE = '<IIQhhhhhhH' -> 10 个字段，raw int16。
        """
        if len(payload) < BATCH_HEAD.size:
            return []
        _, _, _, count = BATCH_HEAD.unpack_from(payload)
        if count > 10 or len(payload) != BATCH_HEAD.size + count * SAMPLE.size:
            return []
        out, off = [], BATCH_HEAD.size
        for _ in range(count):
            v = SAMPLE.unpack_from(payload, off)
            off += SAMPLE.size
            out.append(v)
        return out

    # ---- helpers ----
    def _valid_accel(self, n=50):
        with self.lock:
            items = list(self.recent)[-n:]
        pts = [a for (_, a, _, flags) in items if not (flags & 1)]
        return np.array(pts) if pts else np.zeros((0, 3))

    def _accel_in_window(self, t0, t1):
        with self.lock:
            items = list(self.recent)
        pts = [a for (ns, a, _, flags) in items
               if t0 <= ns < t1 and not (flags & 1)]
        return np.array(pts) if pts else np.zeros((0, 3))

    # ---- commands ----
    def cmd_tilt(self, face):
        if face not in FACE_ORDER:
            return {"ok": False, "error": f"unknown face {face}"}
        acc = self._valid_accel()
        if len(acc) < 10:
            return {"ok": True, "face": face, "tilt_deg": None, "grade": "unknown",
                    "still": False, "samples": len(acc), "note": "数据不足，稍等"}
        mean = acc.mean(axis=0)
        tilt = tilt_deg(mean, face)
        det, _ = best_face(mean)
        return {"ok": True, "face": face,
                "tilt_deg": None if tilt is None else round(tilt, 1),
                "grade": grade(tilt), "detected_face": det,
                "still": bool(is_still(acc[-30:])),
                "gravity_ms2": round(gravity_magnitude(mean), 3),
                "samples": len(acc)}

    def cmd_status(self):
        acc = self._valid_accel()
        if len(acc) < 10:
            return {"ok": True, "best_face": None, "tilt_deg": None, "samples": len(acc)}
        mean = acc.mean(axis=0)
        det, tilt = best_face(mean)
        return {"ok": True, "best_face": det,
                "tilt_deg": None if tilt is None else round(tilt, 1),
                "gravity_ms2": round(gravity_magnitude(mean), 3),
                "still": bool(is_still(acc[-30:])), "samples": len(acc)}

    def cmd_capture(self, face, secs):
        if face not in FACE_ORDER:
            return {"ok": False, "error": f"unknown face {face}"}
        secs = max(10.0, float(secs))
        t0 = time.monotonic_ns()
        self.writer.log_host_event("face_label", face=face)
        # 采集期间监测静止；若移动则延长至安静（最多 +10s）
        deadline = time.monotonic() + secs
        moved = False
        while time.monotonic() < deadline:
            time.sleep(0.3)
            acc = self._valid_accel(30)
            if len(acc) >= 20 and not is_still(acc, max_std=0.35):
                moved = True
        extra_end = time.monotonic() + 10.0
        while moved and time.monotonic() < extra_end:
            moved = False
            time.sleep(3.0)
            acc = self._valid_accel(30)
            if len(acc) >= 20 and not is_still(acc, max_std=0.35):
                moved = True
        t1 = time.monotonic_ns()
        win = self._accel_in_window(t0, t1)
        if len(win) < 50:
            self.writer.log_host_event("face_end", face=face, tilt_deg=None,
                                       duration_s=round((t1 - t0) / 1e9, 2),
                                       grade="unknown", samples=len(win),
                                       note="insufficient_samples")
            return {"ok": False, "error": "采集样本不足", "samples": len(win)}
        mean = win.mean(axis=0)
        tilt = tilt_deg(mean, face)
        g = grade(tilt)
        dur = round((t1 - t0) / 1e9, 2)
        self.writer.log_host_event("face_end", face=face,
                                   tilt_deg=None if tilt is None else round(tilt, 2),
                                   duration_s=dur, grade=g,
                                   samples=int(len(win)),
                                   gravity_ms2=round(gravity_magnitude(mean), 3),
                                   accel_mean=[round(float(x), 4) for x in mean])
        return {"ok": True, "face": face,
                "tilt_deg": None if tilt is None else round(tilt, 1),
                "grade": g, "duration_s": dur, "samples": int(len(win)),
                "gravity_ms2": round(gravity_magnitude(mean), 3)}

    def cmd_gyro(self, secs):
        secs = max(5.0, float(secs))
        self.writer.log_host_event("gyro_still")
        time.sleep(secs)
        self.writer.log_host_event("gyro_still_end")
        return {"ok": True, "seconds": secs}

    def cmd_void(self, face):
        self.writer.log_host_event("face_void", face=face, reason="user_retry")
        return {"ok": True, "voided": face}

    def finish(self):
        self.running = False
        try:
            if self.port and self.port.is_open:
                self._exchange(self.base + 3, "stop", timeout=2.0)
        except Exception:
            pass
        try:
            self.writer.close()
        except Exception:
            pass
        return str(self.writer.path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", required=True)
    ap.add_argument("--output", default="data/sessions")
    ap.add_argument("--label", default="six-face-capture")
    args = ap.parse_args()

    from pathlib import Path
    d = Daemon(args.port, Path(args.output), args.label)
    try:
        d.connect()
    except Exception as exc:
        _resp({"ok": False, "stage": "connect", "error": str(exc)})
        return 1
    _resp({"ok": True, "stage": "ready", "session": str(d.writer.path),
           "board_id": (d.metadata or {}).get("board_id")})

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        cmd = parts[0].upper()
        try:
            if not d.running and cmd not in ("DONE", "PING"):
                _resp({"ok": False, "error": f"reader stopped: {d.error}"})
                continue
            if cmd == "PING":
                _resp({"ok": True, "pong": True, "running": d.running,
                       "error": d.error})
            elif cmd == "STATUS":
                _resp(d.cmd_status())
            elif cmd == "TILT":
                _resp(d.cmd_tilt(parts[1]))
            elif cmd == "CAPTURE":
                _resp(d.cmd_capture(parts[1], float(parts[2]) if len(parts) > 2 else 12))
            elif cmd == "VOID":
                _resp(d.cmd_void(parts[1]))
            elif cmd == "GYRO":
                _resp(d.cmd_gyro(float(parts[1]) if len(parts) > 1 else 15))
            elif cmd == "DONE":
                path = d.finish()
                _resp({"ok": True, "stage": "done", "session": path})
                return 0
            else:
                _resp({"ok": False, "error": f"unknown command {cmd}"})
        except Exception as exc:
            _resp({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
    path = d.finish()
    _resp({"ok": True, "stage": "eof_done", "session": path})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
