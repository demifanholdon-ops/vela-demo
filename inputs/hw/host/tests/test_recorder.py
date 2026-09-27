import csv
import json
import struct

import pytest

from wrist_imu.protocol import encode_packet
from wrist_imu.recorder import (MESSAGE_METADATA, MESSAGE_SAMPLES, MESSAGE_TEMPERATURE,
                                SessionWriter, recover_session)


BATCH_HEAD = struct.Struct("<QQHB")
SAMPLE = struct.Struct("<IIQhhhhhhH")


def sample_packet(packet_seq, segment, first_sample_seq=0):
    rows = b"".join(
        SAMPLE.pack(segment, first_sample_seq + i, 900_000 + i * 10_000,
                    100+i, 200+i, 300+i, 10+i, 20+i, 30+i, 0)
        for i in range(2)
    )
    payload = BATCH_HEAD.pack(990_000, 1_000_000, 12, 2) + rows
    return encode_packet(MESSAGE_SAMPLES, packet_seq, payload)


def metadata(seq, boot_id):
    body = {"boot_id": boot_id, "chip_id": 0x43, "odr_hz": 100,
            "accel_range_g": 4, "gyro_range_dps": 500}
    return encode_packet(MESSAGE_METADATA, seq, json.dumps(body).encode())


def read_rows(path):
    with path.open(newline="") as stream:
        return list(csv.DictReader(stream))


def test_raw_survives_bad_frame(tmp_path):
    w = SessionWriter(tmp_path, {"hand": "unknown"})
    w.ingest(b"broken\0", 123)
    path = w.path
    w.close()
    assert (path / "raw.bin").read_bytes() == b"broken\0"
    assert "decode_error" in (path / "events.jsonl").read_text()


def test_metadata_samples_bad_packet_and_restart(tmp_path):
    wire = metadata(0, "boot-a") + sample_packet(1, 1) + b"bad\0"
    wire += metadata(0, "boot-b") + sample_packet(1, 2, 10)
    w = SessionWriter(tmp_path, {"hand": "left", "label": "wave"})
    # 任意切块覆盖增量解析。
    for offset in range(0, len(wire), 7):
        w.ingest(wire[offset:offset+7], 1_000 + offset)
    path = w.path
    w.close()
    rows = read_rows(path / "samples.csv")
    assert len(rows) == 4
    assert [row["connection_id"] for row in rows] == ["1", "1", "2", "2"]
    events = (path / "events.jsonl").read_text()
    assert "decode_error" in events and "device_metadata" in events
    saved = json.loads((path / "metadata.json").read_text())
    assert saved["user"]["hand"] == "left"
    assert len(saved["connections"]) == 2


def test_samples_without_metadata_are_quarantined(tmp_path):
    w = SessionWriter(tmp_path, {})
    w.ingest(sample_packet(3, 1), 1)
    path = w.path
    w.close()
    assert read_rows(path / "samples.csv") == []
    assert "samples_without_metadata" in (path / "events.jsonl").read_text()


def test_duplicate_packet_does_not_duplicate_samples_and_wrap_is_contiguous(tmp_path):
    w = SessionWriter(tmp_path, {})
    w.ingest(metadata(0xFFFFFFFE, "one"), 1)
    packet = sample_packet(0xFFFFFFFF, 1)
    w.ingest(packet + packet, 2)
    w.ingest(metadata(0, "two"), 3)
    path = w.path
    w.close()
    assert len(read_rows(path / "samples.csv")) == 2
    assert "duplicate_packet" in (path / "events.jsonl").read_text()


def test_truncated_tail_only_exports_complete_packet(tmp_path):
    complete = metadata(0, "one") + sample_packet(1, 1)
    tail = sample_packet(2, 1, 2)[:-4]
    w = SessionWriter(tmp_path, {})
    w.ingest(complete + tail, 1)
    path = w.path
    w.close()
    assert len(read_rows(path / "samples.csv")) == 2
    assert "truncated" in (path / "events.jsonl").read_text()


def test_disk_error_is_fatal(tmp_path):
    class FullDisk:
        def write(self, _):
            raise OSError(28, "No space left on device")
    w = SessionWriter(tmp_path, {})
    w._raw = FullDisk()
    with pytest.raises(OSError, match="No space"):
        w.ingest(b"x", 1)
    assert w.failed


def test_metadata_validation_update_and_temperature(tmp_path):
    w = SessionWriter(tmp_path, {})
    w.ingest(encode_packet(MESSAGE_METADATA, 0, b'{"boot_id":"bad","odr_hz":NaN}'), 1)
    w.ingest(metadata(1, "same"), 2)
    changed = {"boot_id": "same", "chip_id": 0x43, "odr_hz": 200,
               "accel_range_g": 4, "gyro_range_dps": 500}
    w.ingest(encode_packet(MESSAGE_METADATA, 2, json.dumps(changed).encode()), 3)
    temp = {"read_us": 123, "raw": 512, "valid": True}
    w.ingest(encode_packet(MESSAGE_TEMPERATURE, 3, json.dumps(temp).encode()), 4)
    path = w.path
    w.close()
    saved = json.loads((path / "metadata.json").read_text())
    assert len(saved["connections"]) == 1
    assert saved["connections"][0]["metadata_updates"][0]["device"]["odr_hz"] == 200
    events = [json.loads(line) for line in (path / "events.jsonl").read_text().splitlines()]
    assert any(row["event"] == "bad_metadata" for row in events)
    measured = next(row for row in events if row["event"] == "device_temperature")
    assert measured["details"]["celsius"] == 24.0


def test_recent_packet_tracking_is_bounded(tmp_path):
    w = SessionWriter(tmp_path, {})
    w.ingest(metadata(0, "bounded"), 1)
    for seq in range(1, 4200):
        w._track_sequence(seq, seq)
    assert len(w._seen_packet_seq) == 4096
    w.close()


def test_recover_complete_packets_from_raw_file(tmp_path):
    source = tmp_path / "source.bin"
    complete = metadata(0, "recovery") + sample_packet(1, 1)
    source.write_bytes(complete + sample_packet(2, 1, 2)[:-3])
    path = recover_session(source, tmp_path / "recovered")
    assert (path / "raw.bin").read_bytes() == source.read_bytes()
    assert len(read_rows(path / "samples.csv")) == 2
    assert "truncated" in (path / "events.jsonl").read_text()
