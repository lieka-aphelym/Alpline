"""A QR code for the phone page, drawn by the launcher itself (no extra library).

A port to Python of the part of "QR Code Generator for JavaScript" by Kazuhiko Arase (MIT licence, see
THIRD_PARTY.md) that the phone link needs: bytes, error correction M, versions 1 to 10 (up to 213 bytes, far more
than an address with its PIN). It follows viewer/vendor/qrcode.js step by step, including its choice of mask, so
the launcher and share.html draw the same code; tests/test_launcher.py compares the two.

    qr_matrix("https://192.168.1.24:8443/viewer/?k=482913")  ->  list of rows of booleans (True = dark)
"""
from __future__ import annotations

# error correction M: per version, (blocks, total, data) groups (from RS_BLOCK_TABLE in qrcode.js)
_RS_M = {1: [(1, 26, 16)], 2: [(1, 44, 28)], 3: [(1, 70, 44)], 4: [(2, 50, 32)], 5: [(2, 67, 43)],
         6: [(4, 43, 27)], 7: [(4, 49, 31)], 8: [(2, 60, 38), (2, 61, 39)], 9: [(3, 58, 36), (2, 59, 37)],
         10: [(4, 69, 43), (1, 70, 44)]}
_ALIGN = {1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34], 7: [6, 22, 38], 8: [6, 24, 42],
          9: [6, 26, 46], 10: [6, 28, 50]}
_LEVEL_M = 0                                      # the level's value in the format bits (L 1, M 0, Q 3, H 2)
_G15 = 0b10100110111
_G18 = 0b1111100100101
_G15_MASK = 0b101010000010010

_EXP = [0] * 256
_LOG = [0] * 256
for _i in range(8):
    _EXP[_i] = 1 << _i
for _i in range(8, 256):
    _EXP[_i] = _EXP[_i - 4] ^ _EXP[_i - 5] ^ _EXP[_i - 6] ^ _EXP[_i - 8]
for _i in range(255):
    _LOG[_EXP[_i]] = _i


def _gexp(n: int) -> int:
    return _EXP[n % 255]


def _poly(num: list[int], shift: int = 0) -> list[int]:
    i = 0
    while i < len(num) and num[i] == 0:
        i += 1
    return num[i:] + [0] * shift


def _mul(a: list[int], b: list[int]) -> list[int]:
    out = [0] * (len(a) + len(b) - 1)
    for i, x in enumerate(a):
        for j, y in enumerate(b):
            if x and y:
                out[i + j] ^= _gexp(_LOG[x] + _LOG[y])
    return _poly(out)


def _mod(a: list[int], e: list[int]) -> list[int]:
    while len(a) - len(e) >= 0:
        ratio = _LOG[a[0]] - _LOG[e[0]]
        a = list(a)
        for i, y in enumerate(e):
            a[i] ^= _gexp(_LOG[y] + ratio)
        a = _poly(a)
        if not a:
            break
    return a


def _bch_digit(d: int) -> int:
    return d.bit_length()


def _bch_type_info(data: int) -> int:
    d = data << 10
    while _bch_digit(d) - _bch_digit(_G15) >= 0:
        d ^= _G15 << (_bch_digit(d) - _bch_digit(_G15))
    return ((data << 10) | d) ^ _G15_MASK


def _bch_type_number(data: int) -> int:
    d = data << 12
    while _bch_digit(d) - _bch_digit(_G18) >= 0:
        d ^= _G18 << (_bch_digit(d) - _bch_digit(_G18))
    return (data << 12) | d


