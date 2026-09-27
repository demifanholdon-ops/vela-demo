"""wrist-imu 命令行入口。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time
import secrets

import serial

import numpy as np

from .protocol import Decoder, encode_packet
from .recorder import MESSAGE_ACK, MESSAGE_COMMAND, MESSAGE_METADATA, SessionWriter, recover_session


def _command(request_id: int, command: str) -> bytes:
    payload = json.dumps({"request_id": request_id, "command": command}, separators=(",", ":")).encode()
    return encode_packet(MESSAGE_COMMAND, request_id, payload)


def _json_packet(packet):
    try:
        return json.loads(packet.payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}


def _exchange(port, writer, decoder, request_id: int, command: str, timeout: float,
              require_metadata: bool = False) -> None:
    wire = _command(request_id, command)
    deadline = time.monotonic() + timeout
    retry_at = 0.0
    got_metadata = not require_metadata
    got_ack = False
    while time.monotonic() < deadline and not (got_metadata and got_ack):
        now = time.monotonic()
        if now >= retry_at:
            port.write(wire)
            retry_at = now + 0.5
        data = port.read(port.in_waiting or 1)
        if not data:
            continue
        host_ns = time.monotonic_ns()
        writer.ingest(data, host_ns)
        for packet in decoder.feed(data):
            if packet.kind == MESSAGE_METADATA:
                got_metadata = True
            elif packet.kind == MESSAGE_ACK:
                body = _json_packet(packet)
                if body.get("request_id") == request_id and body.get("status") == "ok":
                    got_ack = True
    if not (got_metadata and got_ack):
        raise TimeoutError(f"{command} 握手超时")


def record(args: argparse.Namespace) -> int:
    writer = SessionWriter(args.output, {"hand": args.hand, "label": args.label})
    port = None
    started = False
    exit_code = 0
    try:
        port = serial.Serial(args.port, 115200, timeout=0.1, write_timeout=1.0)
        decoder = Decoder()
        request_base = secrets.randbits(30) * 4
        # 开串口可能复位设备；重复 hello 直到同时收到本次 metadata 与匹配 ACK。
        _exchange(port, writer, decoder, request_base + 1, "hello", 8.0, require_metadata=True)
        _exchange(port, writer, decoder, request_base + 2, "start", 3.0)
        started = True
        deadline = time.monotonic() + args.duration if args.duration else None
        last_receive = time.monotonic()
        while deadline is None or time.monotonic() < deadline:
            data = port.read(port.in_waiting or 1)
            if data:
                writer.ingest(data, time.monotonic_ns())
                decoder.feed(data)
                last_receive = time.monotonic()
            elif time.monotonic() - last_receive > args.receive_timeout:
                raise TimeoutError(f"{args.receive_timeout:g}s 内未收到设备数据")
    except KeyboardInterrupt:
        print("记录已由用户停止", file=sys.stderr)
    except (OSError, serial.SerialException, TimeoutError) as exc:
        print(f"记录或保存失败: {exc}", file=sys.stderr)
        exit_code = 1
    finally:
        if port is not None:
            if started:
                try:
                    _exchange(port, writer, decoder, request_base + 3, "stop", 2.0)
                except (OSError, serial.SerialException, TimeoutError) as exc:
                    print(f"停止应答失败: {exc}", file=sys.stderr)
                    exit_code = 1
            port.close()
        try:
            writer.close()
        except OSError as exc:
            print(f"保存失败: {exc}", file=sys.stderr)
            exit_code = 1
    if exit_code == 0:
        print(writer.path)
    return exit_code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="wrist-imu")
    sub = parser.add_subparsers(dest="subcommand", required=True)
    rec = sub.add_parser("record", help="从串口记录原始 IMU 会话")
    rec.add_argument("--port", required=True)
    rec.add_argument("--output", type=Path, default=Path("data/sessions"))
    rec.add_argument("--duration", type=float, default=60.0)
    rec.add_argument("--receive-timeout", type=float, default=3.0)
    rec.add_argument("--hand", choices=("left", "right", "unknown"), default="unknown")
    rec.add_argument("--label", default="")
    rec.set_defaults(func=record)
    recover = sub.add_parser("recover", help="从 raw.bin 恢复完整有效包")
    recover.add_argument("--raw", type=Path, required=True)
    recover.add_argument("--output", type=Path, default=Path("data/recovered"))
    recover.set_defaults(func=lambda args: (print(recover_session(args.raw, args.output)) or 0))
    cal = sub.add_parser("calibrate", help="从记录会话拟合六面校准并独立验证")
    cal.add_argument("--session", type=Path, required=True)
    cal.add_argument("--output", type=Path, required=True,
                     help="报告输出路径（JSON）；失败时只含原因，不生成伪造校准")
    cal.set_defaults(func=_calibrate)
    from .capture import add_subcommand
    add_subcommand(sub)
    return parser


def _calibrate(args: argparse.Namespace) -> int:
    from .session_calibration import calibrate_session
    report = calibrate_session(args.session, args.output)
    if report["ok"]:
        cal = report["calibration"]
        print(f"校准成功: {args.output}")
        print(f"  calibration_id: {cal['calibration_id'][:16]}...")
        print(f"  accel_bias: {np.round(cal['accel_bias'], 3).tolist()}")
        print(f"  accel_scale: {np.round(cal['accel_scale'], 4).tolist()}")
        print(f"  gyro_bias: {np.round(cal['gyro_bias'], 3).tolist()}")
        print(f"  最大重力误差: "
              f"{cal['validation']['max_gravity_error_fraction']*100:.2f}% (限值 2%)")
        return 0
    print(f"校准失败: {report.get('reason')}", file=sys.stderr)
    print(f"详情见报告: {args.output}", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
