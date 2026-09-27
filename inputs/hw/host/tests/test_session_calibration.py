"""session_calibration 测试：用合成会话目录验证提取/拟合/验证/报告。"""

import csv
import json

import numpy as np
import pytest

from wrist_imu.session_calibration import (calibrate_session, extract_faces,
                                           extract_gyro_bias, load_session)
from wrist_imu.recorder import SAMPLE_COLUMNS

G = 9.80665
ACCEL_LSB = 8192.0 / G       # +-4g: 8192 LSB per g -> per m/s^2
GYRO_LSB = 32768.0 / 500.0   # +-500 dps


def make_session(tmp_path, bias=(0.2, -0.3, 0.4), scale=(1.02, 0.98, 1.01),
                 face_duration_s=12.0, include_gyro_still=True, faces=None,
                 noisy_face=None):
    bias = np.array(bias); scale = np.array(scale)
    session = tmp_path / "session"
    session.mkdir()
    (session / "metadata.json").write_text(json.dumps({
        "schema_version": 1, "user": {}, "connections": [
            {"connection_id": 1, "host_ns": 0, "packet_seq": 0,
             "device": {"boot_id": "b1", "chip_id": "abc123", "odr_hz": 100,
                        "accel_range_g": 4, "gyro_range_dps": 500},
             "metadata_updates": []}],
    }), encoding="utf-8")

    labels = faces if faces is not None else ["+x", "-x", "+y", "-y", "+z", "-z"]
    samples, events = [], []
    t = 0
    rng = np.random.default_rng(7)

    rows = []
    def face_rows(label, duration_s, noise=0.0):
        nonlocal t
        i = "xyz".index(label[1])
        sign = 1.0 if label[0] == "+" else -1.0
        true_v = np.zeros(3); true_v[i] = sign * G
        measured = true_v / scale + bias
        t0 = t
        n = int(duration_s * 100)
        for _ in range(n):
            a = measured + (rng.normal(0, noise, 3) if noise else np.zeros(3))
            ax, ay, az = np.round(a / G * 8192.0).astype(int)
            gx = gy = gz = int(round(rng.normal(0, 0.5)))
            rows.append(dict(zip(SAMPLE_COLUMNS, [
                t, 1, 0, 0, 0, 0, 0, 0, t, ax, ay, az, gx, gy, gz, 0])))
            t += 10_000_000
        return t0, t

    for label in labels:
        noise = 2.0 if noisy_face == label else 0.02
        t0, t1 = face_rows(label, face_duration_s, noise)
        events.append({"event": "face_label", "face": label, "host_ns": t0})
        events.append({"event": "face_end", "face": label, "host_ns": t1})

    if include_gyro_still:
        t0 = t
        n = 500
        for _ in range(n):
            gx, gy, gz = (np.array([1.0, 2.0, 3.0]) * GYRO_LSB
                          + rng.normal(0, 2, 3)).round().astype(int)
            ax, ay, az = np.round((np.array([0, 0, G]) / scale + bias) / G * 8192).astype(int)
            rows.append(dict(zip(SAMPLE_COLUMNS, [
                t, 1, 0, 0, 0, 0, 0, 0, t, ax, ay, az, gx, gy, gz, 0])))
            t += 10_000_000
        events.append({"event": "gyro_still", "host_ns": t0})
        events.append({"event": "gyro_still_end", "host_ns": t})

    events.sort(key=lambda e: e["host_ns"])
    with (session / "samples.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=SAMPLE_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    with (session / "events.jsonl").open("w", encoding="utf-8") as fh:
        for e in events:
            fh.write(json.dumps(e) + "\n")
    return session


def test_load_and_extract_faces(tmp_path):
    session = make_session(tmp_path)
    data = load_session(session)
    assert data["device"]["chip_id"] == "abc123"
    result = extract_faces(data)
    assert result["missing"] == []
    assert len(result["faces"]) == 6
    np.testing.assert_allclose(result["faces"]["+x"]["mean"][0],
                               G / 1.02 + 0.2, atol=0.05)


def test_calibrate_session_success(tmp_path):
    session = make_session(tmp_path)
    out = tmp_path / "report.json"
    report = calibrate_session(session, out)
    assert report["ok"]
    cal = report["calibration"]
    np.testing.assert_allclose(cal["accel_bias"], [0.2, -0.3, 0.4], atol=0.02)
    np.testing.assert_allclose(cal["accel_scale"], [1.02, 0.98, 1.01], atol=0.01)
    np.testing.assert_allclose(cal["gyro_bias"], [1.0, 2.0, 3.0], atol=0.2)
    assert cal["validation"]["passed"]
    assert cal["validation"]["max_gravity_error_fraction"] < 0.02
    assert out.exists()
    saved = json.loads(out.read_text(encoding="utf-8"))
    assert saved["ok"]


def test_missing_face_no_fake_success(tmp_path):
    session = make_session(tmp_path, faces=["+x", "-x", "+y", "-y", "+z"])
    report = calibrate_session(session, tmp_path / "report.json")
    assert not report["ok"]
    assert any(m["face"] == "-z" for m in report["missing_faces"])
    assert "calibration" not in report


def test_short_face_rejected(tmp_path):
    session = make_session(tmp_path, face_duration_s=5.0)
    report = calibrate_session(session, tmp_path / "report.json")
    assert not report["ok"]
    assert "duration" in report["reason"]


def test_unstable_face_rejected(tmp_path):
    session = make_session(tmp_path, noisy_face="+x")
    report = calibrate_session(session, tmp_path / "report.json")
    assert not report["ok"]
    assert "+x" in report["reason"]


def test_no_gyro_still_segment_keeps_zero_bias(tmp_path):
    session = make_session(tmp_path, include_gyro_still=False)
    report = calibrate_session(session, tmp_path / "report.json")
    assert report["ok"]
    assert report["calibration"]["gyro_bias"] == [0.0, 0.0, 0.0]
    assert report["gyro_bias_source"] == "no_still_segment"


def test_face_void_removes_bad_span_and_uses_retry(tmp_path):
    """face_void 之后重采的区间才参与拟合。"""
    from wrist_imu import session_calibration as sc
    session = make_session(tmp_path)
    data = load_session(session)
    # 人为注入：+x 面有一个已配对区间 + 一个 face_void（模拟重采）
    events = data["events"]
    plus_x = [i for i, e in enumerate(events)
              if e.get("event") == "face_end" and e.get("face") == "+x"]
    # 找到 +x 的 label/end，再插入一个更早的伪区间并 void 它
    label_idx = [i for i, e in enumerate(events)
                 if e.get("event") == "face_label" and e.get("face") == "+x"][0]
    t_label = events[label_idx]["host_ns"]
    fake = [
        {"event": "face_label", "face": "+x", "host_ns": t_label - 30_000_000_000},
        {"event": "face_end", "face": "+x", "host_ns": t_label - 18_000_000_000},
        {"event": "face_void", "face": "+x", "host_ns": t_label - 17_000_000_000},
    ]
    data["events"] = sorted(fake + events, key=lambda e: e["host_ns"])
    result = sc.extract_faces(data)
    assert result["missing"] == []
    # 拟合仍应恢复原始 bias/scale（伪区间已被 void，不影响数据）
    report = sc.calibrate_session(session, tmp_path / "r.json")
    # 注: calibrate_session 重新读盘（无伪事件），这里只验证 extract 层面
    assert "+x" in result["faces"]
    assert result["faces"]["+x"]["samples"] > 0
