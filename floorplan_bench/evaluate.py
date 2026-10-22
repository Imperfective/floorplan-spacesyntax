"""도면 평가 모델 — 세대(Unit) 하나를 세 갈래로 채점한다.

    ① 시공 가능성(feasibility)  필수실 구성·겹침·출입 불가 실·채광·형태 → 오류/경고
    ② 공간구문(Space Syntax)    추정 투과성 그래프 위의 깊이·통합도 (Hillier & Hanson 1984)
    ③ 정답지 근접도(typicality) AI 허브 실제 아파트 분포(baseline) 대비 얼마나 '흔한' 도면인가

회의 결정: 주관적 '좋은 도면' 대신 ① 실제 시공 가능한가, ③ 실제 지어진 도면(AI 허브)과
얼마나 가까운가로 본다. ②는 ③의 비교 지표로 들어간다.

각 기준의 근거(basis)는 CRITERIA에 모아 두었다. 팀이 채택한 SCI 논문이 정해지면
basis 칸만 채우면 보고서에 그대로 나온다.

점수에 무엇을 어떻게 넣을지는 criteria.py(사용자 조건)가 정한다. 이 모듈은 세대마다
조건이 읽을 지표표(measures)를 만든다 — 전역 지표와 실별 지표.
"""

from __future__ import annotations

import json
import math
import statistics as st
from dataclasses import asdict, dataclass, fields

from .aihub import CIRCULATION, LoadOptions, StructSheet, Unit, _inside
from .criteria import Config, score_all
from .spacesyntax import CARRIER, SyntaxGraph, SyntaxRules, analyze_graph, bfs_depths

# ═══════════════════════════════════════════════ 근거 목록
CRITERIA: dict[str, dict] = {
    "F1": {"name": "필수실 구성", "basis": "주택건설기준 등에 관한 규정(세대 기본 구성) — 팀 확인 필요"},
    "F2": {"name": "실 겹침 없음", "basis": "기하 정합성"},
    "F3": {"name": "출입 불가 실 없음", "basis": "기하 정합성 / Hillier & Hanson(1984) 투과성"},
    "F4": {"name": "침실 경유 동선 없음", "basis": "프라이버시 위계 — 팀 채택 논문으로 교체"},
    "F5": {"name": "주방-화장실 직결 없음", "basis": "위생 동선 — 팀 채택 논문으로 교체"},
    "F6": {"name": "거실·침실 채광(외기 접면)", "basis": "건축법 시행령 제51조(거실 채광) 취지"},
    "F7": {"name": "실 형태비", "basis": "가구 배치 가능성 — 팀 채택 논문으로 교체"},
    "F8": {"name": "문·창 겹침 없음 (STR)", "basis": "기하 정합성(회의 예시: 창에 문이 걸림)"},
    "S": {"name": "공간구문 지표", "basis": "Hillier & Hanson, The Social Logic of Space (1984)"},
    "T": {"name": "정답지 근접도", "basis": "AI 허브 실제 아파트 분포를 정답지로 사용 (회의 결정)"},
}


# ═══════════════════════════════════════════════ 판정 변수 (사용자가 바꾼다)
@dataclass(frozen=True)
class EvalParams:
    """문 추정 규칙과 시공 가능성 판정의 임계값. 웹 '변수' 칸과 같은 이름."""

    balcony: str = "leaf"
    """SPA 라벨엔 문이 없다 — 발코니를 어떻게 잇나.
    leaf = 가장 넓게 맞닿은 거실·침실·주방 하나에만 | all = 맞닿은 곳 모두(통로가 됨) | none = 제외"""
    include_service: bool = True
    """실외기실을 노드로 포함한다."""
    bridge_isolated: bool = True
    """규칙으로 문이 안 생긴 조각을 가장 길게 맞닿은 곳에 문 하나로 잇는다."""
    overlap_max: float = 0.05
    """작은 실 넓이 대비 이보다 많이 겹치면 '겹침'(F2)."""
    daylight_min_m: float = 0.9
    """거실·침실이 외기·발코니에 이만큼은 면해야 채광 가능(F6)."""
    door_window_min_overlap: float = 0.15
    """STR: 문·창 바운딩박스가 작은 쪽 대비 이만큼 겹치면 '문·창 겹침'(F8)."""

    def as_dict(self) -> dict:
        return asdict(self)


