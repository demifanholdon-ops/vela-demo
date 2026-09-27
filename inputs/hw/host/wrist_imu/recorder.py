"""串口会话可靠落盘：原始字节优先，解析结果仅作为索引。"""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import struct
import time
import uuid
from collections import deque

from .protocol import Decoder, Packet


MESSAGE_METADATA = 1
MESSAGE_SAMPLES = 2
MESSAGE_EVENT = 3
MESSAGE_COMMAND = 4
MESSAGE_ACK = 5
MESSAGE_TEMPERATURE = 6

BATCH_HEAD = struct.Struct("<QQHB")
SAMPLE = struct.Struct("<IIQhhhhhhH")
SAMPLE_COLUMNS = [
    "host_ns", "connection_id", "packet_seq", "read_begin_us", "read_end_us",
    "fifo_words_before", "segment_id", "sample_seq", "sample_est_us",
    "accel_x_raw", "accel_y_raw", "accel_z_raw",
    "gyro_x_raw", "gyro_y_raw", "gyro_z_raw", "flags",
]


class SessionWriter:
    def __init__(self, root: Path, user_metadata: dict):
        root = Path(root)
        root.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        self.path = root / f"{stamp}-{uuid.uuid4().hex[:8]}"
        self.path.mkdir()
        self._raw = (self.path / "raw.bin").open("wb")
        self._samples_file = (self.path / "samples.csv").open("w", newline="", encoding="utf-8")
        self._samples = csv.DictWriter(self._samples_file, fieldnames=SAMPLE_COLUMNS)
        self._samples.writeheader()
        self._events = (self.path / "events.jsonl").open("w", encoding="utf-8")
        self._decoder = Decoder()
        self._closed = False
        self.failed = False
        self._last_flush_ns = 0
        self._metadata = {
            "schema_version": 1,
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "user": dict(user_metadata),
            "connections": [],
            "time_notes": "sample_est_us is device-estimated; host_ns is receive time",
        }
        self._connection_id = 0
        self._boot_id = None
        self._have_metadata = False
        self._seen_packet_seq: set[int] = set()
        self._recent_packet_seq: deque[int] = deque()
        self._expected_packet_seq: int | None = None
        self._write_metadata()

    def _write_metadata(self) -> None:
        tmp = self.path / "metadata.json.tmp"
        tmp.write_text(json.dumps(self._metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(self.path / "metadata.json")

    def _event(self, event: str, host_ns: int | None, **details) -> None:
        row = {"event": event, "host_ns": host_ns, "connection_id": self._connection_id, **details}
        self._events.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")

    def _drain_decode_errors(self, host_ns: int) -> None:
        while self._decoder.errors:
            error = self._decoder.errors.popleft()
            self._event("decode_error", host_ns, reason=error.reason, encoded_size=error.encoded_size)

    def ingest(self, data: bytes, host_ns: int) -> None:
        if self._closed:
            raise RuntimeError("session is closed")
        try:
            # 原始输入必须先持久化，解析错误也不得丢失证据。
            self._raw.write(data)
            packets = self._decoder.feed(data)
            self._drain_decode_errors(host_ns)
            for packet in packets:
                self._consume(packet, host_ns)
            if not self._last_flush_ns or host_ns - self._last_flush_ns >= 1_000_000_000:
                self.flush()
                self._last_flush_ns = host_ns
        except OSError:
            self.failed = True
            raise

    def _consume(self, packet: Packet, host_ns: int) -> None:
        if packet.kind == MESSAGE_METADATA:
            self._consume_metadata(packet, host_ns)
            return
        if packet.seq in self._seen_packet_seq:
            self._event("duplicate_packet", host_ns, packet_seq=packet.seq, kind=packet.kind)
            return
        self._track_sequence(packet.seq, host_ns)
        if packet.kind == MESSAGE_SAMPLES:
            self._consume_samples(packet, host_ns)
        elif packet.kind == MESSAGE_EVENT:
            self._consume_device_json(packet, host_ns, "device_event")
        elif packet.kind == MESSAGE_ACK:
            self._consume_device_json(packet, host_ns, "device_ack")
        elif packet.kind == MESSAGE_TEMPERATURE:
            self._consume_temperature(packet, host_ns)
        else:
            self._event("unknown_message", host_ns, packet_seq=packet.seq, kind=packet.kind,
                        payload_hex=packet.payload.hex())

    def _track_sequence(self, seq: int, host_ns: int) -> None:
        if self._expected_packet_seq is not None and seq != self._expected_packet_seq:
            self._event("packet_gap", host_ns, expected=self._expected_packet_seq, received=seq)
        if len(self._recent_packet_seq) == 4096:
            self._seen_packet_seq.discard(self._recent_packet_seq.popleft())
        self._recent_packet_seq.append(seq)
        self._seen_packet_seq.add(seq)
        self._expected_packet_seq = (seq + 1) & 0xFFFFFFFF

    def _consume_metadata(self, packet: Packet, host_ns: int) -> None:
        try:
            metadata = json.loads(
                packet.payload.decode("utf-8"),
                parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f"non-finite {value}")),
            )
            if not isinstance(metadata, dict):
                raise ValueError("metadata must be object")
            required = ("boot_id", "chip_id", "odr_hz", "accel_range_g", "gyro_range_dps")
            if any(key not in metadata for key in required):
                raise ValueError("missing required device configuration")
            if not isinstance(metadata["boot_id"], str) or not metadata["boot_id"]:
                raise ValueError("boot_id must be a non-empty string")
            if any(not isinstance(metadata[key], (int, float)) or not math.isfinite(metadata[key])
                   for key in required[1:]):
                raise ValueError("device configuration must be finite numeric values")
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            self._event("bad_metadata", host_ns, packet_seq=packet.seq, reason=str(exc))
            return
        boot_id = metadata.get("boot_id")
        if not self._have_metadata or boot_id != self._boot_id:
            self._connection_id += 1
            self._boot_id = boot_id
            self._seen_packet_seq.clear()
            self._recent_packet_seq.clear()
            self._expected_packet_seq = None
            self._metadata["connections"].append({
                "connection_id": self._connection_id,
                "host_ns": host_ns,
                "packet_seq": packet.seq,
                "device": metadata,
                "metadata_updates": [],
            })
        else:
            connection = self._metadata["connections"][-1]
            if metadata != connection["device"]:
                connection["metadata_updates"].append({
                    "host_ns": host_ns, "packet_seq": packet.seq, "device": metadata,
                })
        self._have_metadata = True
        if packet.seq not in self._seen_packet_seq:
            self._track_sequence(packet.seq, host_ns)
        self._event("device_metadata", host_ns, packet_seq=packet.seq, boot_id=boot_id)
        self._write_metadata()

    def _consume_samples(self, packet: Packet, host_ns: int) -> None:
        if not self._have_metadata:
            self._event("samples_without_metadata", host_ns, packet_seq=packet.seq,
                        payload_bytes=len(packet.payload))
            return
        if len(packet.payload) < BATCH_HEAD.size:
            self._event("bad_samples", host_ns, packet_seq=packet.seq, reason="short_header")
            return
        read_begin, read_end, fifo_words, count = BATCH_HEAD.unpack_from(packet.payload)
        expected = BATCH_HEAD.size + count * SAMPLE.size
        if count > 10 or len(packet.payload) != expected:
            self._event("bad_samples", host_ns, packet_seq=packet.seq, reason="length",
                        count=count, payload_bytes=len(packet.payload))
            return
        offset = BATCH_HEAD.size
        for _ in range(count):
            values = SAMPLE.unpack_from(packet.payload, offset)
            offset += SAMPLE.size
            segment, sample_seq, sample_us, ax, ay, az, gx, gy, gz, flags = values
            self._samples.writerow(dict(zip(SAMPLE_COLUMNS, [
                host_ns, self._connection_id, packet.seq, read_begin, read_end, fifo_words,
                segment, sample_seq, sample_us, ax, ay, az, gx, gy, gz, flags,
            ])))

    def _consume_device_json(self, packet: Packet, host_ns: int, event: str) -> None:
        try:
            details = json.loads(packet.payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            details = {"payload_hex": packet.payload.hex(), "json_valid": False}
        self._event(event, host_ns, packet_seq=packet.seq, details=details)

    def _consume_temperature(self, packet: Packet, host_ns: int) -> None:
        try:
            details = json.loads(
                packet.payload.decode("utf-8"),
                parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f"non-finite {value}")),
            )
            raw = details["raw"]
            valid = details["valid"]
            if not isinstance(raw, int) or not isinstance(valid, bool):
                raise ValueError("invalid temperature fields")
            details["celsius"] = raw / 512.0 + 23.0 if valid else None
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            details = {"payload_hex": packet.payload.hex(), "valid": False, "reason": str(exc)}
        self._event("device_temperature", host_ns, packet_seq=packet.seq, details=details)

    def log_host_event(self, event: str, **details) -> None:
        """电脑侧事件（如六面校准的 face_label/face_end），与样本同一时间轴。"""
        if self._closed:
            raise RuntimeError("session is closed")
        self._event(event, time.monotonic_ns(), **details)

    def flush(self) -> None:
        self._raw.flush()
        self._samples_file.flush()
        self._events.flush()

    def close(self) -> None:
        if self._closed:
            return
        self._decoder.finish()
        self._drain_decode_errors(0)
        self.flush()
        self._write_metadata()
        self._raw.close()
        self._samples_file.close()
        self._events.close()
        self._closed = True


def recover_session(raw_path: Path, output_root: Path) -> Path:
    """从 raw.bin 重建索引文件；只导出带 CRC 且完整结束的包。"""
    writer = SessionWriter(output_root, {"recovered_from": str(Path(raw_path).resolve())})
    host_ns = 0
    with Path(raw_path).open("rb") as source:
        while chunk := source.read(65536):
            writer.ingest(chunk, host_ns)
            host_ns += 1
    path = writer.path
    writer.close()
    return path
