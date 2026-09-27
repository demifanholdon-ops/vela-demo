"""WI v1 串口协议：小端头、CRC-32、COBS 与零分隔。"""

from __future__ import annotations

from dataclasses import dataclass
from collections import deque
import struct
import zlib


MAGIC = b"WI"
VERSION = 1
HEADER = struct.Struct("<2sBBHI")
CRC = struct.Struct("<I")
MAX_PAYLOAD = 1024
MAX_ENCODED = 1100


@dataclass(frozen=True)
class Packet:
    kind: int
    seq: int
    payload: bytes


@dataclass(frozen=True)
class DecodeError:
    reason: str
    encoded_size: int


def crc32_bytes(data: bytes) -> bytes:
    return CRC.pack(zlib.crc32(data) & 0xFFFFFFFF)


def cobs_encode(data: bytes) -> bytes:
    out = bytearray(b"\x00")
    code_at = 0
    code = 1
    for value in data:
        if value == 0:
            out[code_at] = code
            code_at = len(out)
            out.append(0)
            code = 1
        else:
            out.append(value)
            code += 1
            if code == 0xFF:
                out[code_at] = code
                code_at = len(out)
                out.append(0)
                code = 1
    out[code_at] = code
    return bytes(out)


def cobs_decode(data: bytes) -> bytes:
    if not data:
        raise ValueError("empty COBS frame")
    out = bytearray()
    offset = 0
    while offset < len(data):
        code = data[offset]
        if code == 0 or offset + code > len(data):
            raise ValueError("invalid COBS code")
        offset += 1
        end = offset + code - 1
        out.extend(data[offset:end])
        offset = end
        if code != 0xFF and offset < len(data):
            out.append(0)
    return bytes(out)


def encode_packet(kind: int, seq: int, payload: bytes) -> bytes:
    payload = bytes(payload)
    if not 0 <= kind <= 0xFF:
        raise ValueError("kind must fit uint8")
    if not 0 <= seq <= 0xFFFFFFFF:
        raise ValueError("seq must fit uint32")
    if len(payload) > MAX_PAYLOAD:
        raise ValueError("payload exceeds protocol limit")
    body = HEADER.pack(MAGIC, VERSION, kind, len(payload), seq) + payload
    return cobs_encode(body + crc32_bytes(body)) + b"\0"


class Decoder:
    """可接受任意分片；错误帧在下一个零分隔符处重新同步。"""

    def __init__(self) -> None:
        self._encoded = bytearray()
        self._discarding = False
        # 长时间噪声链路不能让诊断信息无限占用内存。
        self.errors: deque[DecodeError] = deque(maxlen=256)

    def _error(self, reason: str, size: int) -> None:
        self.errors.append(DecodeError(reason, size))

    def feed(self, chunk: bytes) -> list[Packet]:
        packets: list[Packet] = []
        for value in bytes(chunk):
            if value != 0:
                if not self._discarding:
                    self._encoded.append(value)
                    if len(self._encoded) > MAX_ENCODED:
                        self._error("oversize", len(self._encoded))
                        self._encoded.clear()
                        self._discarding = True
                continue
            if self._discarding:
                self._discarding = False
                continue
            if not self._encoded:
                continue
            encoded = bytes(self._encoded)
            self._encoded.clear()
            try:
                decoded = cobs_decode(encoded)
            except ValueError:
                self._error("cobs", len(encoded))
                continue
            if len(decoded) < HEADER.size + CRC.size:
                self._error("short", len(encoded))
                continue
            body, received_crc = decoded[:-CRC.size], decoded[-CRC.size:]
            if crc32_bytes(body) != received_crc:
                self._error("crc", len(encoded))
                continue
            magic, version, kind, size, seq = HEADER.unpack_from(body)
            if magic != MAGIC or version != VERSION:
                self._error("header", len(encoded))
                continue
            payload = body[HEADER.size:]
            if size != len(payload) or size > MAX_PAYLOAD:
                self._error("length", len(encoded))
                continue
            packets.append(Packet(kind, seq, payload))
        return packets

    def finish(self) -> None:
        """在输入结束时报告未被零分隔符终止的尾包。"""
        if self._encoded or self._discarding:
            self._error("truncated", len(self._encoded))
            self._encoded.clear()
            self._discarding = False