PermeabilityRules = EvalParams  # 이전 이름


def split_params(params: dict) -> tuple[LoadOptions, EvalParams]:
    """설정 파일의 평평한 params → (읽기 옵션, 판정 변수). 모르는 키는 무시."""
    lk = {f.name for f in fields(LoadOptions)}
    ek = {f.name for f in fields(EvalParams)}
    return (LoadOptions(**{k: v for k, v in params.items() if k in lk}),
            EvalParams(**{k: v for k, v in params.items() if k in ek}))


PARAM_HELP: dict[str, str] = {
    "wall_tol_px": "벽 하나 두께로 볼 거리(px)", "min_contact_m": "맞닿음으로 볼 최소 접면(m)",
    "min_space_ratio": "샤프트로 뺄 '기타' 크기(세대 대비)", "ref_bed_m2": "축척 추정: 침실 중앙값(㎡)",
    "orphan_reach_m": "떨어진 실을 세대에 붙일 거리(m)", "px_per_m": "축척 고정(px/m, 비우면 추정)",
    "balcony": "발코니 연결 leaf|all|none", "include_service": "실외기실 포함",
    "bridge_isolated": "고립 조각 자동 연결", "overlap_max": "겹침 허용 비율",
    "daylight_min_m": "채광 최소 접면(m)", "door_window_min_overlap": "문·창 겹침 판정 비율",
}


# 용도 → 문을 둘 수 있는 상대 용도, 우선순위 순. "ANY_OF"는 맞닿은 모든 상대와 연결.
_ONE_OF = {
    "bed": ["living", "etc", "multi", "kitchen", "entry"],   # 출입문 하나: 동선 공간 중 우선순위
    "bath": ["dress", "living", "etc", "multi", "entry", "kitchen", "bed"],
    "dress": ["bed", "etc", "living", "multi"],
    "ac": ["balcony", "bed", "living", "kitchen", "etc"],
}
_CIRC = set(CIRCULATION)


def permeability(u: Unit, rules: PermeabilityRules = PermeabilityRules()) -> dict[str, set[str]]:
    """세대 → 실 사이 출입 그래프(추정)."""
    sp = u.spaces
    nodes = [k for k, s in sp.items()
             if not (s.kind == "balcony" and rules.balcony == "none")
             and not (s.kind == "ac" and not rules.include_service)]
    adj = {k: set() for k in nodes}

    def link(a, b):
        if a in adj and b in adj and a != b:
            adj[a].add(b)
            adj[b].add(a)

    def contact(a, b):
        return u.contact.get(tuple(sorted((a, b))), 0.0)

    # 동선 공간끼리는 맞닿으면 열려 있다고 본다(거실-주방-현관-복도)
    for (a, b) in u.contact:
        if sp[a].kind in _CIRC and sp[b].kind in _CIRC:
            link(a, b)

    for k in nodes:
        kind = sp[k].kind
        nbrs = u.neighbors(k)
        if kind in _ONE_OF:
            for target in _ONE_OF[kind]:
                cands = [n for n in nbrs if sp[n].kind == target and n in adj]
                if kind == "bath" and target == "bed":
                    # 부부욕실: 드레스룸이 없으면 가장 넓은 침실(안방)로
                    cands.sort(key=lambda n: -sp[n].area_px)
                else:
                    cands.sort(key=lambda n: -contact(k, n))
                if cands:
                    link(k, cands[0])
                    break
        elif kind == "balcony" and rules.balcony != "none":
            hosts = [n for n in nbrs if sp[n].kind in ("living", "bed", "kitchen", "etc", "multi")]
            if rules.balcony == "all":
                for n in hosts:
                    link(k, n)
            elif hosts:
                order = {"living": 0, "kitchen": 1, "bed": 2, "multi": 3, "etc": 4}
                link(k, min(hosts, key=lambda n: (order[sp[n].kind], -contact(k, n))))
            else:
                # 발코니끼리 이어진 경우(긴 발코니가 둘로 라벨링됨)
                for n in nbrs:
                    if sp[n].kind == "balcony":
                        link(k, n)

    # 규칙으로 문이 안 생긴 조각(침실 안 붙박이장, 발코니 너머 대피공간 등)은
    # 현관 쪽 덩어리와 가장 길게 맞닿은 곳에 문을 하나 낸다. 맞닿은 곳이 없으면 고립(F3).
    while rules.bridge_isolated:
        reach = _reach(adj, [e for e in u.of("entry") if e in adj])
        bridges = [(contact(a, b), a, b) for (a, b) in u.contact
                   if a in adj and b in adj and (a in reach) != (b in reach)]
        if not reach or not bridges:
            break
        _, a, b = max(bridges)
        link(a, b)
    return adj