_MASKS = (lambda i, j: (i + j) % 2 == 0, lambda i, j: i % 2 == 0, lambda i, j: j % 3 == 0,
          lambda i, j: (i + j) % 3 == 0, lambda i, j: (i // 2 + j // 3) % 2 == 0,
          lambda i, j: (i * j) % 2 + (i * j) % 3 == 0, lambda i, j: ((i * j) % 2 + (i * j) % 3) % 2 == 0,
          lambda i, j: ((i * j) % 3 + (i + j) % 2) % 2 == 0)


def _blocks(version: int) -> list[tuple[int, int]]:
    return [(total, data) for n, total, data in _RS_M[version] for _ in range(n)]


def _codewords(data: bytes, version: int) -> list[int]:
    bits: list[int] = []

    def put(num: int, length: int):
        bits.extend((num >> (length - 1 - i)) & 1 for i in range(length))
    put(4, 4)                                     # byte mode
    put(len(data), 8 if version < 10 else 16)
    for b in data:
        put(b, 8)
    blocks = _blocks(version)
    total_data = sum(d for _, d in blocks)
    if len(bits) > total_data * 8:
        raise ValueError(f"too long for a QR code here ({len(data)} bytes)")
    if len(bits) + 4 <= total_data * 8:
        put(0, 4)
    while len(bits) % 8:
        bits.append(0)
    pad = (0xEC, 0x11)
    k = 0
    while len(bits) < total_data * 8:
        put(pad[k % 2], 8)
        k += 1
    buf = [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]
    dc, ec, off = [], [], 0
    for total, dcount in blocks:
        d = buf[off:off + dcount]
        off += dcount
        ecount = total - dcount
        gen = [1]
        for i in range(ecount):
            gen = _mul(gen, [1, _gexp(i)])
        m = _mod(_poly(d, len(gen) - 1), gen)
        e = [0] * ecount
        for i in range(ecount):
            idx = i + len(m) - ecount
            e[i] = m[idx] if idx >= 0 else 0
        dc.append(d)
        ec.append(e)
    out = []
    for i in range(max(len(d) for d in dc)):
        out += [d[i] for d in dc if i < len(d)]
    for i in range(max(len(e) for e in ec)):
        out += [e[i] for e in ec if i < len(e)]
    return out


def _build(version: int, words: list[int], mask: int, test: bool) -> list[list]:
    n = version * 4 + 17
    m: list[list] = [[None] * n for _ in range(n)]

    def probe(row, col):
        for r in range(-1, 8):
            if not 0 <= row + r < n:
                continue
            for c in range(-1, 8):
                if not 0 <= col + c < n:
                    continue
                m[row + r][col + c] = ((0 <= r <= 6 and c in (0, 6)) or (0 <= c <= 6 and r in (0, 6))
                                       or (2 <= r <= 4 and 2 <= c <= 4))
    probe(0, 0); probe(n - 7, 0); probe(0, n - 7)
    pos = _ALIGN[version]
    for row in pos:
        for col in pos:
            if m[row][col] is not None:
                continue
            for r in range(-2, 3):
                for c in range(-2, 3):
                    m[row + r][col + c] = r in (-2, 2) or c in (-2, 2) or (r == 0 and c == 0)
    for r in range(8, n - 8):
        if m[r][6] is None:
            m[r][6] = r % 2 == 0
    for c in range(8, n - 8):
        if m[6][c] is None:
            m[6][c] = c % 2 == 0
    bits = _bch_type_info((_LEVEL_M << 3) | mask)
    for i in range(15):
        on = not test and (bits >> i) & 1 == 1
        m[i if i < 6 else (i + 1 if i < 8 else n - 15 + i)][8] = on
        m[8][n - i - 1 if i < 8 else (15 - i if i < 9 else 15 - i - 1)] = on
    m[n - 8][8] = not test
    if version >= 7:
        bits = _bch_type_number(version)
        for i in range(18):
            on = not test and (bits >> i) & 1 == 1
            m[i // 3][i % 3 + n - 11] = on
            m[i % 3 + n - 11][i // 3] = on
    f = _MASKS[mask]
    inc, row, bit, byte = -1, n - 1, 7, 0
    col = n - 1
    while col > 0:
        if col == 6:
            col -= 1
        while True:
            for c in range(2):
                if m[row][col - c] is None:
                    dark = byte < len(words) and (words[byte] >> bit) & 1 == 1
                    m[row][col - c] = dark != f(row, col - c)
                    bit -= 1
                    if bit == -1:
                        byte, bit = byte + 1, 7
            row += inc
            if row < 0 or row >= n:
                row -= inc
                inc = -inc
                break
        col -= 2
    return m


def _lost_point(m: list[list]) -> float:
    n = len(m)
    lost = 0.0
    for row in range(n):
        for col in range(n):
            same, dark = 0, m[row][col]
            for r in (-1, 0, 1):
                if not 0 <= row + r < n:
                    continue
                for c in (-1, 0, 1):
                    if (r or c) and 0 <= col + c < n and m[row + r][col + c] == dark:
                        same += 1
            if same > 5:
                lost += 3 + same - 5
    for row in range(n - 1):
        for col in range(n - 1):
            k = m[row][col] + m[row + 1][col] + m[row][col + 1] + m[row + 1][col + 1]
            if k in (0, 4):
                lost += 3
    pat = (True, False, True, True, True, False, True)
    for row in range(n):
        for col in range(n - 6):
            if tuple(m[row][col:col + 7]) == pat:
                lost += 40
    for col in range(n):
        for row in range(n - 6):
            if tuple(m[row + i][col] for i in range(7)) == pat:
                lost += 40
    dark = sum(sum(r) for r in m)
    return lost + abs(100 * dark / n / n - 50) / 5 * 10


def qr_matrix(text: str) -> list[list[bool]]:
    """The QR code of text (the smallest version that fits, mask chosen as qrcode.js does)."""
    data = text.encode("utf-8")
    for version in range(1, 11):
        if 4 + (8 if version < 10 else 16) + 8 * len(data) <= 8 * sum(d for _, d in _blocks(version)):
            break
    else:
        raise ValueError(f"too long for a QR code here ({len(data)} bytes)")
    words = _codewords(data, version)
    best, best_lost = 0, None
    for mask in range(8):
        lost = _lost_point(_build(version, words, mask, True))
        if best_lost is None or lost < best_lost:
            best, best_lost = mask, lost
    return [[bool(x) for x in row] for row in _build(version, words, best, False)]
