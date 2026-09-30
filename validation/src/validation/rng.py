"""Rust's `rand::rngs::StdRng` (rand 0.9: ChaCha12) and the samplers used here.

The offline eviction instances and the footprint Monte Carlo were written
against rand 0.9; reproducing its streams bit for bit keeps the paper's
tables unchanged. `StdRng.seed_from_u64` is rand_core's PCG32 seed
expansion, the key stream is ChaCha with 12 rounds, a 64-bit block counter
and stream id 0, and the samplers are rand 0.9's `random::<f64>()` and
`random_range` on inclusive ranges (Canon's biased method for integers,
`[1, 2) - 1` scaling for floats).
"""

from __future__ import annotations

import struct

import numpy as np

M32 = 0xFFFF_FFFF
M64 = 0xFFFF_FFFF_FFFF_FFFF
_CONST = (0x61707865, 0x3320646E, 0x79622D32, 0x6B206574)
_CHUNK_BLOCKS = 256  # blocks generated per refill (the stream is the same for any value)


def _pcg32(state: int) -> tuple[int, bytes]:
    state = (state * 6364136223846793005 + 11634580027462260723) & M64
    xorshifted = (((state >> 18) ^ state) >> 27) & M32
    rot = state >> 59
    x = ((xorshifted >> rot) | (xorshifted << ((-rot) & 31))) & M32
    return state, x.to_bytes(4, "little")


def _rotl(x: np.ndarray, n: int) -> np.ndarray:
    return (x << np.uint32(n)) | (x >> np.uint32(32 - n))


def _chacha_blocks(key: tuple[int, ...], counter: int, blocks: int, rounds: int) -> np.ndarray:
    """Key stream words of `blocks` consecutive blocks from `counter`."""
    ctr = np.arange(counter, counter + blocks, dtype=np.uint64)
    init = [np.full(blocks, c, dtype=np.uint32) for c in _CONST]
    init += [np.full(blocks, k, dtype=np.uint32) for k in key]
    init += [
        (ctr & np.uint64(M32)).astype(np.uint32),
        (ctr >> np.uint64(32)).astype(np.uint32),
        np.zeros(blocks, dtype=np.uint32),
        np.zeros(blocks, dtype=np.uint32),
    ]
    x = [a.copy() for a in init]

    def qr(a: int, b: int, c: int, d: int) -> None:
        x[a] += x[b]
        x[d] = _rotl(x[d] ^ x[a], 16)
        x[c] += x[d]
        x[b] = _rotl(x[b] ^ x[c], 12)
        x[a] += x[b]
        x[d] = _rotl(x[d] ^ x[a], 8)
        x[c] += x[d]
        x[b] = _rotl(x[b] ^ x[c], 7)

    for _ in range(rounds // 2):
        qr(0, 4, 8, 12)
        qr(1, 5, 9, 13)
        qr(2, 6, 10, 14)
        qr(3, 7, 11, 15)
        qr(0, 5, 10, 15)
        qr(1, 6, 11, 12)
        qr(2, 7, 8, 13)
        qr(3, 4, 9, 14)
    out = np.stack([x[i] + init[i] for i in range(16)], axis=1)  # (blocks, 16)
    return out.reshape(-1)


class StdRng:
    """rand 0.9 `StdRng`: a continuous stream of ChaCha12 key-stream words."""

    def __init__(self, seed: bytes):
        assert len(seed) == 32
        self._key = struct.unpack("<8I", seed)
        self._counter = 0
        self._words: list[int] = []
        self._pos = 0

    @classmethod
    def seed_from_u64(cls, state: int) -> StdRng:
        state &= M64
        seed = b""
        for _ in range(8):
            state, chunk = _pcg32(state)
            seed += chunk
        return cls(seed)

    def _refill(self) -> None:
        rest = self._words[self._pos :]
        new = _chacha_blocks(self._key, self._counter, _CHUNK_BLOCKS, 12)
        self._counter += _CHUNK_BLOCKS
        self._words = rest + new.tolist()
        self._pos = 0

    def next_u32(self) -> int:
        if self._pos >= len(self._words):
            self._refill()
        w = self._words[self._pos]
        self._pos += 1
        return w

    def next_u64(self) -> int:
        if self._pos + 1 >= len(self._words):
            self._refill()
        lo, hi = self._words[self._pos], self._words[self._pos + 1]
        self._pos += 2
        return (hi << 32) | lo

    # --- rand 0.9 samplers -------------------------------------------------

    def random_f64(self) -> float:
        """`rng.random::<f64>()`: 53 random bits in [0, 1)."""
        return (self.next_u64() >> 11) * (1.0 / (1 << 53))

    def _canon(self, low: int, high: int, bits: int) -> int:
        mask = (1 << bits) - 1
        draw = self.next_u64 if bits == 64 else self.next_u32
        rng = (high - low + 1) & mask
        if rng == 0:
            return draw()
        prod = draw() * rng
        result, lo_order = prod >> bits, prod & mask
        if lo_order > ((-rng) & mask):
            new_hi = (draw() * rng) >> bits
            result += 1 if lo_order + new_hi > mask else 0
        return low + result

    def range_u64(self, low: int, high: int) -> int:
        """`rng.random_range(low..=high)` for `u64`."""
        return self._canon(low, high, 64)

    def range_u32(self, low: int, high: int) -> int:
        """`random_range(low..=high)` for `u32`, `i32` and (below 2^32) `usize`."""
        return self._canon(low, high, 32)

    def range_f64(self, low: float, high: float) -> float:
        """`rng.random_range(low..=high)` for `f64`."""
        scale = high - low
        bits = (self.next_u64() >> 12) | (1023 << 52)
        value1_2 = struct.unpack("<d", struct.pack("<Q", bits))[0]
        return (value1_2 - 1.0) * scale + low