def _reach(adj: dict[str, set[str]], starts: list[str], blocked: set[str] = frozenset()) -> set[str]:
    seen, q = set(starts), list(starts)
    while q:
        q = [n for v in q for n in adj[v] if n not in seen and n not in blocked and not seen.add(n)]
    return seen


def syntax_graph(u: Unit, adj: dict[str, set[str]]) -> SyntaxGraph:
    """현관에 외부(carrier)를 붙여 spacesyntax.analyze_graph가 받는 그래프로."""
    nodes = [CARRIER] + list(adj)
    g_adj = {k: set(v) for k, v in adj.items()}
    g_adj[CARRIER] = set()
    for e in u.of("entry"):
        if e in g_adj:
            g_adj[CARRIER].add(e)
            g_adj[e].add(CARRIER)
    labels = {k: u.spaces[k].name for k in adj}
    labels[CARRIER] = "외부"
    return SyntaxGraph(nodes, g_adj, labels, {}, SyntaxRules(vga_enabled=False))


# ═══════════════════════════════════════════════ ① 시공 가능성
def _overlap_ratio(a, b, step: float) -> float:
    """두 실이 겹치는 넓이 / 작은 실 넓이 (격자 표본)."""
    ax, ay, aw, ah = a.bbox
    bx, by, bw, bh = b.bbox
    x0, y0, x1, y1 = max(ax, bx), max(ay, by), min(ax + aw, bx + bw), min(ay + ah, by + bh)
    if x1 <= x0 or y1 <= y0:
        return 0.0
    hit = 0
    y = y0 + step / 2
    while y < y1:
        x = x0 + step / 2
        while x < x1:
            if _inside((x, y), a.poly) and _inside((x, y), b.poly):
                hit += 1
            x += step
        y += step
    return hit * step * step / min(a.area_px, b.area_px)


def feasibility(u: Unit, adj: dict[str, set[str]], p: EvalParams = EvalParams()) -> list[dict]:
    """시공 가능성 위반 목록 — 설명용. 점수 반영은 measures()의 개수 지표를 조건이 읽는다."""
    sp, issues = u.spaces, []

    def add(cid, level, msg, rooms=()):
        issues.append({"id": cid, "level": level, "criterion": CRITERIA[cid]["name"],
                       "message": msg, "rooms": list(rooms)})

    # F1 필수실
    need = {"entry": (1, 1), "living": (1, 9), "kitchen": (1, 9), "bed": (1, 9), "bath": (1, 9)}
    for kind, (lo, hi) in need.items():
        n = len(u.of(kind))
        if not lo <= n <= hi:
            name = {"entry": "현관", "living": "거실", "kitchen": "주방", "bed": "침실", "bath": "화장실"}[kind]
            add("F1", "error", f"{name} {n}개 (허용 {lo}~{hi})")

    # F2 겹침
    keys = list(sp)
    step = u.px_per_m * 0.1
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            r = _overlap_ratio(sp[a], sp[b], step)
            if r > p.overlap_max:
                add("F2", "error", f"{sp[a].name}·{sp[b].name} {r:.0%} 겹침", (a, b))

    # F3 출입 불가 — 현관(외부)에서 닿지 않는 실
    entries = [e for e in u.of("entry") if e in adj]
    reach = _reach(adj, entries)
    lost = [k for k in adj if k not in reach]
    main = [k for k in lost if sp[k].kind in ("living", "bed", "kitchen", "bath", "dress", "entry")]
    minor = [k for k in lost if k not in main]
    if main:
        add("F3", "error", "현관에서 닿지 않는 실: " + ", ".join(sp[k].name for k in main), main)
    if minor:
        # 실제 도면에서도 흔하다 — 1~2㎡ 띠 모양 '기타'는 대개 샤프트·외부 장식이다
        add("F3", "info", "고립된 부속 공간(샤프트·외부 요소로 간주): "
            + ", ".join(sp[k].name for k in minor), minor)

    # F4 침실을 거쳐야만 가는 침실
    if entries:
        for b in u.of("bed"):
            if b not in reach:
                continue
            blocked = {x for x in u.of("bed") if x != b}
            if b not in _reach(adj, entries, blocked):
                add("F4", "warn", f"{sp[b].name}은(는) 다른 침실을 거쳐야 들어감", (b,))

    # F5 주방-화장실 직결
    for k in u.of("kitchen"):
        for n in adj.get(k, ()):
            if sp[n].kind == "bath":
                add("F5", "warn", f"{sp[k].name}에서 {sp[n].name}로 바로 출입", (k, n))

    # F6 채광 — 외기나 발코니에 daylight_min_m 이상 면해야 한다
    min_ext = p.daylight_min_m * u.px_per_m
    for k, s in sp.items():
        if s.kind not in ("living", "bed"):
            continue
        if _daylight_px(u, k) < min_ext:
            add("F6", "warn", f"{s.name}이(가) 외기·발코니에 면하지 않음(창 둘 자리 없음)", (k,))
    # F7(형태)은 실별 지표 aspect·fill로 옮겼다 — 조건에서 기준을 정한다.
    return issues


