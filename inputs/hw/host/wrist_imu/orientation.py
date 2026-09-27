"""六面校准采集的方向判定数学（纯函数，可单元测试）。

约定：模块静止时加速度计读到的是反作用比力，朝上的轴读 +1g。
每个面有一个目标单位向量（该面朝上时，重力方向在传感器系中的投影）。
tilt = 实测单位重力向量与目标向量的夹角（度）。
"""

from __future__ import annotations

import numpy as np

G = 9.80665

# 每个面朝上时，单位加速度向量（含重力，m/s²）应指向的方向。
# +x 朝上 -> 实测 accel ≈ (+G, 0, 0)，单位化后为 +x。
FACE_TARGETS = {
    "+x": np.array([1.0, 0.0, 0.0]),
    "-x": np.array([-1.0, 0.0, 0.0]),
    "+y": np.array([0.0, 1.0, 0.0]),
    "-y": np.array([0.0, -1.0, 0.0]),
    "+z": np.array([0.0, 0.0, 1.0]),
    "-z": np.array([0.0, 0.0, -1.0]),
}
FACE_ORDER = ["+x", "-x", "+y", "-y", "+z", "-z"]

# 采集质量分级阈值（度）
GOOD_TILT = 5.0
OK_TILT = 12.0


def unit_gravity(accel_ms2) -> np.ndarray | None:
    """把加速度均值（m/s²）单位化；模长过小/非有限返回 None。"""
    a = np.asarray(accel_ms2, dtype=float)
    if a.shape != (3,) or not np.all(np.isfinite(a)):
        return None
    norm = float(np.linalg.norm(a))
    if norm < 0.5 * G:        # 远小于 1g，视为无效（自由落体/数据异常）
        return None
    return a / norm


def tilt_deg(accel_ms2, face: str) -> float | None:
    """实测加速度与目标面方向的夹角（度）；无法判定返回 None。"""
    if face not in FACE_TARGETS:
        raise ValueError(f"unknown face {face!r}")
    u = unit_gravity(accel_ms2)
    if u is None:
        return None
    cosang = float(np.clip(np.dot(u, FACE_TARGETS[face]), -1.0, 1.0))
    return float(np.degrees(np.arccos(cosang)))


def grade(tilt: float | None) -> str:
    """把倾角转成质量等级：good / ok / bad / unknown。"""
    if tilt is None:
        return "unknown"
    if tilt <= GOOD_TILT:
        return "good"
    if tilt <= OK_TILT:
        return "ok"
    return "bad"


def gravity_magnitude(accel_ms2) -> float:
    return float(np.linalg.norm(np.asarray(accel_ms2, dtype=float)))


def is_still(recent: np.ndarray, max_std: float = 0.15) -> bool:
    """recent: (N,3) m/s²；逐轴 std 都小于阈值才算静止。"""
    recent = np.asarray(recent, dtype=float)
    if recent.ndim != 2 or recent.shape[0] < 2 or recent.shape[1] != 3:
        return False
    if not np.all(np.isfinite(recent)):
        return False
    return bool(np.all(recent.std(axis=0) < max_std))


def best_face(accel_ms2) -> tuple[str, float | None]:
    """返回当前最接近朝上的面名与其倾角(度)；无法单位化时按最大分量轴提示。"""
    u = unit_gravity(accel_ms2)
    if u is None:
        a = np.asarray(accel_ms2, dtype=float)
        if a.shape == (3,) and np.all(np.isfinite(a)) and np.linalg.norm(a) > 1e-6:
            i = int(np.argmax(np.abs(a)))
            return ("+" if a[i] >= 0 else "-") + "xyz"[i], None
        return "+z", None
    best, best_tilt = "+z", 1e9
    for f in FACE_ORDER:
        cosang = float(np.clip(np.dot(u, FACE_TARGETS[f]), -1.0, 1.0))
        t = float(np.degrees(np.arccos(cosang)))
        if t < best_tilt:
            best_tilt, best = t, f
    return best, best_tilt
