"""목적 함수의 단일 출처(single source of truth).

세 곳이 같은 함수를 써야 비교가 성립한다.
  · D-Wave  : quality_coeffs() + penalty_coeffs() → QUBO
  · CP-SAT  : quality_coeffs() + 네이티브 제약
  · 검증    : raw_values() — 도면을 직접 순회하는 독립 구현

raw_values()는 계수를 전혀 쓰지 않고 도면을 훑어 지표를 세므로,
QUBO 에너지와 raw_values 기반 점수가 일치하면 세 경로가 같은 함수를 푼 것이다.

부호 규약: 에너지는 낮을수록 좋다.
  보상(reward) 항 → 에너지에서 뺀다 (sign = -1)
  벌점(penalty) 항 → 에너지에 더한다 (sign = +1)
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

from .spec import BuildingSpec


@dataclass(frozen=True)
class TermMeta:
    key: str
    label: str
    sign: int  # -1 보상 / +1 벌점
    form: str  # "1차" | "2차" | "하드"
    weight_field: str
    question: str  # 이 항이 답하는 설계 질문
    normalizer: str


TERM_META: list[TermMeta] = [
    TermMeta("cell_violation", "셀 배타성 위반", +1, "하드", "p_cell",
             "한 셀을 정확히 한 방이 차지하는가?", "위반 셀 수 (Σ(nc−1)²)"),
    TermMeta("area_error", "면적 오차", +1, "하드", "p_area",
             "각 방이 요구 면적을 지키는가?", "제곱 오차 합 Σ(|r|−a_r)²"),
    TermMeta("adjacency", "인접 선호 충족", -1, "2차", "w_adjacency",
             "붙어야 할 방은 붙고, 떨어져야 할 방은 떨어졌는가?", "격자 변 수"),
    TermMeta("compactness", "방 응집도", -1, "2차", "w_compactness",
             "같은 방의 셀이 뭉쳐 있는가?", "격자 변 수"),
    TermMeta("corridor", "동선 코어 접면", -1, "2차", "w_corridor",
             "각 방이 복도에 직접 면하는가?", "격자 변 수"),
    TermMeta("noise", "소음 인접", +1, "2차", "w_noise",
             "시끄러운 방이 조용해야 할 방과 벽을 맞대는가?", "격자 변 수"),
    TermMeta("daylight", "채광 확보", -1, "1차", "w_daylight",
             "창이 필요한 방이 외벽에 면하는가?", "채광 요구 실 수"),
    TermMeta("solar", "남향 확보", -1, "1차", "w_solar",
             "채광 실이 남측 외벽에 면하는가?", "채광 요구 실 수"),
    TermMeta("privacy", "프라이버시", -1, "1차", "w_privacy",
             "사적인 방이 현관에서 충분히 먼가?", "Σ 사적도"),
    TermMeta("circulation", "공용 접근성", -1, "1차", "w_circulation",
             "공용 공간이 현관에서 가까운가?", "Σ 공용도"),
    TermMeta("plumbing", "설비 코어 집중", -1, "1차", "w_plumbing",
             "급배수 실이 배관 코어에 가까운가?", "급배수 실 수"),
    TermMeta("thermal", "외피 노출", +1, "1차", "w_thermal",
             "창이 필요 없는 방이 외벽을 낭비하는가?", "비채광 실 수"),
]

QUALITY_KEYS = [t.key for t in TERM_META if t.form != "하드"]
HARD_KEYS = [t.key for t in TERM_META if t.form == "하드"]
LABELS = {t.key: t.label for t in TERM_META}
META_BY_KEY = {t.key: t for t in TERM_META}


def normalizers(spec: BuildingSpec) -> dict[str, float]:
    """각 항을 대략 [0, 1] 범위로 옮기는 나눗수. 스펙만으로 결정된다."""
    n_edges = float(len(spec.neighbor_pairs)) or 1.0
    n_window = float(sum(1 for r in spec.rooms if r.needs_window)) or 1.0
    n_nonwindow = float(sum(1 for r in spec.rooms if not r.needs_window)) or 1.0
    n_wet = float(sum(1 for r in spec.rooms if r.wet)) or 1.0
    return {
        # 2차 항은 모두 같은 '격자 변' 위에서 겨루므로 분모가 반드시 같아야 한다.
        "adjacency": n_edges, "compactness": n_edges,
        "corridor": n_edges, "noise": n_edges,
        "daylight": n_window, "solar": n_window,
        "privacy": sum(r.privacy for r in spec.rooms) or 1.0,
        "circulation": sum(r.public for r in spec.rooms) or 1.0,
        "plumbing": n_wet, "thermal": n_nonwindow,
    }


# ────────────────────────────────────────── 계수 생성 (QUBO / CP-SAT 공용)
def quality_coeffs(spec: BuildingSpec, w) -> tuple[dict, dict, float]:
    """품질 10개 항을 (1차계수, 2차계수, 상수)로. 이미 부호·가중치가 적용된 에너지 기여분."""
    nrm = normalizers(spec)
    lin: dict[tuple[str, int], float] = {}
    quad: dict[tuple, float] = {}

    def L(v, c):
        if c:
            lin[v] = lin.get(v, 0.0) + c

    def Q(u, v, c):
        if c:
            k = (u, v) if u <= v else (v, u)
            quad[k] = quad.get(k, 0.0) + c

    g = lambda key: getattr(w, META_BY_KEY[key].weight_field) / nrm[key]

    # ── 2차 항 ──────────────────────────────────────────────
    k_adj = g("adjacency")
    for r, s, a_rs in spec.adjacency_pairs():
        for c, d in spec.neighbor_pairs:
            Q((r, c), (s, d), -k_adj * a_rs)
            Q((s, c), (r, d), -k_adj * a_rs)

    k_comp = g("compactness")
    for r in spec.room_keys:
        for c, d in spec.neighbor_pairs:
            Q((r, c), (r, d), -k_comp)

    k_cor = g("corridor")
    core = spec.core_room
    if core in spec.room_by_key:
        for r in spec.room_keys:
            if r == core:
                continue
            for c, d in spec.neighbor_pairs:
                Q((core, c), (r, d), -k_cor)
                Q((r, c), (core, d), -k_cor)

    k_noise = g("noise")
    for r, s in combinations(spec.room_keys, 2):
        rr, ss = spec.room_by_key[r], spec.room_by_key[s]
        m = rr.noise * ss.quiet + ss.noise * rr.quiet
        if not m:
            continue
        for c, d in spec.neighbor_pairs:
            Q((r, c), (s, d), k_noise * m)
            Q((s, c), (r, d), k_noise * m)

    # ── 1차 항 ──────────────────────────────────────────────
    k_light, k_solar = g("daylight"), g("solar")
    k_priv, k_circ = g("privacy"), g("circulation")
    k_plumb, k_therm = g("plumbing"), g("thermal")
    for room in spec.rooms:
        a = room.area
        for c in spec.cells:
            v = 0.0
            if room.needs_window:
                if spec.is_perimeter(c):
                    v -= k_light / a
                if spec.is_south(c):
                    v -= k_solar / a
            else:
                if spec.is_perimeter(c):
                    v += k_therm / a
            v -= k_priv * room.privacy * spec.entrance_dist(c) / a
            v -= k_circ * room.public * (1.0 - spec.entrance_dist(c)) / a
            if room.wet:
                v -= k_plumb * (1.0 - spec.core_dist(c)) / a
            L((room.key, c), v)

    return lin, quad, 0.0


def penalty_coeffs(spec: BuildingSpec, w) -> tuple[dict, dict, float]:
    """하드 제약을 QUBO 페널티로. CP-SAT는 이 대신 네이티브 제약을 쓴다."""
    lin: dict[tuple[str, int], float] = {}
    quad: dict[tuple, float] = {}
    const = 0.0

    def L(v, c):
        lin[v] = lin.get(v, 0.0) + c

    def Q(u, v, c):
        k = (u, v) if u <= v else (v, u)
        quad[k] = quad.get(k, 0.0) + c

    # p_cell · Σ_c (Σ_r x_rc − 1)²
    for c in spec.cells:
        for r in spec.room_keys:
            L((r, c), -w.p_cell)
        for r, s in combinations(spec.room_keys, 2):
            Q((r, c), (s, c), 2.0 * w.p_cell)
    const += w.p_cell * spec.n_cells

    # p_area · Σ_r (Σ_c x_rc − a_r)²   ← 같은 방의 모든 셀 쌍을 잇는 조밀한 클리크
    for room in spec.rooms:
        for c in spec.cells:
            L((room.key, c), w.p_area * (1.0 - 2.0 * room.area))
        for c, d in combinations(spec.cells, 2):
            Q((room.key, c), (room.key, d), 2.0 * w.p_area)
        const += w.p_area * room.area**2

    return lin, quad, const


# ────────────────────────────────────────── 독립 검증용 평가기
def raw_values(spec: BuildingSpec, assignment: list) -> dict[str, float]:
    """계수를 쓰지 않고 도면을 직접 훑어 12개 항의 정규화 값을 센다."""
    nrm = normalizers(spec)
    a = assignment
    core = spec.core_room

    cell_violation = sum(1 for k in a if k is None)
    counts = {k: 0 for k in spec.room_keys}
    for k in a:
        if k is not None:
            counts[k] += 1
    area_error = sum((counts[r.key] - r.area) ** 2 for r in spec.rooms)

    adjacency = compactness = corridor = noise = 0.0
    for c, d in spec.neighbor_pairs:
        rc, rd = a[c], a[d]
        if rc is None or rd is None:
            continue
        if rc == rd:
            compactness += 1.0
            continue
        adjacency += spec.adj_weight(rc, rd)
        if rc == core or rd == core:
            corridor += 1.0
        R, S = spec.room_by_key[rc], spec.room_by_key[rd]
        noise += R.noise * S.quiet + S.noise * R.quiet

    daylight = solar = privacy = circulation = plumbing = thermal = 0.0
    for c, key in enumerate(a):
        if key is None:
            continue
        room = spec.room_by_key[key]
        inv = 1.0 / room.area
        if room.needs_window:
            if spec.is_perimeter(c):
                daylight += inv
            if spec.is_south(c):
                solar += inv
        elif spec.is_perimeter(c):
            thermal += inv
        privacy += room.privacy * spec.entrance_dist(c) * inv
        circulation += room.public * (1.0 - spec.entrance_dist(c)) * inv
        if room.wet:
            plumbing += (1.0 - spec.core_dist(c)) * inv

    return {
        "cell_violation": float(cell_violation),
        "area_error": float(area_error),
        "adjacency": adjacency / nrm["adjacency"],
        "compactness": compactness / nrm["compactness"],
        "corridor": corridor / nrm["corridor"],
        "noise": noise / nrm["noise"],
        "daylight": daylight / nrm["daylight"],
        "solar": solar / nrm["solar"],
        "privacy": privacy / nrm["privacy"],
        "circulation": circulation / nrm["circulation"],
        "plumbing": plumbing / nrm["plumbing"],
        "thermal": thermal / nrm["thermal"],
    }


def score_from_values(vals: dict[str, float], w) -> float:
    """항 값 + 가중치 → 에너지."""
    return sum(
        t.sign * getattr(w, t.weight_field) * vals[t.key] for t in TERM_META
    )
