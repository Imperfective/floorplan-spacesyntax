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

from . import jsmath
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
    """문 추정 규칙·시공 가능성 판정의 임계값·정답지 채점 변수. 웹 '변수' 칸(PARAMS)과 같은 이름·기본값."""

    graph: str = "door"
    """그래프 규약. door = 문 추정(투과) 그래프 | adjacency = 벽 인접 그래프(맞닿은 실은 모두 이어짐)."""
    balcony: str = "leaf"
    """SPA 라벨엔 문이 없다 — 발코니를 어떻게 잇나.
    leaf = 가장 넓게 맞닿은 거실·침실·주방 하나에만 | all = 맞닿은 곳 모두(통로가 됨) | none = 제외"""
    include_service: bool = True
    """실외기실을 노드로 포함한다."""
    bridge_isolated: bool = True
    """규칙으로 문이 안 생긴 조각을 가장 길게 맞닿은 곳에 문 하나로 잇는다."""
    overlap_max: float = 0.05
    """작은 실 넓이 대비 이보다 많이 겹치면 '겹침'(F2)."""
    daylight_min_px: float = 81.0
    """거실·침실이 외기·발코니에 이만큼(px × s) 면해야 채광 가능(F6). 배율 1에서 약 0.9m."""
    door_window_min_overlap: float = 0.20
    """STR: 문·창 바운딩박스가 작은 쪽 대비 이만큼 겹치면 '문·창 겹침'(F8)."""
    # 정답지 채점에만 쓰는 변수(rescore) — 원본을 다시 읽지 않고 다시 채점할 수 있다
    z_cut: float = 3
    """점수 = 100 × max(0, 1 − |z| / z_cut)."""
    strata_min: int = 15
    """같은 침실 수 세대가 이만큼 있으면 그 층(stratum)만 기준으로."""
    w_syntax: float = 30
    """영역 가중치 — 공간구문."""
    w_area: float = 20
    """영역 가중치 — 면적 구성."""
    w_shape: float = 10
    """영역 가중치 — 형태."""
    w_ext: float = 10
    """영역 가중치 — 외기 접면."""

    def as_dict(self) -> dict:
        return asdict(self)


PermeabilityRules = EvalParams  # 이전 이름

# 정답지 채점 변수(웹 PARAMS의 rescore: true)
SCORING_KEYS = ("z_cut", "strata_min", "w_syntax", "w_area", "w_shape", "w_ext")


def scoring_params(p=None) -> dict:
    """웹 scoringParams — 채점 변수만 뽑고, 비어 있으면 기본값."""
    if isinstance(p, EvalParams):
        p = p.as_dict()
    p = p or {}
    defaults = EvalParams()
    return {k: p[k] if p.get(k) is not None else getattr(defaults, k) for k in SCORING_KEYS}


def default_params() -> dict:
    """웹 defaultParams — 읽기 옵션 + 판정 변수, 평평한 하나의 dict."""
    return {**LoadOptions().as_dict(), **EvalParams().as_dict()}


def split_params(params: dict) -> tuple[LoadOptions, EvalParams]:
    """설정 파일의 평평한 params → (읽기 옵션, 판정 변수). 모르는 키는 무시."""
    lk = {f.name for f in fields(LoadOptions)}
    ek = {f.name for f in fields(EvalParams)}
    return (LoadOptions(**{k: v for k, v in params.items() if k in lk}),
            EvalParams(**{k: v for k, v in params.items() if k in ek}))


