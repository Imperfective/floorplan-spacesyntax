"""평가 구조를 사용자가 정한다 — 조건(criterion)을 넣고 빼고, 점수에 어떻게 반영할지 고른다.

웹 스튜디오(docs/aihub.html)와 같은 문법·같은 JSON을 쓴다. 웹에서 만든 설정 파일을
그대로 `aihub_eval.py score --config 설정.json` 으로 돌릴 수 있다.

조건 한 줄
    대상.지표  연산자  값  [.. 최악값 | ± 허용치]  [w=가중치]  [as=반영방식]  [agg=worst|mean]

    대상    실 용도(living bed master kitchen entry bath balcony dress ac etc multi) 또는 전역 @
    연산자  <= 작을수록 좋음 · >= 클수록 좋음 · == 목표값 ±허용치
    반영방식
        as=weight         (기본) 가중 평균에 들어간다      조건점수 0~1 × 가중치
        as=penalty:25     못 맞춘 만큼 총점에서 뺀다        25 × (1 − 조건점수)
        as=gate           못 맞추면 총점 0 (필수 조건)

    '..'·'±'를 생략하면 weight는 지표의 기본 폭(span)을, penalty·gate는 '맞으면 1 아니면 0'을 쓴다.

총점
    기본점 = Σ(가중치 × 조건점수) / Σ가중치 × 100      (weight 조건이 없으면 100)
    총점   = 기본점 − Σ감점,  gate를 하나라도 못 맞추면 0
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field

# ═══════════════════════════════════════════════ 지표 목록 (웹과 공유)
MEASURES: dict[str, dict] = {
    # ── 전역: 시공 가능성 (개수 — 0이어야 정상)
    "missing_required":  {"label": "필수실 누락 수", "scope": "global", "span": 1,
                          "hint": "현관 1·거실·주방·침실·화장실 중 빠진 것 (F1)"},
    "overlap_pairs":     {"label": "겹친 실 쌍", "scope": "global", "span": 1,
                          "hint": "넓이가 겹치는 실 쌍 (F2)"},
    "unreachable_rooms": {"label": "출입 불가 주요실", "scope": "global", "span": 1,
                          "hint": "현관에서 닿지 않는 거실·침실·주방·화장실·드레스룸 (F3)"},
    "bed_via_bed":       {"label": "침실 경유 침실", "scope": "global", "span": 1,
                          "hint": "다른 침실을 거쳐야만 들어가는 침실 (F4)"},
    "kitchen_bath":      {"label": "주방-화장실 직결", "scope": "global", "span": 1,
                          "hint": "주방에서 바로 화장실로 (F5)"},
    "unlit_rooms":       {"label": "채광 불가 거실·침실", "scope": "global", "span": 1,
                          "hint": "외기·발코니에 면하지 않은 거실·침실 (F6)"},
    "door_window_overlaps": {"label": "문·창 겹침", "scope": "global", "span": 1,
                          "hint": "STR 라벨에서 문과 창이 겹친 곳 (F8). SPA만 있으면 건너뜀"},
    # ── 전역: 구성·공간구문
    "n_bed":             {"label": "침실 수", "scope": "global", "span": 2, "hint": ""},
    "n_bath":            {"label": "화장실 수", "scope": "global", "span": 1, "hint": ""},
    "n_spaces":          {"label": "실 수", "scope": "global", "span": 4, "hint": "그래프 노드 수(외부 제외)"},
    "mean_depth_system": {"label": "시스템 평균깊이", "scope": "global", "span": 1.6,
                          "hint": "모든 실 쌍의 평균 이동 횟수. 낮을수록 얕다."},
    "max_depth_from_carrier": {"label": "외부→최대깊이", "scope": "global", "span": 3,
                          "hint": "외부에서 가장 깊은 실까지 문을 몇 번 지나는가."},
    "mean_integration":  {"label": "평균 통합도", "scope": "global", "span": 1.5, "hint": ""},
    "intelligibility":   {"label": "명료성 r²", "scope": "global", "span": .6,
                          "hint": "연결도와 통합도의 상관. 길찾기 쉬움."},
    "ringiness":         {"label": "고리성", "scope": "global", "span": .2,
                          "hint": "순환 동선의 비율. 0이면 나무 구조."},
    "typicality":        {"label": "정답지 근접도", "scope": "global", "span": 40,
                          "hint": "AI 허브 실제 도면 분포 대비 0~100. 정답지를 불러와야 계산된다."},
    # ── 실 단위
    "area_ratio":        {"label": "세대 대비 면적비", "scope": "room", "span": .05, "hint": "축척 무관"},
    "est_m2":            {"label": "면적(㎡, 추정)", "scope": "room", "span": 4, "hint": "축척 추정치 — 참고용"},
    "aspect":            {"label": "장단변비", "scope": "room", "span": 1.5, "hint": "바운딩박스 긴 변 / 짧은 변"},
    "fill":              {"label": "충전율", "scope": "room", "span": .25,
                          "hint": "실 넓이 / 바운딩박스 넓이. 낮으면 많이 꺾인 형태"},
    "daylight_m":        {"label": "외기·발코니 접면(m)", "scope": "room", "span": 2, "hint": "창을 둘 수 있는 길이"},
    "step_depth":        {"label": "외부→깊이", "scope": "room", "span": 3, "hint": "외부에서 이 실까지 문을 몇 번"},
    "integration":       {"label": "통합도", "scope": "room", "span": 2, "hint": "1/RRA. 클수록 중심"},
    "integration_rank":  {"label": "통합도 순위", "scope": "room", "span": 4, "hint": "1이면 가장 통합적"},
    "RRA":               {"label": "RRA", "scope": "room", "span": .5, "hint": "작을수록 통합적"},
    "mean_depth":        {"label": "평균깊이", "scope": "room", "span": 1.2, "hint": ""},
    "connectivity":      {"label": "연결도", "scope": "room", "span": 3, "hint": "이 실에 난 문의 수(추정)"},
    "control_value":     {"label": "제어값", "scope": "room", "span": 1.2, "hint": ""},
    "choice":            {"label": "선택도", "scope": "room", "span": .3, "hint": "최단 경로 통과 빈도"},
}

TARGETS: dict[str, str] = {
    "living": "거실", "bed": "침실(모두)", "master": "안방(가장 큰 침실)", "kitchen": "주방",
    "entry": "현관", "bath": "화장실", "balcony": "발코니", "dress": "드레스룸",
    "ac": "실외기실", "etc": "기타", "multi": "다목적공간",
}
EFFECTS = ("weight", "penalty", "gate")


@dataclass
class Criterion:
    measure: str
    scope: str = "global"
    room: str | None = None
    mode: str = "range"            # range(best↔worst) | target(±tol) | pass(op·value 이진)
    best: float | None = None
    worst: float | None = None
    target: float | None = None
    tol: float | None = None
    op: str | None = None          # pass 모드의 <= / >=
    value: float | None = None
    effect: str = "weight"         # weight | penalty | gate
    weight: float = 1.0
    penalty: float = 0.0
    agg: str = "worst"             # 같은 용도 실이 여럿일 때 worst | mean
    enabled: bool = True
    why: str = ""

    def as_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}

    @classmethod
    def from_dict(cls, d: dict) -> "Criterion":
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in d.items() if k in known})


# ═══════════════════════════════════════════════ 문법 ↔ 조건
_LINE = re.compile(
    r"^(?P<tgt>[A-Za-z0-9_@]+)\s*\.?\s*(?P<ms>[A-Za-z0-9_]*)\s*(?P<op><=|>=|==)\s*(?P<v>-?[\d.]+)"
    r"\s*(?:(?P<sep>\.\.|±|\+-)\s*(?P<v2>-?[\d.]+))?(?P<opts>(?:\s+[a-z]+\s*=\s*[\w.:]+)*)\s*$")


def parse_dsl(text: str) -> tuple[list[Criterion], list[str]]:
    out, errors = [], []
    for ln, raw in enumerate(text.splitlines(), 1):
        why = raw.split("#", 1)[1].strip() if "#" in raw else ""
        body = raw.split("#", 1)[0].strip()
        enabled = True
        if not body and raw.lstrip().startswith("#!"):
            # '#! ...' 는 꺼 둔 조건
            body, enabled, why = raw.lstrip()[2:].split("#", 1)[0].strip(), False, ""
        if not body:
            continue
        m = _LINE.match(body)
        if not m:
            errors.append(f"{ln}행: 해석 불가 — {raw.strip()!r}")
            continue
        tgt, ms, op, v, sep, v2 = (m["tgt"], m["ms"], m["op"], float(m["v"]), m["sep"],
                                   float(m["v2"]) if m["v2"] else None)
        if tgt.startswith("@"):
            ms, tgt = ms or tgt[1:], "@"
        meta = MEASURES.get(ms)
        if not meta:
            errors.append(f"{ln}행: 알 수 없는 지표 {ms!r}")
            continue
        if meta["scope"] == "room" and tgt == "@":
            errors.append(f"{ln}행: {ms}는 실 단위 지표입니다 (예: bed.{ms})")
            continue
        if meta["scope"] == "global" and tgt != "@":
            errors.append(f"{ln}행: {ms}는 전역 지표입니다 (@{ms})")
            continue
        if meta["scope"] == "room" and tgt not in TARGETS:
            errors.append(f"{ln}행: 알 수 없는 대상 {tgt!r} ({', '.join(TARGETS)})")
            continue
        opts = dict(re.findall(r"([a-z]+)\s*=\s*([\w.:]+)", m["opts"] or ""))
        eff, pen = opts.get("as", "weight"), 0.0
        if eff.startswith("penalty"):
            eff, pen = "penalty", float(eff.split(":", 1)[1]) if ":" in eff else 10.0
        if eff not in EFFECTS:
            errors.append(f"{ln}행: 반영방식은 weight · penalty:점수 · gate 중 하나")
            continue
        c = Criterion(measure=ms, scope=meta["scope"], room=None if tgt == "@" else tgt,
                      effect=eff, penalty=pen, weight=float(opts.get("w", 1)),
                      agg=opts.get("agg", "worst"), enabled=enabled, why=why or meta["hint"])
        span = meta["span"]
        if op == "==":
            c.mode, c.target, c.tol = "target", v, v2 if v2 is not None else span / 3
        elif v2 is None and eff != "weight":
            c.mode, c.op, c.value = "pass", op, v
        else:
            c.mode, c.best = "range", v
            c.worst = v2 if v2 is not None else (v + span if op == "<=" else v - span)
        out.append(c)
    return out, errors


def to_dsl(cs: list[Criterion]) -> str:
    lines = []
    for c in cs:
        t = f"{c.room}.{c.measure}" if c.scope == "room" else f"@{c.measure}"
        if c.mode == "target":
            body = f"{t} == {_n(c.target)} ± {_n(c.tol)}"
        elif c.mode == "pass":
            body = f"{t} {c.op} {_n(c.value)}"
        else:
            body = f"{t} {'<=' if c.worst > c.best else '>='} {_n(c.best)} .. {_n(c.worst)}"
        if c.effect == "weight" and c.weight != 1:
            body += f" w={_n(c.weight)}"
        if c.effect == "penalty":
            body += f" as=penalty:{_n(c.penalty)}"
        if c.effect == "gate":
            body += " as=gate"
        if c.agg != "worst":
            body += f" agg={c.agg}"
        line = ("#! " if not c.enabled else "") + body
        if c.why and c.enabled:
            line += f"   # {c.why}"
        lines.append(line)
    return "\n".join(lines)


def _n(x) -> str:
    return f"{x:g}"


# ═══════════════════════════════════════════════ 기본 조건 세트
PRESETS: dict[str, str] = {
    "시공가능성 + 공간구문": """\
