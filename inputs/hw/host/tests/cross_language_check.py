"""跨语言一致性: Python apply_calibration vs C++ 测试期望值（同一输入）。"""
import numpy as np
from wrist_imu.calibration import fit_six_faces, apply_calibration, calibration_id

G = 9.80665
bias = np.array([0.2, -0.3, 0.4]); scale = np.array([1.02, 0.98, 1.01])
means = {}
for i, axis in enumerate("xyz"):
    for sign, label in ((1, "+"), (-1, "-")):
        v = np.zeros(3); v[i] = sign * G
        means[label + axis] = v / scale + bias
cal = fit_six_faces(means, "board-test")
cal["gyro_bias"] = [1.0, 2.0, 3.0]
cal["axis_map"] = [[0, 1, 0], [-1, 0, 0], [0, 0, 1]]

a, g = apply_calibration(np.array([1.2, 1.7, 3.4]), np.array([11.0, 22.0, 33.0]), cal)
print("python accel:", np.round(a, 4).tolist())
print("python gyro :", np.round(g, 4).tolist())
# C++ 测试期望（test/calibration_test.cpp 硬编码）:
# accel [1.96, -1.02, 3.03], gyro [20, -10, 30]
assert np.allclose(a, [1.96, -1.02, 3.03], atol=1e-4), a
assert np.allclose(g, [20.0, -10.0, 30.0], atol=1e-4), g
print("CROSS-LANGUAGE CONSISTENT")
