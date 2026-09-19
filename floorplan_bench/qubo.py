"""공통 목적함수 → dimod BQM (D-Wave가 받는 형태).

BQM = terms.quality_coeffs (품질 10항) + terms.penalty_coeffs (하드 제약 2항)
CP-SAT는 앞의 절반을 그대로 쓰고, 뒤의 절반은 네이티브 제약으로 대체한다.
"""

from __future__ import annotations

import dimod

from .spec import BuildingSpec
from .terms import penalty_coeffs, quality_coeffs


def build_bqm(spec: BuildingSpec, w) -> dimod.BinaryQuadraticModel:
    ql, qq, qc = quality_coeffs(spec, w)
    pl, pq, pc = penalty_coeffs(spec, w)
    lin = dict(ql)
    for v, c in pl.items():
        lin[v] = lin.get(v, 0.0) + c
    quad = dict(qq)
    for k, c in pq.items():
        quad[k] = quad.get(k, 0.0) + c
    return dimod.BinaryQuadraticModel(lin, quad, qc + pc, dimod.BINARY)


def build_quality_bqm(spec: BuildingSpec, w) -> dimod.BinaryQuadraticModel:
    """하드 제약 없이 품질 항만. 제약을 만족하는 해끼리 비교할 때 쓴다."""
    ql, qq, qc = quality_coeffs(spec, w)
    return dimod.BinaryQuadraticModel(ql, qq, qc, dimod.BINARY)


def bqm_stats(bqm: dimod.BinaryQuadraticModel) -> dict:
    n = bqm.num_variables
    max_edges = n * (n - 1) / 2
    return {
        "variables": n,
        "interactions": bqm.num_interactions,
        "density": bqm.num_interactions / max_edges if max_edges else 0.0,
    }


def sample_to_x(sample: dict) -> dict:
    return {k: int(v) for k, v in sample.items()}


def x_violations(spec: BuildingSpec, x: dict) -> dict:
    per_cell = [0] * spec.n_cells
    per_room = {k: 0 for k in spec.room_keys}
    for (room, cell), v in x.items():
        if v:
            per_cell[cell] += 1
            per_room[room] += 1
    return {
        "empty_cells": sum(1 for n in per_cell if n == 0),
        "overlapped_cells": sum(1 for n in per_cell if n > 1),
        "area_errors": {k: per_room[k] - spec.room_by_key[k].area
                        for k in spec.room_keys
                        if per_room[k] != spec.room_by_key[k].area},
        "total_area_sq_error": sum((per_room[k] - spec.room_by_key[k].area) ** 2
                                   for k in spec.room_keys),
    }
