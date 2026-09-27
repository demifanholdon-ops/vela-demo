import copy
import json

import numpy as np
import pytest

from wrist_imu.calibration import (apply_calibration, calibration_id,
                                   fit_six_faces, validate_calibration)


G = 9.80665


def synthetic_faces(bias=None, scale=None):
    bias = np.array([0.2, -0.3, 0.4]) if bias is None else np.asarray(bias)
    scale = np.array([1.02, 0.98, 1.01]) if scale is None else np.asarray(scale)
    means = {}
    for i, axis in enumerate("xyz"):
        for sign, label in ((1, "+"), (-1, "-")):
            value = np.zeros(3)
            value[i] = sign * G
            means[label + axis] = value / scale + bias
    return means, bias, scale


def test_recover_bias_scale_and_candidate_not_active():
    means, bias, scale = synthetic_faces()
    calibration = fit_six_faces(means, "board-test")
    np.testing.assert_allclose(calibration["accel_bias"], bias)
    np.testing.assert_allclose(calibration["accel_scale"], scale)
    assert calibration["version"] == 1
    assert not calibration["validation"]["passed"]
    assert calibration["calibration_id"] == calibration_id(calibration)


def test_apply_order_is_scale_then_axis_map_and_gyro_bias():
    calibration = fit_six_faces(synthetic_faces()[0], "board-test")
    calibration["gyro_bias"] = [1.0, 2.0, 3.0]
    calibration["axis_map"] = [[0, 1, 0], [-1, 0, 0], [0, 0, 1]]
    accel, gyro = apply_calibration(np.array([1.2, 1.7, 3.4]),
                                    np.array([11.0, 22.0, 33.0]), calibration)
    # scaled accel before mapping: [1.02, 1.96, 3.03]
    np.testing.assert_allclose(accel, [1.96, -1.02, 3.03], atol=1e-12)
    np.testing.assert_allclose(gyro, [20.0, -10.0, 30.0])


@pytest.mark.parametrize("missing", ["+x", "-z"])
def test_missing_face_rejected(missing):
    means, _, _ = synthetic_faces()
    del means[missing]
    with pytest.raises(ValueError, match="missing faces"):
        fit_six_faces(means, "board-test")


def test_bad_scale_nan_and_face_quality_rejected():
    means, _, _ = synthetic_faces()
    means["+x"] = means["+x"].copy()
    means["+x"][0] = np.nan
    with pytest.raises(ValueError, match="finite"):
        fit_six_faces(means, "board-test")
    means, _, _ = synthetic_faces(scale=[0.4, 1, 1])
    with pytest.raises(ValueError, match="scale"):
        fit_six_faces(means, "board-test")
    means, _, _ = synthetic_faces()
    means["+x"] = {"mean": means["+x"], "variance": [0.5, 0.01, 0.01], "duration_s": 12}
    with pytest.raises(ValueError, match="variance"):
        fit_six_faces(means, "board-test")


@pytest.mark.parametrize("axis_map", [
    [[1, 0, 0], [0, 1, 0], [0, 0, -1]],  # left handed
    [[1, 0.1, 0], [0, 1, 0], [0, 0, 1]],  # non orthogonal
])
def test_invalid_axis_map_rejected(axis_map):
    calibration = fit_six_faces(synthetic_faces()[0], "board-test")
    calibration["axis_map"] = axis_map
    with pytest.raises(ValueError, match="axis_map"):
        apply_calibration(np.zeros(3), np.zeros(3), calibration)


def test_board_mismatch_and_independent_validation():
    calibration = fit_six_faces(synthetic_faces()[0], "board-test")
    with pytest.raises(ValueError, match="board_id"):
        validate_calibration({"calibration": calibration, "faces": synthetic_faces()[0]}, "other")
    result = validate_calibration({"calibration": calibration, "faces": synthetic_faces()[0]}, "board-test")
    assert result["passed"]
    assert result["max_gravity_error_fraction"] < 1e-12


def test_id_is_canonical_and_rejects_nonfinite_parameters():
    calibration = fit_six_faces(synthetic_faces()[0], "board-test")
    reordered = json.loads(json.dumps(calibration, sort_keys=False))
    assert calibration_id(reordered) == calibration["calibration_id"]
    bad = copy.deepcopy(calibration)
    bad["gyro_bias"][0] = float("nan")
    with pytest.raises(ValueError, match="finite"):
        apply_calibration(np.zeros(3), np.zeros(3), bad)