PARAM_HELP: dict[str, str] = {
    "px_per_m": "축척 고정(px/m, 비우면 추정 — ㎡·m 표시용)", "ref_bed_m2": "축척 추정: 침실 중앙값(㎡)",
    "ref_bed_side_px": "축척 배율 기준: 침실 한 변(px)",
    "wall_tol_px": "실 사이 간격 허용 — 내벽(px)", "wall_tol_ext_px": "실 사이 간격 허용 — 외벽 쪽(px)",
    "min_contact_px": "최소 접촉 길이(px × max(1, s))", "duct_area_px": "덕트로 뺄 '기타' 면적(px² × s²)",
    "orphan_reach_m": "떨어진 실을 세대에 붙일 거리(m)", "sample_step_px": "경계 표본 간격(px)",
    "graph": "그래프 규약 door|adjacency",
    "balcony": "발코니 연결 leaf|all|none", "include_service": "실외기실 포함",
    "bridge_isolated": "고립 조각 자동 연결", "overlap_max": "겹침 허용 비율",
    "daylight_min_px": "채광 최소 접면(px × s)", "door_window_min_overlap": "문·창 겹침 판정 비율",
    "z_cut": "z 절단값", "strata_min": "층화 최소 세대 수",
    "w_syntax": "영역 가중치 — 공간구문", "w_area": "영역 가중치 — 면적 구성",
    "w_shape": "영역 가중치 — 형태", "w_ext": "영역 가중치 — 외기 접면",
}


# 용도 → 문을 둘 수 있는 상대 용도, 우선순위 순. "ANY_OF"는 맞닿은 모든 상대와 연결.
_ONE_OF = {
    "bed": ["living", "etc", "multi", "kitchen", "entry"],   # 출입문 하나: 동선 공간 중 우선순위
    "bath": ["dress", "living", "etc", "multi", "entry", "kitchen", "bed"],
    "dress": ["bed", "etc", "living", "multi"],
    "ac": ["balcony", "bed", "living", "kitchen", "etc"],
}
_CIRC = set(CIRCULATION)


class _OrderedSet(dict):
    """삽입 순서를 지키는 집합 — 웹 엔진의 Set과 같은 순서로 돈다.
    통제값·선택도처럼 이웃을 돌며 더하는 값은 더하는 순서에 따라 끝자리가 바뀌기 때문."""
    __slots__ = ()

    def __init__(self, items=()):
        super().__init__((x, None) for x in items)

    def add(self, x):
        self.setdefault(x, None)

    def __repr__(self):
        return "{" + ", ".join(map(repr, self)) + "}"


def permeability(u: Unit, rules: PermeabilityRules = PermeabilityRules()) -> dict[str, set[str]]:
    """세대 → 실 사이 출입 그래프(추정)."""
    sp = u.spaces
    nodes = [k for k, s in sp.items()
             if not (s.kind == "balcony" and rules.balcony == "none")
             and not (s.kind == "ac" and not rules.include_service)]
    adj = {k: _OrderedSet() for k in nodes}

    def link(a, b):
        if a in adj and b in adj and a != b:
            adj[a].add(b)
            adj[b].add(a)

    def contact(a, b):
        return u.contact.get(tuple(sorted((a, b))), 0.0)

    if rules.graph == "adjacency":   # 벽 인접 그래프 — 맞닿은 실은 모두 이어진 것으로 본다
        for (a, b) in u.contact:
            link(a, b)
        return adj

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
    g_adj = {k: _OrderedSet(v) for k, v in adj.items()}
    g_adj[CARRIER] = _OrderedSet()
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

    # F6 채광 — 외기나 발코니에 daylight_min_px × s 이상 면해야 한다
    min_ext = p.daylight_min_px * u.s
    for k, s in sp.items():
        if s.kind not in ("living", "bed"):
            continue
        if _daylight_px(u, k) < min_ext:
            add("F6", "warn", f"{s.name}이(가) 외기·발코니에 면하지 않음(창 둘 자리 없음)", (k,))
    # F7(형태)은 실별 지표 aspect·fill로 옮겼다 — 조건에서 기준을 정한다.
    return issues


def _daylight_px(u: Unit, k: str) -> float:
    s = 0
    for n in u.neighbors(k):   # 웹의 reduce와 같은 순서로 더한다
        if u.spaces[n].kind in ("balcony", "ac"):
            s += u.contact.get(tuple(sorted((k, n))), 0)
    return u.exterior.get(k, 0) + s


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


