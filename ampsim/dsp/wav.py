"""Leitor mínimo de WAV (PCM 16/24/32 bits e float 32/64) para impulsos de gabinete."""
import struct

import numpy as np


def read_wav(path):
    """Retorna (amostras float64 [n, canais], taxa de amostragem)."""
    with open(path, "rb") as f:
        data = f.read()
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError("Arquivo não é WAV/RIFF")
    pos = 12
    fmt = None
    payload = None
    while pos + 8 <= len(data):
        cid = data[pos:pos + 4]
        size = struct.unpack("<I", data[pos + 4:pos + 8])[0]
        body = data[pos + 8:pos + 8 + size]
        if cid == b"fmt ":
            tag, ch, rate, _, _, bits = struct.unpack("<HHIIHH", body[:16])
            if tag == 0xFFFE and len(body) >= 26:          # WAVE_FORMAT_EXTENSIBLE
                tag = struct.unpack("<H", body[24:26])[0]
            fmt = (tag, ch, rate, bits)
        elif cid == b"data":
            payload = body
        pos += 8 + size + (size & 1)
    if fmt is None or payload is None:
        raise ValueError("WAV sem blocos fmt/data")
    tag, ch, rate, bits = fmt
    if tag == 3 and bits == 32:
        x = np.frombuffer(payload, "<f4").astype(np.float64)
    elif tag == 3 and bits == 64:
        x = np.frombuffer(payload, "<f8").copy()
    elif tag == 1 and bits == 16:
        x = np.frombuffer(payload, "<i2") / 32768.0
    elif tag == 1 and bits == 32:
        x = np.frombuffer(payload, "<i4") / 2147483648.0
    elif tag == 1 and bits == 24:
        b = np.frombuffer(payload[: len(payload) // 3 * 3], np.uint8).reshape(-1, 3).astype(np.int32)
        v = b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)
        v = np.where(v >= 1 << 23, v - (1 << 24), v)
        x = v / 8388608.0
    else:
        raise ValueError(f"Formato WAV não suportado (tag={tag}, bits={bits})")
    x = x[: len(x) // ch * ch].reshape(-1, ch)
    return x.astype(np.float64), rate
