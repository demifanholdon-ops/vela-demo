"""把校准文件下发到设备（set_calibration），验证 ACK 与 metadata 回写。

用法: .venv/bin/python -m wrist_imu.push_calibration --port /dev/ttyUSB0 \
          --calibration data/calibration/report-0e27827d.json
"""
from __future__ import annotations

import argparse
import json
import secrets
from pathlib import Path
import sys
import time

import serial

from .calibration import device_payload
from .protocol import Decoder, encode_packet
from .recorder import MESSAGE_ACK, MESSAGE_COMMAND, MESSAGE_METADATA


def push(port_path: str, cal_report_path: Path, timeout: float = 8.0) -> int:
    report = json.loads(Path(cal_report_path).read_text(encoding="utf-8"))
    if not report.get("ok"):
        print("校准报告未通过验证(ok=False)，拒绝下发。", file=sys.stderr)
        return 1
    calibration = report["calibration"]
    payload = device_payload(calibration)
    body = json.dumps({"request_id": 0, "command": "set_calibration",
                       "args": payload}, separators=(",", ":"))
    if len(body.encode()) > 1024:
        print(f"payload {len(body.encode())}B 超过协议 1024B 限制", file=sys.stderr)
        return 1

    port = serial.Serial(port_path, 115200, timeout=0.1, write_timeout=1.0)
    decoder = Decoder()
    rid = secrets.randbits(30) * 4 + 1

    # 先 hello 拿 metadata（确认 board_id 与连接），再下发
    def exchange(req_id, command, args=None, need_meta=False):
        msg = {"request_id": req_id, "command": command}
        if args is not None:
            msg["args"] = args
        wire = encode_packet(MESSAGE_COMMAND, req_id,
                             json.dumps(msg, separators=(",", ":")).encode())
        deadline = time.monotonic() + timeout
        retry = 0.0
        ack = None
        meta = None
        while time.monotonic() < deadline and (ack is None or (need_meta and meta is None)):
            now = time.monotonic()
            if now >= retry:
                port.write(wire)
                retry = now + 0.5
            data = port.read(port.in_waiting or 1)
            if not data:
                continue
            for packet in decoder.feed(data):
                if packet.kind == MESSAGE_METADATA:
                    try:
                        meta = json.loads(packet.payload.decode())
                    except Exception:
                        meta = None
                elif packet.kind == MESSAGE_ACK:
                    try:
                        b = json.loads(packet.payload.decode())
                    except Exception:
                        continue
                    if b.get("request_id") == req_id:
                        ack = b
        return ack, meta

    hello_ack, hello_meta = exchange(rid, "hello", need_meta=True)
    if not hello_ack or hello_ack.get("status") != "ok":
        print(f"hello 失败: {hello_ack}", file=sys.stderr)
        port.close(); return 1
    board = (hello_meta or {}).get("board_id")
    cal_board = calibration.get("board_id")
    print(f"设备 board_id: {board}")
    print(f"校准 board_id: {cal_board}")
    if board != cal_board:
        print("⚠️ board_id 不匹配：此校准不属于该设备，拒绝下发。", file=sys.stderr)
        port.close(); return 1

    # 下发校准
    ack, _ = exchange(rid + 1, "set_calibration", args=payload)
    print(f"set_calibration ACK: {ack}")
    if not ack or ack.get("status") != "ok":
        print("下发未成功。", file=sys.stderr)
        port.close(); return 1

    # 触发 metadata 重发，确认 calibration_status=applied
    ack2, meta2 = exchange(rid + 2, "hello", need_meta=True)
    print(f"下发后 metadata: calibration_status="
          f"{(meta2 or {}).get('calibration_status')}, "
          f"calibration_id={(meta2 or {}).get('calibration_id')}")
    ok = (meta2 or {}).get("calibration_status") == "applied" and \
         (meta2 or {}).get("calibration_id") == calibration["calibration_id"]
    # 停止
    exchange(rid + 3, "stop")
    port.close()
    print("✅ 下发验证通过：设备已应用校准并回报 applied。" if ok
          else "⚠️ ACK ok 但 metadata 未确认 applied，请检查。")
    return 0 if ok else 2


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", required=True)
    ap.add_argument("--calibration", required=True, type=Path)
    args = ap.parse_args()
    return push(args.port, args.calibration)


if __name__ == "__main__":
    raise SystemExit(main())