# ═══════════════════════════════════════════════ ② 공간구문 + ③ 비교용 특징 · 정답지
# 근거 문서(평면 평가 랩 v0.3.0 evidence)의 지표 — 공간구문 30 · 면적 20 · 형태 10 · 외기 접면 10.
# 모든 지표는 축척과 무관한 비율이다. 채점은 기준 분포(AI 허브)의 중앙값과 Qn 척도로 구한 강건 z,
# 값이 몇 개뿐인 이산 지표는 경험적 누적분포(백분위)로 한다. dir: two 양측 · up 높을수록 유리 · down 낮을수록 유리.
# 웹(docs/aihub-engine.js의 FEATURES)과 같은 표 — 고칠 때는 둘을 함께 고친다.
FEATURES: dict[str, dict] = {
    "int_ratio_lb": {"label": "거실/침실 통합도 비", "domain": "syntax", "dir": "two", "method": "z", "w": 1,
                     "cites": ["byun2016", "choi2014"], "grade": "A", "def": "거실 통합도 ÷ 침실 평균 통합도"},
    "int_ratio_kb": {"label": "주방/침실 통합도 비", "domain": "syntax", "dir": "two", "method": "z", "w": 1,
                     "cites": ["byun2016", "choi2014"], "grade": "A", "def": "주방 평균 통합도 ÷ 침실 평균 통합도"},
    "geno_tau": {"label": "유전형 순위 부합도 τ", "domain": "syntax", "dir": "up", "method": "pct", "w": 1,
                 "cites": ["hillier1987", "choi2014"], "grade": "A",
                 "def": "거실·주방·현관·침실·화장실 평균 통합도 순서와 거실 > 주방 > 현관 > 침실 > 화장실의 "
                        "Kendall τ_b(5유형이 모두 있을 때). 11개 값뿐이라 백분위로 채점"},
    "geno_dist": {"label": "유전형 프로필 거리", "domain": "syntax", "dir": "down", "method": "z", "w": 1,
                  "cites": ["hillier1987", "choi2014"], "grade": "A·C",
                  "def": "5유형 평균 통합도를 평면 안에서 표준화한 벡터와 기준 분포 중앙 벡터 사이의 거리"},
    "pp_depth": {"label": "공·사 깊이 차", "domain": "syntax", "dir": "up", "method": "pct", "w": 1,
                 "cites": ["park2024", "ham2017"], "grade": "B",
                 "def": "(침실·드레스룸 평균 깊이) − (거실·주방 평균 깊이). 정수 깊이라 백분위로 채점"},
    "int_func": {"label": "기능실 평균 통합도(실 수 보정)", "domain": "syntax", "dir": "two", "method": "resid", "w": 0.5,
                 "cites": ["hillier1984", "ostwald2011"], "grade": "C",
                 "def": "'기타'를 뺀 기능실 통합도 평균 — 기준 분포에서 log K(기능실 수)에 회귀한 잔차로 채점"},
    "control_living": {"label": "거실 통제값(참고)", "domain": "syntax", "dir": "two", "method": "z", "w": 0,
                       "cites": ["ostwald2011", "lee2018"], "grade": "C",
                       "def": "거실 이웃 실마다 1/(그 실의 연결 수)를 더한 값 — 점수에 넣지 않음"},
    "r_living": {"label": "거실 면적비", "domain": "area", "dir": "two", "method": "z", "w": 1,
                 "cites": ["sun2022"], "grade": "D", "def": "거실 면적 ÷ 세대 면적"},
    "r_kitchen": {"label": "주방 면적비", "domain": "area", "dir": "two", "method": "z", "w": 1,
                  "cites": ["sun2022"], "grade": "D", "def": "주방 면적 ÷ 세대 면적"},
    "r_bed": {"label": "침실 면적비(합)", "domain": "area", "dir": "two", "method": "z", "w": 1,
              "cites": ["sun2022"], "grade": "D", "def": "침실 면적 합 ÷ 세대 면적"},
    "r_bath": {"label": "화장실 면적비(합)", "domain": "area", "dir": "two", "method": "z", "w": 1,
               "cites": ["sun2022"], "grade": "D", "def": "화장실 면적 합 ÷ 세대 면적"},
    "r_balcony": {"label": "발코니 면적비(합)", "domain": "area", "dir": "two", "method": "z", "w": 1,
                  "cites": ["sun2022"], "grade": "D", "def": "발코니 면적 합 ÷ 세대 면적"},
    "pub_priv": {"label": "공용/개인 면적비", "domain": "area", "dir": "two", "method": "z", "w": 1,
                 "cites": ["park2024"], "grade": "B", "def": "(거실 + 주방 + 현관) ÷ (침실 + 드레스룸)"},
    "master_ratio": {"label": "안방/다른 침실 면적비", "domain": "area", "dir": "two", "method": "z", "w": 1,
                     "cites": ["zeng2025"], "grade": "B", "def": "가장 큰 침실 ÷ 나머지 침실 평균(침실 2개 이상)"},
    "rect_mbr": {"label": "실 직사각형도(회전 MBR)", "domain": "shape", "dir": "up", "method": "z", "w": 1,
                 "cites": ["rosin1999", "rodrigues2013"], "grade": "B",
                 "def": "거실·침실·주방 면적 ÷ 회전 최소 외접 사각형 면적, 면적 가중 평균"},
    "aspect_mbr": {"label": "실 종횡비", "domain": "shape", "dir": "down", "method": "z", "w": 1,
                   "cites": ["upasani2020", "zeng2025"], "grade": "B", "def": "거실·침실·주방 MBR 장변 ÷ 단변, 면적 가중 평균"},
    "narrow_bed": {"label": "가장 좁은 침실의 상대 폭", "domain": "shape", "dir": "up", "method": "z", "w": 1,
                   "cites": ["upasani2020", "rodrigues2013"], "grade": "B",
                   "def": "가장 좁은 침실의 MBR 단변 ÷ 시트 침실 한 변 중앙값"},
    "ext_ratio": {"label": "거주실 외기 접면비", "domain": "ext", "dir": "up", "method": "z", "w": 1,
                  "cites": ["ju2020", "zeng2025"], "grade": "B",
                  "def": "거실·침실·주방 둘레 중 세대 밖·발코니·실외기실로 열린 길이 ÷ 전체 둘레"},
    # 채점하지 않는 보조값
    "n_bed": {"label": "침실 수", "info": True}, "n_bath": {"label": "화장실 수", "info": True},
    "k_func": {"label": "기능실 수 K", "info": True}, "ringiness": {"label": "고리성(참고)", "info": True},
    "gz_living": {"label": "유전형 벡터 — 거실", "info": True}, "gz_kitchen": {"label": "유전형 벡터 — 주방", "info": True},
    "gz_entry": {"label": "유전형 벡터 — 현관", "info": True}, "gz_bed": {"label": "유전형 벡터 — 침실", "info": True},
    "gz_bath": {"label": "유전형 벡터 — 화장실", "info": True},
}
DOMAINS: dict[str, dict] = {
    "syntax": {"label": "공간구문", "param": "w_syntax"}, "area": {"label": "면적 구성", "param": "w_area"},
    "shape": {"label": "형태", "param": "w_shape"}, "ext": {"label": "외기 접면", "param": "w_ext"},
}
SCORED = [k for k, m in FEATURES.items() if m.get("domain")]
GENO = ("living", "kitchen", "entry", "bed", "bath")   # 한국 유전형 기준 순서(Choi et al. 2014, 복도 제외)


