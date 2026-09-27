import json
from pathlib import Path

import pytest

from wrist_imu.protocol import Decoder, DecodeError, encode_packet


FIXTURE = Path(__file__).parents[2] / "test" / "fixtures" / "protocol-v1.json"


def test_cross_language_fixture():
    fixture = json.loads(FIXTURE.read_text())
    wire = encode_packet(fixture["kind"], fixture["seq"], bytes.fromhex(fixture["payload_hex"]))
    assert wire.hex() == fixture["wire_hex"]
    packet = Decoder().feed(wire)[0]
    assert (packet.kind, packet.seq, packet.payload) == (
        fixture["kind"], fixture["seq"], bytes.fromhex(fixture["payload_hex"])
    )


@pytest.mark.parametrize("payload", [b"", b"a\0b\0c"])
def test_round_trip(payload):
    assert Decoder().feed(encode_packet(9, 0xFFFFFFFF, payload))[0].payload == payload


def test_fragment_and_resync():
    d = Decoder()
    wire = encode_packet(3, 7, b'{"code":"reset"}')
    assert d.feed(b"x" * 2000 + b"\0") == []
    result = []
    for byte in wire:
        result.extend(d.feed(bytes([byte])))
    assert [(p.kind, p.seq, p.payload) for p in result] == [(3, 7, b'{"code":"reset"}')]
    assert d.errors


def test_crc_and_declared_length_are_rejected():
    good = bytearray(encode_packet(1, 2, b"abc"))
    good[-3] ^= 0x55
    d = Decoder()
    assert d.feed(good) == []
    assert d.errors[-1].reason in {"crc", "cobs"}

    # Decoded body with a payload length larger than the actual payload.
    bad_body = b"WI\x01\x01\x04\x00\x02\x00\x00\x00abc"
    from wrist_imu.protocol import cobs_encode, crc32_bytes
    malformed = cobs_encode(bad_body + crc32_bytes(bad_body)) + b"\0"
    assert d.feed(malformed) == []
    assert d.errors[-1].reason == "length"


def test_argument_limits():
    with pytest.raises(ValueError):
        encode_packet(256, 0, b"")
    with pytest.raises(ValueError):
        encode_packet(1, -1, b"")
    with pytest.raises(ValueError):
        encode_packet(1, 0, b"x" * 65536)


def test_truncated_cobs_block_is_rejected():
    d = Decoder()
    assert d.feed(b"\x02\0") == []
    assert d.errors[-1].reason == "cobs"
