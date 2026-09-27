# 硬件输入与复现

## 附件范围

来自团队提供的 `hw.7z` 与 `report-0e27827d.json`。压缩包实际包含一段六面校准会话、Python 上位机源码及测试。没有 MCU 固件源码、Anker SDK、真实音频、佩戴者睡眠数据或双相障碍标签。

样本为 BMI323 六轴 raw int16，100 Hz，±4g，±500 dps。`samples.csv` 共 92,048 行，其中表头一行，数据 92,047 条。`host_ns` 是主机接收时间，`sample_est_us` 是设备估计采样时间，两者不可互换。

`raw.bin`、CSV、事件及 metadata 保留原字节，`inputs/HARDWARE-SHA256.json` 包含数据与上位机文件哈希。`report-0e27827d.json` 的 `session` 原机器路径改为仓库相对路径；校准参数、板卡匹配标识和 calibration_id 均保持不变。

## 不安装依赖的工程重放

在仓库根目录运行：

```bash
python3 scripts/replay.py --output runtime/replay.json
```

此路径用于前后端统一读取：验证 board_id、参数哈希与单位，转换原始样本，按 connection/segment 分组检查时钟和质量，重算六面均值与重力误差，形成证据窗口。窗口门槛为工程质量规则，不是医疗阈值。

## 硬件同学原始拟合脚本

Python 3.10+，推荐 3.12。在专门的虚拟环境中运行：

```bash
python3 -m venv .venv-hardware
.venv-hardware/bin/python -m pip install -e './inputs/hw/host[test]'
.venv-hardware/bin/python -m pytest inputs/hw/host/tests -q
.venv-hardware/bin/python -m wrist_imu.cli calibrate --session inputs/hw/data/20260926T141442.230441Z-0e27827d --output runtime/refit-calibration.json
```

运行前创建 `runtime` 目录（`mkdir -p runtime`）；Windows 替换虚拟环境解释器路径。不要将输出覆盖到原校准附件。

核心文件：`calibration.py`（拟合与应用）、`session_calibration.py`（会话提取）、`capture_daemon.py`（采集）、`push_calibration.py`（下发）、`protocol.py`（协议与解码）。

`probe_state.py` / `prove_calibration.py` 和下发工具会访问串口，只有实体板卡连接且明确选择目标设备时才运行。本次无板卡验收不执行这些工具。`tests/cross_language_check.py` 仅核对脚本注释中的 C++ 期望值，不编译或执行 C++ 固件。

## 校准边界

原报告验证通过，最大重力误差约 0.53%，限值 2%。这是校准集回代检查，不是独立验证集精度，更不是行为、睡眠或疾病识别准确率。活动和声音尚无真实配对数据；目前不声称完成双路同步、场景识别或情绪分类。

## 修复附件缺少的测试样例

原压缩包缺少 `test/fixtures/protocol-v1.json`，导致一个协议测试无法运行。发布版使用 `scripts/recover_protocol_fixture.py` 独立解码 `raw.bin`，校验长度与 CRC 后，取实际记录的第一个有效数据帧恢复测试样例。JSON 内标注原始文件哈希、字节偏移及来源；不把它声称为原始丢失样例或新的 C++ 固件验证。原硬件源码与 23 个原始文件保持不变。