@missing_required    <= 0          as=gate         # 필수실(현관·거실·주방·침실·화장실)
@overlap_pairs       <= 0          as=penalty:25   # 실끼리 겹치면 지을 수 없다
@unreachable_rooms   <= 0          as=penalty:25   # 현관에서 닿지 않는 주요실
@door_window_overlaps <= 0         as=penalty:25   # 문과 창이 겹침(STR)
@bed_via_bed         <= 0          as=penalty:5    # 침실을 거쳐 들어가는 침실
@kitchen_bath        <= 0          as=penalty:5    # 주방에서 바로 화장실
@unlit_rooms         <= 0          as=penalty:5    # 창 둘 자리 없는 거실·침실
bed.aspect           <= 2.5        as=penalty:5    # 지나치게 길쭉한 침실
bed.fill             >= 0.6        as=penalty:5    # 지나치게 꺾인 침실
living.integration_rank <= 1 .. 4  w=2             # 거실이 가장 통합된 공간
entry.step_depth     <= 1 .. 3     w=1             # 현관은 외부에서 바로
master.step_depth    == 3 ± 1.5    w=1.5           # 안방은 현관에서 물러나게
@typicality          >= 90 .. 40   w=3             # 정답지(AI 허브) 분포에 가까울수록
""",
    "시공가능성만": """\