def _fin(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _sum(xs) -> float:
    """왼쪽부터 차례로 더한다 — 웹의 reduce와 같은 순서·같은 반올림."""
    s = 0
    for x in xs:
        s += x
    return s


def _mean(xs: list) -> float:
    return _sum(xs) / len(xs)


def _sq(x: float) -> float:
    """웹의 x ** 2 — V8은 x * x와 같지만 파이썬 float ** 2(윈도 C pow)는 1ulp 다를 때가 있다."""
    return x * x


def _poly_area(poly) -> float:
    a = 0
    for i in range(len(poly)):
        p, q = poly[i], poly[(i + 1) % len(poly)]
        a += p[0] * q[1] - q[0] * p[1]
    return abs(a) / 2


def _mbr(poly) -> tuple[float, float, float]:
    """회전 최소 외접 사각형 (넓이, 폭, 높이) — 볼록 껍질의 각 변 방향으로 돌려 가장 작은 사각형(Rosin 1999)."""
    P = sorted((p[0], p[1]) for p in poly)

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lo, up = [], []
    for p in P:
        while len(lo) >= 2 and cross(lo[-2], lo[-1], p) <= 0:
            lo.pop()
        lo.append(p)
    for p in reversed(P):
        while len(up) >= 2 and cross(up[-2], up[-1], p) <= 0:
            up.pop()
        up.append(p)
    H = lo[:-1] + up[:-1]
    best = None
    for i in range(len(H)):
        a, b = H[i], H[(i + 1) % len(H)]
        L = jsmath.hypot(b[0] - a[0], b[1] - a[1])
        if not L > 0:
            continue
        ux, uy = (b[0] - a[0]) / L, (b[1] - a[1]) / L
        x0, x1, y0, y1 = math.inf, -math.inf, math.inf, -math.inf
        for p in H:
            x, y = p[0] * ux + p[1] * uy, p[1] * ux - p[0] * uy
            x0, x1, y0, y1 = min(x0, x), max(x1, x), min(y0, y), max(y1, y)
        w, h = x1 - x0, y1 - y0
        if best is None or w * h < best[0]:
            best = (w * h, w, h)
    return best or (0.0, 0.0, 0.0)


def features(u: Unit, adj: dict[str, set[str]]) -> tuple[dict, dict]:
    """세대 → 정답지 비교용 특징(FEATURES)과 공간구문 결과."""
    g = syntax_graph(u, adj)
    res = analyze_graph(g)
    nodes, glob = res["nodes"], res["global"]
    sp, tot = u.spaces, u.area_px
    by = lambda kind: _sum(sp[k].area_px for k in u.of(kind))
    d0 = bfs_depths(g, CARRIER)
    beds = u.of("bed")
    E, V = glob["edge_count"], glob["node_count"]

    def int_of(k):
        n = nodes.get(k)
        return n["integration"] if n and _fin(n["integration"]) else None

    def mean_of(xs):
        v = [x for x in xs if _fin(x)]
        return _mean(v) if v else None

    def ratio(a, b):
        return a / b if _fin(a) and _fin(b) and b > 0 else None

    mi = {k: mean_of([int_of(s) for s in u.of(k)]) for k in GENO}

    # 유전형: 5유형이 모두 있을 때만(3유형 τ는 4개 값뿐이라 비교 불가)
    tau, gz = None, {"gz_" + k: None for k in GENO}
    if all(_fin(mi[k]) for k in GENO):
        xs = [mi[k] for k in GENO]
        C = D = tx = 0
        for i in range(5):
            for j in range(i + 1, 5):   # 기준 순서에서 i가 j보다 위
                dx = xs[i] - xs[j]
                if dx > 0:
                    C += 1
                elif dx < 0:
                    D += 1
                else:
                    tx += 1
        tau = (C - D) / math.sqrt((10 - tx) * 10) if tx < 10 else None
        m = _mean(xs)
        sd = math.sqrt(_sum(_sq(x - m) for x in xs) / len(xs))
        if sd > 0:
            for k, x in zip(GENO, xs):
                gz["gz_" + k] = (x - m) / sd

    def depth_of(kinds):
        return mean_of([d0[k] for kd in kinds for k in u.of(kd) if k in d0])

    priv_d, pub_d = depth_of(("bed", "dress")), depth_of(("living", "kitchen"))
    func = [k for k in adj if sp[k].kind != "etc"]
    living = [k for k in u.of("living") if k in nodes]

    # 형태(회전 MBR)·외기 접면 — 거실·침실·주방
    bed_areas = sorted((sp[b].area_px for b in beds), reverse=True)
    rw = rs = as_ = 0
    narrow, opened, perim = None, 0, 0
    for k, s in sp.items():
        if s.kind not in ("living", "bed", "kitchen"):
            continue
        pa = _poly_area(s.poly)
        area, w, h = _mbr(s.poly)
        lo, hi = min(w, h), max(w, h)
        if area > 0 and lo > 0:
            rw += pa
            rs += pa * (pa / area)
            as_ += pa * (hi / lo)
        if s.kind == "bed" and u.bed_side_px and u.bed_side_px > 0:
            r = lo / u.bed_side_px
            if narrow is None or r < narrow:
                narrow = r
        opened += _daylight_px(u, k)
        perim += (u.perimeter or {}).get(k) or 0

    f = {
        "n_bed": len(beds), "n_bath": len(u.of("bath")), "k_func": len(func),
        "ringiness": (E - V + 1) / max(1, 2 * V - 5),
        "int_ratio_lb": ratio(mi["living"], mi["bed"]), "int_ratio_kb": ratio(mi["kitchen"], mi["bed"]),
        "geno_tau": tau, **gz,
        "pp_depth": priv_d - pub_d if _fin(priv_d) and _fin(pub_d) else None,
        "int_func": mean_of([int_of(k) for k in func]),
        "control_living": mean_of([nodes[k]["control_value"] for k in living]),
        "r_living": by("living") / tot, "r_kitchen": by("kitchen") / tot, "r_bed": by("bed") / tot,
        "r_bath": by("bath") / tot, "r_balcony": by("balcony") / tot,
        "pub_priv": ratio(by("living") + by("kitchen") + by("entry"), by("bed") + by("dress")),
        "master_ratio": bed_areas[0] / _mean(bed_areas[1:]) if len(bed_areas) >= 2 else None,
        "rect_mbr": rs / rw if rw > 0 else None, "aspect_mbr": as_ / rw if rw > 0 else None,
        "narrow_bed": narrow,
        "ext_ratio": min(1, opened / perim) if perim > 0 else None,
    }
    return f, res


# ═══════════════════════════════════════════════ ③ 정답지(baseline)
def type_key(u: Unit) -> str:
    """평형 대용 — 축척이 없으므로 '침실 수-화장실 수' (예: 3R2B ≈ 84㎡형)."""
    return f"{len(u.of('bed'))}R{len(u.of('bath'))}B"


# Qn 강건 척도(Rousseeuw & Croux 1993): 2.2219 · d_n · {|xi − xj|; i<j}의 k번째 값, k = C(h,2), h = ⌊n/2⌋+1.
# k번째 쌍 차이는 정렬된 값에서 '차이 ≤ d인 쌍 수'를 두 포인터로 세며 이분 탐색으로 찾는다 — O(n log 범위).
# 웹 qnScale과 같은 반복·같은 종료 조건이라 같은 값이 나온다.
QN_DN = [0, 0, 0.399, 0.994, 0.512, 0.844, 0.611, 0.857, 0.669, 0.872]


def qn_scale(s: list[float]) -> float:
    """정렬된 값 → Qn."""
    n = len(s)
    if n < 2:
        return 0
    h = n // 2 + 1
    k = h * (h - 1) / 2

    def count(d):
        c = i = 0
        for j in range(1, n):
            while s[j] - s[i] > d:
                i += 1
            c += j - i
        return c

    if count(0) >= k:
        return 0
    lo, hi = 0, s[-1] - s[0]
    it = 0
    while it < 200 and hi - lo > 1e-12 * max(1, hi):
        mid = (lo + hi) / 2
        if count(mid) >= k:
            hi = mid
        else:
            lo = mid
        it += 1
    dn = QN_DN[n] if n <= 9 else (n / (n + 1.4) if n % 2 else n / (n + 3.8))
    return 2.2219 * dn * hi


def _js_round(x: float) -> int:
    """자바스크립트 Math.round — .5는 위로(파이썬 round는 짝수 쪽)."""
    return math.floor(x + 0.5)


def cdf_of(s: list[float]) -> dict:
    """경험적 누적분포 — 값이 300종 이하면 정확히([값, 그보다 작은 수, 같은 수]), 많으면 201개 분위수."""
    n, uniq = len(s), []
    for i, x in enumerate(s):
        if uniq and uniq[-1][0] == x:
            uniq[-1][2] += 1
        else:
            uniq.append([x, i, 1])
    if len(uniq) <= 300:
        return {"n": n, "exact": uniq}
    return {"n": n, "q": [s[_js_round(i / 200 * (n - 1))] for i in range(201)]}


def cdf_at(c: dict, v: float) -> float:
    """F(v), 같은 값은 절반으로 센다."""
    if c.get("exact") is not None:
        less = c["n"]
        for x, lt, eq in c["exact"]:
            if x == v:
                return (lt + eq / 2) / c["n"]
            if x > v:
                less = lt
                break
        return less / c["n"]
    q = c["q"]
    m = len(q) - 1
    if v < q[0]:
        return 0
    if v > q[m]:
        return 1
    a = 0
    while a < m and q[a] < v:          # 첫 q ≥ v
        a += 1
    b = a
    while b < m and q[b + 1] <= v:     # 마지막 q ≤ v
        b += 1
    if q[a] == v:
        return (a + b) / 2 / m
    return (a - 1 + (v - q[a - 1]) / (q[a] - q[a - 1])) / m


def _stats_of(xs: list[float], need_cdf: bool) -> dict | None:
    if len(xs) < 3:
        return None
    s = sorted(xs)
    qn = qn_scale(s)
    out = {"median": st.median(s), "qn": qn, "n": len(s), "min": s[0], "max": s[-1]}
    if need_cdf or not qn > 0:
        out["cdf"] = cdf_of(s)
    return out


def summarize_features(rs: list[dict]) -> dict:
    """특징 행 → 지표별 분포(중앙값·Qn·누적분포)."""
    out = {}
    for k in SCORED:
        if k in ("int_func", "geno_dist"):
            continue
        s = _stats_of([r[k] for r in rs if _fin(r.get(k))], FEATURES[k]["method"] == "pct")
        if s:
            out[k] = s
    # 기능실 평균 통합도: log K 회귀 잔차(D값 정규화의 K 의존성, Ostwald 2011)
    pr = [r for r in rs if _fin(r.get("int_func")) and _fin(r.get("k_func")) and r["k_func"] > 0]
    if len(pr) >= 3:
        xs = [jsmath.log(r["k_func"]) for r in pr]
        ys = [r["int_func"] for r in pr]
        mx, my = _mean(xs), _mean(ys)
        sxy = sxx = 0
        for x, y in zip(xs, ys):
            sxy += (x - mx) * (y - my)
            sxx += _sq(x - mx)
        b = sxy / sxx if sxx > 0 else 0
        a = my - b * mx
        s = _stats_of([y - (a + b * x) for x, y in zip(xs, ys)], False)
        if s:
            out["int_func"] = {**s, "a": a, "b": b}
    # 유전형 프로필: 성분별 중앙값 벡터 ĝ, 그 거리의 분포
    gs = [r for r in rs if all(_fin(r.get("gz_" + g)) for g in GENO)]
    if len(gs) >= 3:
        ghat = [st.median([r["gz_" + g] for r in gs]) for g in GENO]
        s = _stats_of([math.sqrt(_sum(_sq(r["gz_" + g] - ghat[i]) for i, g in enumerate(GENO))) for r in gs],
                      False)
        if s:
            out["geno_dist"] = {**s, "ghat": ghat}
    return out


def _bed_key(n) -> str:
    """층 키 — 웹의 객체 키(String(n_bed))와 같게."""
    return str(int(n)) if _fin(n) and float(n).is_integer() else str(n)


def build_baseline(rows: list[dict]) -> dict:
    """rows: [{unit, type, **features}] → 정답지. 침실 수로 층화(5세대 이상인 층만 저장, 쓸지는 채점 때 strata_min으로)."""
    by_bed: dict = {}
    by_type: dict[str, list[dict]] = {}
    for r in rows:
        if _fin(r.get("n_bed")):
            by_bed.setdefault(r["n_bed"], []).append(r)
        by_type.setdefault(r["type"], []).append(r)
    strata = {_bed_key(nb): {"n": len(rs), "features": summarize_features(rs)}
              for nb, rs in sorted(by_bed.items()) if len(rs) >= 5}
    return {
        "kind": "aihub-baseline", "version": 2, "n_units": len(rows),
        "all": summarize_features(rows),
        "strata": strata,
        "type_counts": dict(sorted(((t, len(rs)) for t, rs in by_type.items()), key=lambda x: -x[1])),
    }


def _score_feature(meta: dict, b: dict, v: float, z_cut: float) -> dict | None:
    qn = b.get("qn")
    if meta["method"] == "pct" or not (qn is not None and qn > 0):
        if not b.get("cdf"):
            return None
        F = cdf_at(b["cdf"], v)
        if meta["dir"] == "up":
            score = 100 * min(1, F / 0.5)
        elif meta["dir"] == "down":
            score = 100 * min(1, (1 - F) / 0.5)
        else:
            score = 100 * 2 * min(F, 1 - F)
        return {"z": None, "F": F, "score": score}
    z = (v - b["median"]) / qn
    zz = min(0, z) if meta["dir"] == "up" else max(0, z) if meta["dir"] == "down" else z
    return {"z": z, "F": None, "score": 100 * max(0, 1 - abs(zz) / z_cut)}


def _num(v) -> float:
    """웹의 `+x || 0` — 숫자로 못 읽으면 0."""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return 0
    return x if x == x else 0


def typicality(f: dict, baseline: dict, sp=None) -> dict | None:
    """정답지 근접도 0~100 — 지표 점수를 영역 안에서 가중 평균하고, 영역을 영역 가중치로 평균.
    같은 침실 수 층이 strata_min 세대 이상이면 그 층을, 아니면 전체 분포를 기준으로 한다."""
    if not baseline or baseline.get("version") != 2:
        return None
    sp = scoring_params(sp)
    stratum = (baseline.get("strata") or {}).get(_bed_key(f.get("n_bed")))
    use_st = bool(stratum and stratum["n"] >= sp["strata_min"])
    ref = stratum["features"] if use_st else baseline["all"]
    per = {}
    for k in SCORED:
        meta, b = FEATURES[k], ref.get(k)
        if not b:
            continue
        v = f.get(k)
        if k == "int_func":
            if not _fin(v) or not (_fin(f.get("k_func")) and f["k_func"] > 0):
                continue
            v -= b["a"] + b["b"] * jsmath.log(f["k_func"])
        if k == "geno_dist":
            if not all(_fin(f.get("gz_" + g)) for g in GENO):
                continue
            v = math.sqrt(_sum(_sq(f["gz_" + g] - b["ghat"][i]) for i, g in enumerate(GENO)))
        if not _fin(v):
            continue
        r = _score_feature(meta, b, v, sp["z_cut"])
        if not r:
            continue
        per[k] = {"value": v, "raw": f.get(k), "median": b["median"], "z": r["z"], "F": r["F"],
                  "score": r["score"], "w": meta["w"], "domain": meta["domain"]}
    domains, num, den = {}, 0, 0
    for d, D in DOMAINS.items():
        items = [x for x in per.values() if x["domain"] == d and x["w"] > 0]
        if not items:
            continue
        ws = _sum(x["w"] for x in items)
        score = _sum(x["w"] * x["score"] for x in items) / ws
        dw = _num(sp.get(D["param"]))
        domains[d] = {"score": score, "weight": dw, "n": len(items)}
        num += dw * score
        den += dw
    used = f"침실 {f.get('n_bed')}개 층 ({stratum['n']}세대)" if use_st else f"전체 ({baseline['n_units']}세대)"
    return {"reference": used, "score": num / den if den > 0 else float("nan"), "domains": domains, "features": per}


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
    typ = typicality(f, baseline, scoring_params(rules)) if baseline else None
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


def to_json(obj, ndigits: int | None = 4) -> str:
    """NaN·무한대는 null. ndigits=None이면 반올림하지 않는다(정답지 — 누적분포가 값의 같음을 본다)."""
    return json.dumps(_clean(obj, ndigits), ensure_ascii=False, indent=2)


def _clean(o, ndigits: int | None = 4):
    if isinstance(o, float):
        if o != o or o in (math.inf, -math.inf):
            return None
        return o if ndigits is None else round(o, ndigits)
    if isinstance(o, dict):
        return {str(k): _clean(v, ndigits) for k, v in o.items()}
    if isinstance(o, (list, tuple, set)):
        return [_clean(v, ndigits) for v in o]
    return o
