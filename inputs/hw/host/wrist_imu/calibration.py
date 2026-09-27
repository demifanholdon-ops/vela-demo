"""六面加速度校准：拟合、应用、验证与 canonical ID。

校准格式 version=1 字段：
  board_id, units, accel_bias[3] (m/s^2), accel_scale[3],
  gyro_bias[3] (deg/s), axis_map[3][3], temperature_range,
  validation, calibration_id

应用顺序（C++ 端必须一致）：
  accel' = axis_map @ ((accel - accel_bias) * accel_scale)
  gyro'  = axis_map @ (gyro - gyro_bias)

calibration_id 只覆盖参数字段（不含 validation / calibration_id），
canonical JSON（sort_keys、紧凑分隔符）后取 SHA256。
"""

from __future__ import annotations

import hashlib
import json

import numpy as np

G = 9.80665
VERSION = 1
FACE_LABELS = ("+x", "-x", "+y", "-y", "+z", "-z")
SCALE_RANGE = (0.5, 2.0)
MAX_FACE_VARIANCE = 0.05      # (m/s^2)^2，每面每轴静止方差上限
MIN_FACE_DURATION_S = 10.0    # 每面稳定片段最短秒数
GRAVITY_ERROR_LIMIT = 0.02    # 验证：|a|/g - 1 的最大允许比例

_PARAM_FIELDS = ("version", "board_id", "units", "accel_bias", "accel_scale",
                 "gyro_bias", "axis_map", "temperature_range")


def _face_vector(face):
    """face 可以是 ndarray(3) 或 {mean, variance, duration_s} dict。"""
    if isinstance(face, dict):
        mean = np.asarray(face["mean"], dtype=float)
        variance = face.get("variance")
        if variance is not None:
            variance = np.asarray(variance, dtype=float)
            if not np.all(np.isfinite(variance)):
                raise ValueError("face variance contains non-finite values")
            if np.any(variance > MAX_FACE_VARIANCE):
                raise ValueError(
                    f"face variance {variance.tolist()} exceeds "
                    f"{MAX_FACE_VARIANCE}: placement not stable")
        duration = face.get("duration_s")
        if duration is not None and float(duration) < MIN_FACE_DURATION_S:
            raise ValueError(
                f"face duration {duration}s < {MIN_FACE_DURATION_S}s")
    else:
        mean = np.asarray(face, dtype=float)
    if mean.shape != (3,):
        raise ValueError(f"face mean must have shape (3,), got {mean.shape}")
    if not np.all(np.isfinite(mean)):
        raise ValueError("face mean contains non-finite values")
    return mean


def fit_six_faces(means: dict, board_id: str) -> dict:
    """由六面静止均值拟合 accel bias/scale。

    模型：measured = true / scale + bias，其中 true 在该面为 ±G·e_i。
    因此 bias_i = (plus_i + minus_i)/2，scale_i = 2G/(plus_i - minus_i)。
    """
    missing = [label for label in FACE_LABELS if label not in means]
    if missing:
        raise ValueError(f"missing faces: {', '.join(missing)}")

    faces = {label: _face_vector(means[label]) for label in FACE_LABELS}

    bias = np.zeros(3)
    scale = np.zeros(3)
    for i, axis in enumerate("xyz"):
        plus = faces["+" + axis][i]
        minus = faces["-" + axis][i]
        bias[i] = (plus + minus) / 2.0
        span = plus - minus
        if span == 0.0:
            raise ValueError(f"scale for axis {axis}: plus/minus faces identical")
        scale[i] = 2.0 * G / span

    if not (np.all(np.isfinite(bias)) and np.all(np.isfinite(scale))):
        raise ValueError("fit produced non-finite parameters")
    if np.any(scale < SCALE_RANGE[0]) or np.any(scale > SCALE_RANGE[1]):
        raise ValueError(
            f"scale {scale.tolist()} outside allowed range "
            f"[{SCALE_RANGE[0]}, {SCALE_RANGE[1]}]")

    calibration = {
        "version": VERSION,
        "board_id": str(board_id),
        "units": {"accel": "m/s^2", "gyro": "deg/s"},
        "accel_bias": bias.tolist(),
        "accel_scale": scale.tolist(),
        "gyro_bias": [0.0, 0.0, 0.0],
        "axis_map": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
        "temperature_range": {"min_c": None, "max_c": None},
        "validation": {"passed": False, "reason": "not_validated"},
    }
    calibration["calibration_id"] = calibration_id(calibration)
    return calibration


