"""웹 엔진(node·브라우저의 V8)과 끝자리까지 같은 수학 함수.

파이썬 math.log·log2·hypot은 C 라이브러리를 쓰고, V8의 Math.log·log2는 fdlibm 이식,
Math.hypot은 최댓값으로 나눈 카한 합이다. 대개 같지만 마지막 비트(1ulp)가 다를 때가 있어,
값이 몇 개뿐인 분포(정답지의 경험적 누적분포)에서 같은 값/다른 값 판정이 갈릴 수 있다.
그래서 정답지·특징 계산에 들어가는 곳은 이 함수를 쓴다. (tests/test_engine_parity.py가 node와 비교)

    fdlibm: Copyright (C) 1993 by Sun Microsystems, Inc. All rights reserved.
    Developed at SunPro, a Sun Microsystems, Inc. business. Permission to use, copy, modify,
    and distribute this software is freely granted, provided that this notice is preserved.
"""

from __future__ import annotations

import math
import struct

_D = struct.Struct("<d")
_Q = struct.Struct("<Q")


def _words(x: float) -> tuple[int, int]:
    """double → (부호 있는 상위 32비트, 하위 32비트)."""
    b = _Q.unpack(_D.pack(x))[0]
    hx = b >> 32
    return (hx - (1 << 32) if hx >= 0x80000000 else hx), b & 0xFFFFFFFF


def _from_words(hx: int, lx: int) -> float:
    return _D.unpack(_Q.pack(((hx & 0xFFFFFFFF) << 32) | (lx & 0xFFFFFFFF)))[0]


_LG1 = 6.666666666666735130e-01   # 3FE55555 55555593
_LG2 = 3.999999999940941908e-01   # 3FD99999 9997FA04
_LG3 = 2.857142874366239149e-01   # 3FD24924 94229359
_LG4 = 2.222219843214978396e-01   # 3FCC71C5 1D8E78AF
_LG5 = 1.818357216161805012e-01   # 3FC74664 96CB03DE
_LG6 = 1.531383769920937332e-01   # 3FC39A09 D078C69F
_LG7 = 1.479819860511658591e-01   # 3FC2F112 DF3E5244
_TWO54 = 1.80143985094819840000e+16
_LN2_HI = 6.93147180369123816490e-01
_LN2_LO = 1.90821492927058770002e-10
_IVLN2HI = 1.44269504072144627571e+00
_IVLN2LO = 1.67517131648865118353e-10


def _reduce(x: float):
    """공통 앞부분 — x = 2^k · (1+f), √2/2 < 1+f < √2. 특수값이면 (값, None)."""
    hx, lx = _words(x)
    k = 0
    if hx < 0x00100000:                       # x < 2**-1022
        if ((hx & 0x7FFFFFFF) | lx) == 0:
            return -math.inf, None            # log(±0) = -inf
        if hx < 0:
            return math.nan, None             # log(음수) = NaN
        k -= 54
        x *= _TWO54                           # 비정규 수는 키운다
        hx, lx = _words(x)
    if hx >= 0x7FF00000:
        return x + x, None
    k += (hx >> 20) - 1023
    hx &= 0x000FFFFF
    i = (hx + 0x95F64) & 0x100000
    x = _from_words(hx | (i ^ 0x3FF00000), lx)   # x 또는 x/2로 정규화
    k += i >> 20
    return (x, k, hx), True


def log(x: float) -> float:
    """V8 Math.log (fdlibm e_log.c)."""
    r, ok = _reduce(x)
    if ok is None:
        return r
    x, k, hx = r
    f = x - 1.0
    if (0x000FFFFF & (2 + hx)) < 3:          # -2**-20 <= f < 2**-20
        if f == 0.0:
            if k == 0:
                return 0.0
            dk = float(k)
            return dk * _LN2_HI + dk * _LN2_LO
        R = f * f * (0.5 - 0.33333333333333333 * f)
        if k == 0:
            return f - R
        dk = float(k)
        return dk * _LN2_HI - ((R - dk * _LN2_LO) - f)
    s = f / (2.0 + f)
    dk = float(k)
    z = s * s
    i = hx - 0x6147A
    w = z * z
    j = 0x6B851 - hx
    t1 = w * (_LG2 + w * (_LG4 + w * _LG6))
    t2 = z * (_LG1 + w * (_LG3 + w * (_LG5 + w * _LG7)))
    i |= j
    R = t2 + t1
    if i > 0:
        hfsq = 0.5 * f * f
        if k == 0:
            return f - (hfsq - s * (hfsq + R))
        return dk * _LN2_HI - ((hfsq - (s * (hfsq + R) + dk * _LN2_LO)) - f)
    if k == 0:
        return f - s * (f - R)
    return dk * _LN2_HI - ((s * (f - R) - dk * _LN2_LO) - f)


def _k_log1p(f: float) -> float:
    s = f / (2.0 + f)
    z = s * s
    w = z * z
    t1 = w * (_LG2 + w * (_LG4 + w * _LG6))
    t2 = z * (_LG1 + w * (_LG3 + w * (_LG5 + w * _LG7)))
    R = t2 + t1
    hfsq = 0.5 * f * f
    return s * (hfsq + R)


def log2(x: float) -> float:
    """V8 Math.log2 (FreeBSD e_log2.c)."""
    if x == 1.0:
        return 0.0
    r, ok = _reduce(x)
    if ok is None:
        return r
    x, k, _ = r
    y = float(k)
    f = x - 1.0
    hfsq = 0.5 * f * f
    r = _k_log1p(f)
    hi = f - hfsq
    hi = _from_words(_words(hi)[0], 0)        # 하위 비트를 지워 정확한 hi + lo로
    lo = (f - hi) - hfsq + r
    val_hi = hi * _IVLN2HI
    val_lo = (lo + hi) * _IVLN2LO + lo * _IVLN2HI
    w = y + val_hi
    val_lo += (y - w) + val_hi
    return val_lo + w


def hypot(x: float, y: float) -> float:
    """V8 Math.hypot(x, y) — 최댓값으로 나눠 카한 합 후 √ × 최댓값."""
    if x != x or y != y:
        return math.inf if math.inf in (abs(x), abs(y)) else math.nan
    ax, ay = abs(x), abs(y)
    m = ax if ax > ay else ay
    if m == math.inf:
        return math.inf
    if m == 0:
        return 0.0
    a, b = ax / m, ay / m
    return math.sqrt(a * a + b * b) * m        # 두 항이면 카한 보정값은 0으로 남는다