def _daylight_px(u: Unit, k: str) -> float:
    return u.exterior.get(k, 0) + sum(u.contact.get(tuple(sorted((k, n))), 0) for n in u.neighbors(k)
                                      if u.spaces[n].kind in ("balcony", "ac"))


def struct_checks(sh: StructSheet, min_overlap: float = EvalParams.door_window_min_overlap) -> list[dict]:
    """STR 라벨: 문과 창이 겹치는 곳(회의 예시). 겹친 넓이 / 작은 쪽 넓이 > min_overlap."""
    out = []
    for d in sh.doors:
        for w in sh.windows:
            (ax, ay, aw, ah), (bx, by, bw, bh) = d["bbox"], w["bbox"]
            ix = max(0.0, min(ax + aw, bx + bw) - max(ax, bx))
            iy = max(0.0, min(ay + ah, by + bh) - max(ay, by))
            small = max(1.0, min(aw * ah, bw * bh))
            if ix * iy / small > min_overlap:
                out.append({"id": "F8", "level": "error", "criterion": CRITERIA["F8"]["name"],
                            "message": f"문({d['type']}) #{d['id']} 과 창({w['type']}) #{w['id']} 겹침 "
                                       f"{ix * iy / small:.0%}",
                            "rooms": [], "door": d["id"], "window": w["id"]})
    return out


# ═══════════════════════════════════════════════ ② 공간구문 + ③ 비교용 특징
FEATURES: dict[str, str] = {
    # 구성
    "n_bed": "침실 수", "n_bath": "화장실 수", "n_nodes": "실 수(그래프 노드)",
    # 면적 비율 (세대 합계 대비, 축척 무관)
    "r_living": "거실 면적비", "r_bed": "침실 면적비", "r_kitchen": "주방 면적비",
    "r_bath": "화장실 면적비", "r_entry": "현관 면적비", "r_balcony": "발코니 면적비",
    "r_master": "안방/거실 면적비",
    # 공간구문
    "mean_depth": "전체 평균 깊이", "max_depth": "외부로부터 최대 깊이",
    "living_depth": "거실 깊이(외부→)", "bed_depth": "침실 평균 깊이",
    "living_int_rank": "거실 통합도 순위(1=가장 통합)", "living_RRA": "거실 RRA",
    "ringiness": "고리성(순환 동선)",
}