def calibration_id(calibration: dict) -> str:
    """参数字段的 canonical JSON SHA256（与键序无关，可跨序列化稳定）。"""
    payload = {field: calibration[field] for field in _PARAM_FIELDS
               if field in calibration}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _check_axis_map(axis_map):
    m = np.asarray(axis_map, dtype=float)
    if m.shape != (3, 3) or not np.all(np.isfinite(m)):
        raise ValueError("axis_map must be a finite 3x3 matrix")
    if not np.allclose(m @ m.T, np.eye(3), atol=1e-6):
        raise ValueError("axis_map is not orthogonal")
    if not np.isclose(np.linalg.det(m), 1.0, atol=1e-6):
        raise ValueError("axis_map is left-handed (det != +1)")
    return m


def apply_calibration(accel, gyro, calibration: dict):
    """按比例→坐标变换的统一顺序应用校准；返回 (accel, gyro)。"""
    for name in ("accel_bias", "accel_scale", "gyro_bias"):
        values = np.asarray(calibration[name], dtype=float)
        if values.shape != (3,) or not np.all(np.isfinite(values)):
            raise ValueError(f"{name} must contain finite values")
    axis_map = _check_axis_map(calibration["axis_map"])

    accel = np.asarray(accel, dtype=float)
    gyro = np.asarray(gyro, dtype=float)
    if not (np.all(np.isfinite(accel)) and np.all(np.isfinite(gyro))):
        raise ValueError("input sample contains non-finite values")

    bias = np.asarray(calibration["accel_bias"], dtype=float)
    scale = np.asarray(calibration["accel_scale"], dtype=float)
    gyro_bias = np.asarray(calibration["gyro_bias"], dtype=float)

    accel_out = axis_map @ ((accel - bias) * scale)
    gyro_out = axis_map @ (gyro - gyro_bias)
    return accel_out, gyro_out


def validate_calibration(data: dict, board_id: str) -> dict:
    """独立验证：用拟合参数回代六面数据，检查重力模长误差。

    data = {"calibration": cal, "faces": {label: ndarray|dict}}
    """
    calibration = data["calibration"]
    if str(calibration.get("board_id")) != str(board_id):
        raise ValueError(
            f"board_id mismatch: calibration is for "
            f"{calibration.get('board_id')!r}, got {board_id!r}")

    faces = data.get("faces")
    if not faces:
        return {"passed": False, "reason": "no_faces",
                "max_gravity_error_fraction": float("inf"), "per_face": {}}

    per_face = {}
    max_err = 0.0
    for label in FACE_LABELS:
        if label not in faces:
            return {"passed": False, "reason": f"missing face {label}",
                    "max_gravity_error_fraction": float("inf"),
                    "per_face": per_face}
        mean = _face_vector(faces[label])
        corrected, _ = apply_calibration(mean, np.zeros(3), calibration)
        err = abs(float(np.linalg.norm(corrected)) / G - 1.0)
        per_face[label] = err
        max_err = max(max_err, err)

    passed = max_err <= GRAVITY_ERROR_LIMIT
    return {
        "passed": passed,
        "max_gravity_error_fraction": max_err,
        "gravity_error_limit": GRAVITY_ERROR_LIMIT,
        "per_face": per_face,
        "reason": None if passed else "gravity_error_exceeds_limit",
    }


def device_payload(calibration: dict) -> dict:
    """下发设备的参数子集（受协议 1024 字节 payload 限制）。"""
    return {
        "version": calibration["version"],
        "calibration_id": calibration["calibration_id"],
        "accel_bias": calibration["accel_bias"],
        "accel_scale": calibration["accel_scale"],
        "gyro_bias": calibration["gyro_bias"],
        "axis_map": calibration["axis_map"],
    }
