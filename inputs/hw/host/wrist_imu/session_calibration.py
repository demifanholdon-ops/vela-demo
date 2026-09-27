"""六面校准会话处理：从 record 会话提取面数据、拟合、验证、报告。

约定（与计划 Task 5 一致）：
- samples.csv 中 accel/gyro 为 int16 原始值；±4g -> 8192 LSB/g，
  ±500dps -> 65.536 LSB/dps（metadata 中 accel_range_g / gyro_range_dps 为准）。
- 面标签由电脑侧写入 events.jsonl：
    {"event": "face_label", "face": "+x", "host_ns": t0}
    {"event": "face_end",   "face": "+x", "host_ns": t1}
  一对 face_label/face_end 之间、且 flags==0（质量有效）的样本参与该面统计。
- gyro 偏置取独立的静止段：
    {"event": "gyro_still", "host_ns": t0} / {"event": "gyro_still_end", "host_ns": t1}
  没有静止段时 gyro_bias 保持 0，并在报告中标注。
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np

from .calibration import (FACE_LABELS, fit_six_faces, validate_calibration,
                          calibration_id)

MAX_FACE_STD = 0.35   # m/s^2，单面每轴 std 上限（对应方差约 0.12，配合稳定判据）


def _lsb_per_unit(metadata_device: dict) -> tuple[float, float]:
    accel_g = float(metadata_device.get("accel_range_g", 4))
    gyro_dps = float(metadata_device.get("gyro_range_dps", 500))
    return 32768.0 / accel_g, 32768.0 / gyro_dps


def load_session(session_path: Path) -> dict:
    """读取会话目录，返回 metadata/samples/events 的轻量结构。"""
    session_path = Path(session_path)
    metadata = json.loads((session_path / "metadata.json").read_text(encoding="utf-8"))
    connections = metadata.get("connections") or []
    if not connections:
        raise ValueError("session has no device metadata (no connections)")
    device = connections[-1]["device"]

    samples = []
    with (session_path / "samples.csv").open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            samples.append(row)
    events = []
    events_path = session_path / "events.jsonl"
    if events_path.exists():
        for line in events_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                events.append(json.loads(line))
    return {"metadata": metadata, "device": device,
            "samples": samples, "events": events}


def _still_spans(events: list[dict], start_name: str,
                 end_name: str) -> list[tuple[str, int, int]]:
    """配对 start/end 事件为区间；face_void 会移除该面最近一个已配对区间。

    void_name 固定为 "face_void"，用于六面采集重采场景。
    """
    spans, opens = [], {}
    for event in events:
        name = event.get("event")
        if name == start_name:
            opens[event.get("face") or "_"] = int(event["host_ns"])
        elif name == end_name:
            key = event.get("face") or "_"
            if key in opens:
                spans.append((key, opens.pop(key), int(event["host_ns"])))
        elif name == "face_void":
            face = event.get("face")
            # 移除该面最后一个区间（重采前的作废数据）
            for i in range(len(spans) - 1, -1, -1):
                if spans[i][0] == face:
                    del spans[i]
                    break
    return spans


def extract_faces(session: dict, min_duration_s: float = 10.0) -> dict:
    """返回 {label: {"mean": (3,), "variance": (3,), "duration_s": float}} 与缺失面列表。"""
    accel_lsb, gyro_lsb = _lsb_per_unit(session["device"])
    spans = _still_spans(session["events"], "face_label", "face_end")
    faces, missing = {}, []

    for label in FACE_LABELS:
        rows = [s for (key, t0, t1) in spans if key == label
                for s in session["samples"]
                if not (int(s["flags"]) & 1) and t0 <= int(s["host_ns"]) < t1]
        if not rows:
            missing.append({"face": label, "reason": "no_labelled_samples"})
            continue
        acc = np.array([[int(s["accel_x_raw"]), int(s["accel_y_raw"]), int(s["accel_z_raw"])]
                        for s in rows], dtype=float) / accel_lsb * 9.80665
        duration = (int(rows[-1]["host_ns"]) - int(rows[0]["host_ns"])) / 1e9
        variance = acc.var(axis=0)
        if duration < min_duration_s:
            missing.append({"face": label, "reason": f"duration {duration:.1f}s < {min_duration_s:.0f}s"})
            continue
        if np.any(np.sqrt(variance) > MAX_FACE_STD):
            missing.append({"face": label,
                            "reason": f"unstable placement, std {np.sqrt(variance).round(3).tolist()}"})
            continue
        faces[label] = {"mean": acc.mean(axis=0), "variance": variance,
                        "duration_s": duration, "samples": len(rows)}
    return {"faces": faces, "missing": missing}


def extract_gyro_bias(session: dict) -> tuple[np.ndarray, str | None]:
    """独立静止段 gyro 偏置 (deg/s)。无静止段 -> ([0,0,0], reason)。"""
    _, gyro_lsb = _lsb_per_unit(session["device"])
    spans = _still_spans(session["events"], "gyro_still", "gyro_still_end")
    rows = [s for (key, t0, t1) in spans
            for s in session["samples"]
            if not (int(s["flags"]) & 1) and t0 <= int(s["host_ns"]) < t1]
    if len(rows) < 100:
        return np.zeros(3), "no_still_segment"
    gyro = np.array([[int(s["gyro_x_raw"]), int(s["gyro_y_raw"]), int(s["gyro_z_raw"])]
                     for s in rows], dtype=float) / gyro_lsb
    return gyro.mean(axis=0), None


def calibrate_session(session_path: Path, output_path: Path) -> dict:
    """完整流程：加载会话 -> 提取六面+gyro -> 拟合 -> 独立验证 -> 写报告。

    失败时不生成 calibration 文件，只写报告（含缺失面/拒绝原因），
    返回 dict 带 "ok": False。绝不伪造成功。
    """
    session = load_session(session_path)
    # 设备 metadata 自带 board_id（来自 efuse MAC），必须直接沿用，
    # 否则下发时 board_id 校验不匹配。chip_id 仅用于回退。
    device = session["device"]
    board_id = device.get("board_id") or f"esp32s3-{device.get('chip_id', 'unknown')}"

    report = {
        "session": str(Path(session_path).resolve()),
        "board_id": board_id,
        "ok": False,
    }
    face_result = extract_faces(session)
    report["faces"] = {k: {"mean": v["mean"].tolist(),
                           "variance": v["variance"].tolist(),
                           "duration_s": round(v["duration_s"], 2),
                           "samples": v["samples"]}
                       for k, v in face_result["faces"].items()}
    report["missing_faces"] = face_result["missing"]

    gyro_bias, gyro_reason = extract_gyro_bias(session)
    report["gyro_bias_dps"] = gyro_bias.tolist()
    report["gyro_bias_source"] = gyro_reason or "still_segment"

    if face_result["missing"]:
        report["reason"] = "missing faces: " + ", ".join(
            f"{m['face']}({m['reason']})" for m in face_result["missing"])
        _write_report(output_path, report)
        return report

    means = {k: v["mean"] for k, v in face_result["faces"].items()}
    try:
        calibration = fit_six_faces(means, board_id)
    except ValueError as exc:
        report["reason"] = f"fit rejected: {exc}"
        _write_report(output_path, report)
        return report

    if gyro_reason is None:
        calibration["gyro_bias"] = gyro_bias.tolist()
        calibration["calibration_id"] = calibration_id(calibration)

    validation = validate_calibration({"calibration": calibration, "faces": means},
                                      board_id)
    calibration["validation"] = validation
    report["calibration"] = calibration
    report["validation"] = validation
    report["ok"] = bool(validation["passed"])
    if not report["ok"]:
        report["reason"] = f"validation failed: {validation}"
    _write_report(output_path, report)
    return report


def _write_report(output_path: Path, report: dict) -> None:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    def _default(value):
        if isinstance(value, np.ndarray):
            return value.tolist()
        if isinstance(value, (np.floating, np.integer)):
            return value.item()
        raise TypeError(f"not serializable: {type(value)}")

    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=_default) + "\n",
        encoding="utf-8")