def features(u: Unit, adj: dict[str, set[str]]) -> tuple[dict, dict]:
    g = syntax_graph(u, adj)
    res = analyze_graph(g)
    nodes, glob = res["nodes"], res["global"]
    tot = u.area_px
    by = lambda kind: sum(u.spaces[k].area_px for k in u.of(kind))
    d0 = bfs_depths(g, CARRIER)
    beds = u.of("bed")
    living = u.of("living")
    ranked = sorted((k for k in adj if nodes[k]["integration"] == nodes[k]["integration"]),
                    key=lambda k: -nodes[k]["integration"])
    E = glob["edge_count"]
    V = glob["node_count"]
    f = {
        "n_bed": len(beds), "n_bath": len(u.of("bath")), "n_nodes": len(adj),
        "r_living": by("living") / tot, "r_bed": by("bed") / tot, "r_kitchen": by("kitchen") / tot,
        "r_bath": by("bath") / tot, "r_entry": by("entry") / tot, "r_balcony": by("balcony") / tot,
        "r_master": (max(u.spaces[b].area_px for b in beds) / by("living")) if beds and living and by("living") else None,
        "mean_depth": glob["mean_depth_system"],
        "max_depth": glob["max_depth_from_carrier"],
        "living_depth": d0.get(living[0]) if living else None,
        "bed_depth": st.mean([d0[b] for b in beds if b in d0]) if any(b in d0 for b in beds) else None,
        "living_int_rank": (ranked.index(living[0]) + 1) if living and living[0] in ranked else None,
        "living_RRA": nodes[living[0]]["RRA"] if living else None,
        "ringiness": (E - V + 1) / max(1, 2 * V - 5),
    }
    return f, res


# ═══════════════════════════════════════════════ ③ 정답지(baseline)
def type_key(u: Unit) -> str:
    """평형 대용 — 축척이 없으므로 '침실 수-화장실 수' (예: 3R2B ≈ 84㎡형)."""
    return f"{len(u.of('bed'))}R{len(u.of('bath'))}B"


