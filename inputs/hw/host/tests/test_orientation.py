"""orientation.py 单元测试。"""
import numpy as np
import pytest

from wrist_imu.orientation import (G, best_face, grade, gravity_magnitude,
                                   is_still, tilt_deg, unit_gravity)


def test_tilt_zero_when_perfectly_aligned():
    for face, target in [("+x", [G, 0, 0]), ("-x", [-G, 0, 0]),
                         ("+y", [0, G, 0]), ("-y", [0, -G, 0]),
                         ("+z", [0, 0, G]), ("-z", [0, 0, -G])]:
        assert tilt_deg(target, face) == pytest.approx(0.0, abs=1e-6)


def test_tilt_known_angle():
    # 绕 y 轴旋转 30°：+z 面的倾角应为 30°
    ang = np.radians(30)
    a = np.array([G * np.sin(ang), 0.0, G * np.cos(ang)])
    assert tilt_deg(a, "+z") == pytest.approx(30.0, abs=1e-6)
    # 同一个向量对 -z 面应为 150°
    assert tilt_deg(a, "-z") == pytest.approx(150.0, abs=1e-6)


def test_tilt_independent_of_magnitude():
    # 未标定 scale 时模长不是精确 1g，倾角判定应不受影响
    a = np.array([1.05 * G, 0, 0])
    assert tilt_deg(a, "+x") == pytest.approx(0.0, abs=1e-6)


def test_unit_gravity_rejects_bad_input():
    assert unit_gravity([0, 0, 0]) is None
    assert unit_gravity([0, 0, 0.1]) is None      # 模长过小
    assert unit_gravity([np.nan, 0, G]) is None
    assert unit_gravity([1, 2]) is None


def test_tilt_none_on_freefall():
    assert tilt_deg([0, 0, 0.2], "+z") is None


def test_grade_thresholds():
    assert grade(0.0) == "good"
    assert grade(5.0) == "good"
    assert grade(5.1) == "ok"
    assert grade(12.0) == "ok"
    assert grade(12.1) == "bad"
    assert grade(90.0) == "bad"
    assert grade(None) == "unknown"


def test_best_face_picks_closest():
    ang = np.radians(8)
    a = np.array([0, G * np.sin(ang), G * np.cos(ang)])
    face, tilt = best_face(a)
    assert face == "+z"
    assert tilt == pytest.approx(8.0, abs=1e-6)


def test_best_face_fallback_without_valid_magnitude():
    face, tilt = best_face([0.05, -0.3, 0.1])   # 模长远小于 g
    assert face == "-y"
    assert tilt is None


def test_is_still():
    still = np.tile([0, 0, G], (30, 1)) + np.random.default_rng(1).normal(0, 0.01, (30, 3))
    assert is_still(still)
    moving = np.tile([0, 0, G], (30, 1)) + np.random.default_rng(2).normal(0, 2.0, (30, 3))
    assert not is_still(moving)
    assert not is_still(np.zeros((1, 3)))
    assert not is_still(np.zeros((0, 3)))


def test_gravity_magnitude():
    assert gravity_magnitude([0, 0, G]) == pytest.approx(G)
