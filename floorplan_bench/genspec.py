"""AI 허브 실제 도면에서 뽑은 생성 사양(docs/data/aihub-genspec.json) → 격자 생성기의 BuildingSpec.

웹 프로그램의 '생성 사양' 화면과 tools/build_default_data.js 가 같은 사양을 만든다(유형·침실 수별).
손으로 정하던 방 면적·채광·현관 거리·인접 선호를 실측 분포로 바꿔, CP-SAT · QUBO(· CQM)에 그대로 넣는다.

    from floorplan_bench.genspec import spec_from_aihub
    spec = spec_from_aihub("3R2B", width=10, height=10)     # → BuildingSpec

옮기는 규칙
- 실 구성: 역할별 최빈 개수(침실은 안방 master 1 + 나머지 bed). 있을 확률 50% 미만인 역할은 넣지 않는다.
  '기타'(etc)는 복도·팬트리·덕트를 모은 라벨이라 기본으로 뺀다(skip=() 로 넣을 수 있음).
- 사양은 필수 실을 갖춘 세대만으로 만든다(현관 조각만 있는 세대는 집의 본보기가 아님).
- 면적: 역할별 면적비 중앙값을 합 1로 맞춰 격자 셀 수에 나눈다(최대 나머지 방식, 실마다 최소 2셀).
- 채광(needs_window): 그 역할이 외기·발코니에 면할 확률 ≥ 0.5.
- 프라이버시·공용성: 현관에서 깊이 중앙값을 역할 사이에서 0~1로 정규화(깊을수록 privacy↑, public↓).
- 인접 선호: 벽을 맞댈 확률 p → 2p − 1(−1~1). |값| < 0.15는 뺀다. 같은 역할이 여럿이면 모든 짝에 같은 값.
- 소음·정숙·급배수: 데이터에 없는 성질이라 역할별 관행 값(내장 apartment_8x8과 같은 값)을 쓴다.
"""

from __future__ import annotations

import json
import os

from .spec import BuildingSpec, Room

DEFAULT_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "data", "aihub-genspec.json")

# 역할 → (격자 키 접두, 이름, 소음, 정숙, 급배수, 색) — 소음·정숙·급배수는 데이터에 없어 관행 값
ROLE_META = {
    "entry": ("hall", "현관·복도", 0.2, 0.0, False, "#b8b8b8"),
    "living": ("living", "거실", 0.8, 0.2, False, "#8ecae6"),
    "kitchen": ("kitchen", "주방·식당", 1.0, 0.0, True, "#ffb703"),
    "master": ("master", "안방", 0.1, 1.0, False, "#a8dadc"),
    "bed": ("bed", "침실", 0.2, 0.9, False, "#bde0fe"),
    "bath": ("bath", "화장실", 0.4, 0.1, True, "#cdb4db"),
    "dress": ("dress", "드레스룸", 0.1, 0.5, False, "#e9c46a"),
    "balcony": ("balcony", "발코니", 0.3, 0.0, False, "#d8f3dc"),
    "ac": ("ac", "실외기실", 0.6, 0.0, False, "#adb5bd"),
    "multi": ("multi", "다목적공간", 0.4, 0.3, False, "#ffd6a5"),
    "etc": ("store", "기타·다용도", 0.5, 0.0, True, "#c7c7a6"),
}


def load_genspec(path: str = DEFAULT_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        gs = json.load(f)
    if gs.get("kind") != "aihub-genspec":
        raise ValueError("생성 사양 JSON(kind: aihub-genspec)이 아닙니다")
    return gs


def _largest_remainder(weights: list[float], total: int, minimum: int) -> list[int]:
    n = len(weights)
    if total < minimum * n:
        raise ValueError(f"격자 {total}셀에 실 {n}개를 최소 {minimum}셀씩 넣을 수 없습니다")
    free = total - minimum * n
    s = sum(weights) or 1.0
    raw = [w / s * free for w in weights]
    out = [int(r) for r in raw]
    order = sorted(range(n), key=lambda i: raw[i] - out[i], reverse=True)
    for i in order[: free - sum(out)]:
        out[i] += 1
    return [o + minimum for o in out]


def spec_from_genspec(gs: dict, stratum: str = "3R2B", width: int = 10, height: int = 10,
                      entrance: tuple[int, int] | None = None, plumbing_core: tuple[int, int] | None = None,
                      min_present: float = 0.5, min_cells: int = 2, skip: tuple[str, ...] = ("etc",)) -> BuildingSpec:
    st = gs["strata"].get(stratum)
    if st is None:
        raise KeyError(f"사양에 '{stratum}' 층이 없습니다 — 있는 층: {', '.join(gs['strata'])}")
    prog, rooms = st["program"], st["rooms"]

    # 실 목록: (역할, 키)
    slots: list[tuple[str, str]] = []
    for role in gs["roles"]:
        p = prog.get(role)
        if role in skip or not p or role not in rooms or p["present"] < min_present or role not in ROLE_META:
            continue
        count = max(1, int(p["mode"]))
        prefix = ROLE_META[role][0]
        for k in range(count):
            # 첫 실은 접두 그대로(bath, kitchen), 둘째부터 번호(bath2). 침실은 안방(master) 다음이라 bed2부터
            key = f"{prefix}{k + 2}" if role == "bed" else prefix if k == 0 else f"{prefix}{k + 1}"
            slots.append((role, key))

    cells = width * height
    areas = _largest_remainder([rooms[r]["area"]["p50"] for r, _ in slots], cells, min_cells)

    depths = {r: rooms[r]["depth"]["p50"] for r, _ in slots if rooms[r]["depth"]["p50"] is not None}
    dmin, dmax = (min(depths.values()), max(depths.values())) if depths else (0, 1)
    span = (dmax - dmin) or 1.0

    room_objs = []
    for (role, key), area in zip(slots, areas):
        _, name, noise, quiet, wet, color = ROLE_META[role]
        privacy = round((depths.get(role, dmin) - dmin) / span, 3)
        label = name if key == ROLE_META[role][0] else f"{name} {key[len(ROLE_META[role][0]):]}"
        room_objs.append(Room(key, label, area, rooms[role]["ext"] >= 0.5, privacy, round(1 - privacy, 3), noise, quiet, wet, color))

    adjacency: dict[tuple[str, str], float] = {}
    keys_of = {}
    for role, key in slots:
        keys_of.setdefault(role, []).append(key)
    for pair, w in st["suggest"]["weights"].items():
        a, b = pair.split("|")
        for ka in keys_of.get(a, []):
            for kb in keys_of.get(b, []):
                if ka != kb:
                    adjacency[tuple(sorted((ka, kb)))] = float(w)

    return BuildingSpec(
        key=f"aihub_{stratum}_{width}x{height}",
        name=f"AI 허브 {st.get('label', stratum)} 실측 사양 ({width}×{height} = {cells}셀, {st['n']:,}세대 기준)",
        width=width, height=height,
        entrance=entrance or (0, height - 1),
        plumbing_core=plumbing_core or (width - 1, 0),
        rooms=room_objs,
        adjacency=adjacency,
        core_room="hall",
    )


def spec_from_aihub(stratum: str = "3R2B", width: int = 10, height: int = 10, path: str = DEFAULT_PATH, **kw) -> BuildingSpec:
    return spec_from_genspec(load_genspec(path), stratum, width, height, **kw)