def build_baseline(rows: list[dict]) -> dict:
    """특징 행 목록 → 유형별·전체 분포(중앙값, 강건 척도)."""
    def summarize(rs):
        out = {}
        for k in FEATURES:
            xs = sorted(r[k] for r in rs if r.get(k) is not None and r[k] == r[k])
            if len(xs) < 3:
                continue
            med = st.median(xs)
            mad = st.median([abs(x - med) for x in xs]) * 1.4826
            q1, q3 = xs[len(xs) // 4], xs[(3 * len(xs)) // 4]
            spread = max(mad, (q3 - q1) / 1.349, 0.05 * abs(med), 1e-6)
            out[k] = {"median": med, "scale": spread, "n": len(xs), "min": xs[0], "max": xs[-1]}
        return out

    by_type: dict[str, list[dict]] = {}
    for r in rows:
        by_type.setdefault(r["type"], []).append(r)
    return {
        "n_units": len(rows),
        "all": summarize(rows),
        "types": {t: {"n": len(rs), "features": summarize(rs)} for t, rs in by_type.items() if len(rs) >= 5},
        "type_counts": dict(sorted(((t, len(rs)) for t, rs in by_type.items()), key=lambda x: -x[1])),
    }


def typicality(f: dict, ttype: str, baseline: dict, skip: tuple = ("n_bed", "n_bath")) -> dict:
    """특징마다 강건 z → 0~100점. 같은 유형 분포가 있으면 그것을, 없으면 전체 분포를."""
    ref = baseline["types"].get(ttype, {}).get("features") or baseline["all"]
    used = "type:" + ttype if ttype in baseline["types"] else "all"
    per = {}
    for k, b in ref.items():
        if k in skip or f.get(k) is None or f[k] != f[k]:
            continue
        z = (f[k] - b["median"]) / max(b["scale"] or 0.0, 1e-3)  # JSON 반올림으로 0이 될 수 있다
        per[k] = {"value": f[k], "median": b["median"], "z": z,
                  "score": max(0.0, 100.0 * (1 - abs(z) / 3.0))}
    score = st.mean(p["score"] for p in per.values()) if per else float("nan")
    return {"reference": used, "score": score, "features": per}


# ═══════════════════════════════════════════════ 지표표 (조건이 읽는 값)
def measures(u: Unit, adj: dict[str, set[str]], issues: list[dict], res: dict,
             feats: dict, typ: dict | None = None, door_window_overlaps: int | None = None) -> dict:
    """criteria.MEASURES의 이름 그대로 — 전역 값과 실별 값."""
    count = lambda cid: sum(1 for i in issues if i["id"] == cid and i["level"] != "info")
    nodes, glob = res["nodes"], res["global"]
    ranked = sorted((k for k in adj if nodes[k]["integration"] == nodes[k]["integration"]),
                    key=lambda k: -nodes[k]["integration"])
    g = {
        "missing_required": count("F1"),
        "overlap_pairs": count("F2"),
        "unreachable_rooms": sum(len(i["rooms"]) for i in issues if i["id"] == "F3" and i["level"] == "error"),
        "bed_via_bed": count("F4"),
        "kitchen_bath": count("F5"),
        "unlit_rooms": count("F6"),
        "door_window_overlaps": door_window_overlaps,
        "n_bed": feats["n_bed"], "n_bath": feats["n_bath"], "n_spaces": len(adj),
        "mean_depth_system": glob["mean_depth_system"],
        "max_depth_from_carrier": glob["max_depth_from_carrier"],
        "mean_integration": glob["mean_integration"],
        "intelligibility": glob["intelligibility"],
        "ringiness": feats["ringiness"],
        "typicality": typ["score"] if typ else None,
    }
    rooms = {}
    for k, sp in u.spaces.items():
        w, h = sp.bbox[2], sp.bbox[3]
        n = nodes.get(k)
        rooms[k] = {
            "name": sp.name, "kind": sp.kind,
            "area_ratio": sp.area_px / u.area_px,
            "est_m2": u.area_m2(k),
            "aspect": max(w, h) / max(1.0, min(w, h)),
            "fill": sp.area_px / max(1.0, w * h),
            "daylight_m": _daylight_px(u, k) / u.px_per_m,
            "step_depth": n["step_depth_from_carrier"] if n else None,
            "integration": n["integration"] if n else None,
            "integration_rank": (ranked.index(k) + 1) if k in ranked else None,
            "RRA": n["RRA"] if n else None,
            "mean_depth": n["mean_depth"] if n else None,
            "connectivity": n["connectivity"] if n else None,
            "control_value": n["control_value"] if n else None,
            "choice": n["choice"] if n else None,
        }
    return {"global": g, "rooms": rooms}


# ═══════════════════════════════════════════════ 종합
def evaluate(u: Unit, baseline: dict | None = None,
             rules: EvalParams = EvalParams(), config: Config | None = None) -> dict:
    """세대 하나 → 지표표 + 사용자 조건 채점. config가 없으면 기본 조건 세트."""
    config = config or Config()
    adj = permeability(u, rules)
    issues = feasibility(u, adj, rules)
    f, res = features(u, adj)
    typ = typicality(f, type_key(u), baseline) if baseline else None
    m = measures(u, adj, issues, res, f, typ)
    sc = score_all(config.criteria, m)
    out = {
        "unit": u.uid, "type": type_key(u),
        "est_area_m2": round(u.area_m2(), 1), "px_per_m": round(u.px_per_m, 1),
        "spaces": {k: {"name": s.name, "kind": s.kind, "area_ratio": s.area_px / u.area_px,
                       "est_m2": round(u.area_m2(k), 1)} for k, s in u.spaces.items()},
        "dropped_small": u.dropped,
        "doors_inferred": sorted({tuple(sorted((a, b))) for a in adj for b in adj[a]}),
        "feasibility": {
            "pass": not any(i["level"] == "error" for i in issues),
            "errors": sum(i["level"] == "error" for i in issues),
            "warnings": sum(i["level"] == "warn" for i in issues),
            "issues": issues,
        },
        "measures": m,
        "features": f,
        "score": {"total": sc["total"], "grade": sc["grade"], "base": sc["base"],
                  "penalty": sc["penalty"], "gated": sc["gated"], "skipped": sc["skipped"]},
        "criteria_rows": sc["rows"],
    }
    if typ:
        out["typicality"] = typ
    return out


def to_json(obj) -> str:
    return json.dumps(_clean(obj), ensure_ascii=False, indent=2)


def _clean(o):
    if isinstance(o, float):
        return None if (o != o or o in (math.inf, -math.inf)) else round(o, 4)
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple, set)):
        return [_clean(v) for v in o]
    return o