@missing_required    <= 0          as=gate
@overlap_pairs       <= 0          as=gate
@unreachable_rooms   <= 0          as=gate
@door_window_overlaps <= 0         as=gate
@bed_via_bed         <= 0          as=penalty:10
@kitchen_bath        <= 0          as=penalty:10
@unlit_rooms         <= 0          as=penalty:10
""",
    "정답지 근접도 중심": """\
@missing_required    <= 0          as=gate
@unreachable_rooms   <= 0          as=gate
@typicality          >= 95 .. 50   w=5
living.area_ratio    >= 0.22 .. 0.12 w=1
master.daylight_m    >= 3 .. 0.5   w=1
""",
}
DEFAULT_PRESET = "시공가능성 + 공간구문"


def preset(name: str = DEFAULT_PRESET) -> list[Criterion]:
    cs, errs = parse_dsl(PRESETS[name])
    assert not errs, errs
    return cs


# ═══════════════════════════════════════════════ 채점
def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def score_value(c: Criterion, v: float | None) -> float | None:
    if v is None or v != v:
        return None
    if c.mode == "target":
        return _clamp(1 - abs(v - c.target) / max(c.tol or 0, 1e-9))
    if c.mode == "pass":
        return 1.0 if (v <= c.value if c.op == "<=" else v >= c.value) else 0.0
    return _clamp((v - c.worst) / ((c.best - c.worst) or 1e-9))


def room_ids(target: str, rooms: dict[str, dict]) -> list[str]:
    if target == "master":
        beds = [k for k, r in rooms.items() if r["kind"] == "bed"]
        return [max(beds, key=lambda k: rooms[k]["area_ratio"])] if beds else []
    return [k for k, r in rooms.items() if r["kind"] == target]


def score_criterion(c: Criterion, m: dict) -> dict:
    if c.scope == "global":
        v = m["global"].get(c.measure)
        return {"value": v, "score": score_value(c, v), "room": None}
    ids = room_ids(c.room, m["rooms"])
    vals = [(k, m["rooms"][k].get(c.measure)) for k in ids]
    scored = [(k, v, score_value(c, v)) for k, v in vals]
    scored = [x for x in scored if x[2] is not None]
    if not scored:
        return {"value": None, "score": None, "room": None, "note": "해당 실 없음" if not ids else "값 없음"}
    if c.agg == "mean":
        return {"value": sum(x[1] for x in scored) / len(scored),
                "score": sum(x[2] for x in scored) / len(scored), "room": None}
    k, v, s = min(scored, key=lambda x: x[2])
    return {"value": v, "score": s, "room": k}


def score_all(cs: list[Criterion], m: dict) -> dict:
    rows = []
    for c in cs:
        if not c.enabled:
            continue
        rows.append({"criterion": c.as_dict(), **score_criterion(c, m)})
    wrows = [r for r in rows if r["criterion"]["effect"] == "weight" and r["score"] is not None]
    wsum = sum(r["criterion"]["weight"] for r in wrows)
    base = (sum(r["criterion"]["weight"] * r["score"] for r in wrows) / wsum * 100) if wsum else 100.0
    penalty = 0.0
    gated = []
    for r in rows:
        c, s = r["criterion"], r["score"]
        if s is None:
            continue
        if c["effect"] == "penalty":
            r["deduct"] = c["penalty"] * (1 - s)
            penalty += r["deduct"]
        elif c["effect"] == "gate" and s < 1:
            gated.append(r)
    total = 0.0 if gated else max(0.0, base - penalty)
    return {"base": base, "penalty": penalty, "gated": len(gated), "total": total,
            "grade": grade(total), "rows": rows,
            "skipped": sum(r["score"] is None for r in rows)}


def grade(t: float) -> str:
    for g, lim in (("A+", 95), ("A", 90), ("B+", 85), ("B", 80), ("C+", 70), ("C", 60), ("D", 45)):
        if t >= lim:
            return g
    return "F"


# ═══════════════════════════════════════════════ 설정 파일 (웹과 공유)
@dataclass
class Config:
    params: dict = field(default_factory=dict)
    criteria: list[Criterion] = field(default_factory=preset)

    def as_dict(self) -> dict:
        return {"version": 1, "params": self.params, "criteria": [c.as_dict() for c in self.criteria],
                "dsl": to_dsl(self.criteria)}


def load_config(path: str | None) -> Config:
    """JSON(웹에서 내보낸 설정) 또는 조건 문법 텍스트 파일."""
    if not path:
        return Config()
    with open(path, encoding="utf-8") as f:
        text = f.read()
    if path.lower().endswith(".json"):
        d = json.loads(text)
        cs = [Criterion.from_dict(c) for c in d.get("criteria", [])]
        if not cs and d.get("dsl"):
            cs, errs = parse_dsl(d["dsl"])
            if errs:
                raise SystemExit("\n".join(errs))
        return Config(params=d.get("params", {}), criteria=cs)
    cs, errs = parse_dsl(text)
    if errs:
        raise SystemExit("\n".join(errs))
    return Config(criteria=cs)
