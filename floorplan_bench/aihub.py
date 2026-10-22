"""AI 허브 '건축 도면 데이터' 라벨(JSON) → 세대별 공간 그래프.

라벨은 COCO 형식이다. 한 장(images[0])에 여러 세대가 그려져 있고, 실은 픽셀 좌표 폴리곤이다.

    SPA  공간(거실·침실·주방·현관 …)      → 이 모듈의 주 입력
    STR  구조(벽체·출입문·창호)            → 문·창 정합성 검사에 쓴다
    OBJ  객체(변기·세면대·싱크대 …)        · OCR  실명 글자

주의: 샘플에서 SPA/STR/OBJ/OCR은 서로 다른 도면이다(파일 번호가 다르다).
그래서 SPA만으로는 문 위치를 모른다. 여기서는 **맞닿은 실(인접 그래프)** 에
**용도별 출입 규칙**을 얹어 투과성 그래프를 추정한다(PermeabilityRules).

픽셀→미터 축척은 라벨에 없고 시트마다 다르다(한 장에 1세대~8세대). 욕실·침실 넓이나
벽 두께로 추정해 보면 추정치끼리 2~4배 어긋난다. 그래서 **평가 지표는 모두 축척이 필요 없게**
(세대 면적 대비 비율·형태비·위상) 만들고, 판정 임계값(접면 길이 등)만 시트의 침실 중앙값을
9㎡로 놓고 잡은 대략의 축척(px_per_m)에 맞춘다. ㎡ 값은 참고용 추정치다.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import asdict, dataclass, field

# category_id → (키, 한글명)
SPACE_CATS: dict[int, tuple[str, str]] = {
    13: ("living", "거실"), 14: ("bed", "침실"), 15: ("kitchen", "주방"),
    16: ("entry", "현관"), 17: ("balcony", "발코니"), 18: ("bath", "화장실"),
    19: ("ac", "실외기실"), 20: ("dress", "드레스룸"), 22: ("etc", "기타"),
    1: ("multi", "다목적공간"),
}
CORE_CATS = {2: "엘리베이터홀", 3: "계단실", 23: "엘리베이터"}
STR_CATS = {9: "door", 10: "window", 11: "wall"}
OBJ_CATS = {4: "변기", 5: "세면대", 6: "싱크대", 7: "욕조", 8: "가스레인지"}

CIRCULATION = ("living", "etc", "multi", "kitchen", "entry")


# ═══════════════════════════════════════════════ 기하 (의존성 없이)
Pt = tuple[float, float]


def _pts(flat: list[float]) -> list[Pt]:
    return list(zip(flat[0::2], flat[1::2]))


def _edges(poly: list[Pt]):
    return zip(poly, poly[1:] + poly[:1])


def _seg_dist(p: Pt, a: Pt, b: Pt) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    L = dx * dx + dy * dy
    t = 0.0 if L == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L))
    return math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy)


def _poly_dist(p: Pt, poly: list[Pt]) -> float:
    return min(_seg_dist(p, a, b) for a, b in _edges(poly))


def _inside(p: Pt, poly: list[Pt]) -> bool:
    x, y, c = p[0], p[1], False
    for (x1, y1), (x2, y2) in _edges(poly):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            c = not c
    return c


def _boundary_samples(poly: list[Pt], step: float) -> list[Pt]:
    out = []
    for a, b in _edges(poly):
        n = max(1, int(math.hypot(b[0] - a[0], b[1] - a[1]) / step))
        out += [(a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n) for i in range(n)]
    return out


def _bbox_gap(a: tuple, b: tuple) -> float:
    dx = max(b[0] - (a[0] + a[2]), a[0] - (b[0] + b[2]), 0.0)
    dy = max(b[1] - (a[1] + a[3]), a[1] - (b[1] + b[3]), 0.0)
    return max(dx, dy)


# ═══════════════════════════════════════════════ 자료형
@dataclass
class Space:
    sid: str            # 세대 안에서 유일한 키 (living, bed1, bed2 …)
    kind: str           # SPACE_CATS 키
    name: str           # 한글명
    poly: list[Pt]
    area_px: float
    bbox: tuple[float, float, float, float]

    @property
    def centroid(self) -> Pt:
        """라벨 자리 — ㄱ자 실은 바운딩박스 중심이 실 밖이므로 안쪽에서 벽과 가장 먼 점(격자 탐색)."""
        x, y, w, h = self.bbox
        c = (x + w / 2, y + h / 2)
        best, bd = (c, _poly_dist(c, self.poly)) if _inside(c, self.poly) else (None, -1.0)
        n = 14
        for i in range(1, n):
            for j in range(1, n):
                p = (x + w * i / n, y + h * j / n)
                if not _inside(p, self.poly):
                    continue
                d = _poly_dist(p, self.poly)
                if d > bd * 1.15:   # 중심을 조금 더 선호
                    best, bd = p, d
        return best or c


@dataclass
class Unit:
    """단위세대 하나."""
    source: str                       # 원본 파일명
    index: int                        # 시트 안에서 몇 번째 세대
    spaces: dict[str, Space]
    contact: dict[tuple[str, str], float]   # 맞닿은 실 쌍 → 접면 길이(px)
    exterior: dict[str, float]               # 실 → 외기(다른 실·코어가 없는 쪽) 접면 길이(px)
    px_per_m: float
    dropped: list[str] = field(default_factory=list)   # 샤프트 등으로 제외한 소형 실
    contact_mid: dict[tuple[str, str], Pt] = field(default_factory=dict)  # 접면 중앙 — 문을 그릴 자리
    options: dict = field(default_factory=dict)        # 이 세대를 읽을 때 쓴 LoadOptions

    @property
    def uid(self) -> str:
        return f"{os.path.splitext(self.source)[0]}#{self.index}"

    @property
    def area_px(self) -> float:
        return sum(s.area_px for s in self.spaces.values())

    def area_m2(self, sid: str | None = None) -> float:
        a = self.spaces[sid].area_px if sid else self.area_px
        return a / self.px_per_m ** 2

    def of(self, kind: str) -> list[str]:
        return [k for k, s in self.spaces.items() if s.kind == kind]

    def neighbors(self, sid: str) -> list[str]:
        return [b if a == sid else a for (a, b) in self.contact if sid in (a, b)]


@dataclass(frozen=True)
class LoadOptions:
    px_per_m: float | None = None
    """축척(px/m). None이면 시트의 침실 넓이 중앙값을 ref_bed_m2로 보고 추정한다."""
    ref_bed_m2: float = 9.0
    wall_tol_px: float = 32.0
    """이 거리 안이면 벽 하나를 사이에 두고 맞닿은 것으로 본다(벽 두께 분포의 골짜기)."""
    min_contact_m: float = 0.6
    """맞닿았다고 보려면 접면이 이만큼은 길어야 한다(모서리 접촉 제외)."""
    min_space_ratio: float = 0.012
    """세대 면적 대비 이보다 작은 '기타' 실은 샤프트(PS·AD)로 보고 뺀다."""
    orphan_reach_m: float = 2.0
    """현관 없는 실 덩어리를 이 거리 안의 세대에 붙인다(고립 실 검출용)."""
    sample_step_px: float = 6.0

    def as_dict(self) -> dict:
        return asdict(self)


# ═══════════════════════════════════════════════ 읽기
def read_coco(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def label_type(data: dict, path: str = "") -> str:
    """SPA / STR / OBJ / OCR — 파일명이 우선, 없으면 카테고리 구성으로."""
    base = os.path.basename(path).upper()
    for t in ("SPA", "STR", "OBJ", "OCR"):
        if f"_{t}_" in base:
            return t
    cats = {a["category_id"] for a in data.get("annotations", [])}
    if cats & set(SPACE_CATS):
        return "SPA"
    if cats & set(STR_CATS):
        return "STR"
    if cats & set(OBJ_CATS):
        return "OBJ"
    return "OCR"


def _contact(pa: list[Pt], pb: list[Pt], bb_a, bb_b, opt: LoadOptions) -> tuple[float, Pt | None]:
    """접면 길이(px)와 접면 중앙점."""
    if _bbox_gap(bb_a, bb_b) > opt.wall_tol_px:
        return 0.0, None
    # 양쪽에서 잰 접면 길이 중 짧은 쪽 — 큰 실의 긴 변이 작은 실 하나에 붙는 과대평가 방지
    sa = [p for p in _boundary_samples(pa, opt.sample_step_px) if _poly_dist(p, pb) <= opt.wall_tol_px]
    sb = [p for p in _boundary_samples(pb, opt.sample_step_px) if _poly_dist(p, pa) <= opt.wall_tol_px]
    if not sa or not sb:
        return 0.0, None
    pts = sa + sb
    mid = (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
    # 중앙점이 ㄱ자 접면의 안쪽 허공에 떨어지면 가장 가까운 실제 표본점으로
    mid = min(pts, key=lambda p: math.hypot(p[0] - mid[0], p[1] - mid[1]))
    return min(len(sa), len(sb)) * opt.sample_step_px, mid


def load_units(path: str, opt: LoadOptions = LoadOptions()) -> list[Unit]:
    """SPA 라벨 한 장 → 단위세대 목록."""
    data = read_coco(path)
    raw, core = [], []
    for a in data["annotations"]:
        cid = a["category_id"]
        if not a.get("segmentation") or not a["segmentation"][0]:
            continue
        poly = _pts(a["segmentation"][0])
        if len(poly) < 3:
            continue
        item = (cid, poly, float(a["area"]), tuple(a["bbox"]))
        if cid in SPACE_CATS:
            raw.append(item)
        elif cid in CORE_CATS:
            core.append(item)

    if opt.px_per_m is None:
        beds = sorted(r[2] for r in raw if SPACE_CATS[r[0]][0] == "bed")
        ppm = math.sqrt(beds[len(beds) // 2] / opt.ref_bed_m2) if beds else 100.0
        opt = LoadOptions(**{**opt.as_dict(), "px_per_m": ppm})

    n = len(raw)
    min_contact = opt.min_contact_m * opt.px_per_m
    contact: dict[tuple[int, int], float] = {}
    mids: dict[tuple[int, int], Pt] = {}
    for i in range(n):
        for j in range(i + 1, n):
            L, mid = _contact(raw[i][1], raw[j][1], raw[i][3], raw[j][3], opt)
            if L >= min_contact:
                contact[(i, j)] = L
                mids[(i, j)] = mid

    # 세대 나누기: 인접 그래프의 연결 요소 → 현관이 둘 이상이면 현관 기준 그래프 보로노이
    adj = {i: set() for i in range(n)}
    for i, j in contact:
        adj[i].add(j)
        adj[j].add(i)
    owner = _split_by_entry(raw, adj)

    units = []
    groups: dict[int, list[int]] = {}
    for i in sorted(owner):   # 라벨 순서로 — 탐색 순서에 따라 실 번호가 바뀌지 않게
        groups.setdefault(owner[i], []).append(i)
    entry_cid = next(c for c, (k, _) in SPACE_CATS.items() if k == "entry")
    order = sorted(groups.values(), key=lambda g: (min(raw[i][3][0] for i in g), min(raw[i][3][1] for i in g)))
    is_home = [any(raw[i][0] == entry_cid for i in g) for g in order]
    homes = [list(g) for g, h in zip(order, is_home) if h]
    # 현관 없는 조각: 어느 세대와 orphan_reach_m 안에 있으면 그 세대에 붙인다(→ 출입 불가 실로 걸림).
    # 더 멀면 공용부 잔여·다른 그림으로 보고 버린다.
    for g, h in zip(order, is_home):
        if h or not homes:
            continue
        gap, home = min((min(_bbox_gap(raw[i][3], raw[j][3]) for i in g for j in h), hi)
                        for hi, h in enumerate(homes))
        if gap <= opt.orphan_reach_m * opt.px_per_m:
            homes[home] = homes[home] + g
    for gi, members in enumerate(homes):
        units.append(_make_unit(path, gi, members, raw, core, contact, mids, opt))
    for k, u in enumerate(units):
        u.index = k
    return units


def _split_by_entry(raw, adj) -> dict[int, int]:
    entry_cid = next(c for c, (k, _) in SPACE_CATS.items() if k == "entry")
    owner: dict[int, int] = {}
    seen: set[int] = set()
    comp_id = 0
    for s in range(len(raw)):
        if s in seen:
            continue
        comp, stack = [], [s]
        seen.add(s)
        while stack:
            v = stack.pop()
            comp.append(v)
            for u in adj[v]:
                if u not in seen:
                    seen.add(u)
                    stack.append(u)
        entries = [i for i in comp if raw[i][0] == entry_cid]
        if len(entries) <= 1:
            for i in comp:
                owner[i] = comp_id
            comp_id += 1
            continue
        # 다중 출발 BFS — 가장 가까운 현관의 세대로. 동률이면 무게중심이 가까운 쪽.
        dist = {i: {} for i in comp}
        for e in entries:
            d, q = {e: 0}, [e]
            while q:
                nq = []
                for v in q:
                    for u in adj[v]:
                        if u not in d:
                            d[u] = d[v] + 1
                            nq.append(u)
                q = nq
            for i, k in d.items():
                dist[i][e] = k

        def cdist(i, e):
            (x1, y1, w1, h1), (x2, y2, w2, h2) = raw[i][3], raw[e][3]
            return math.hypot(x1 + w1 / 2 - x2 - w2 / 2, y1 + h1 / 2 - y2 - h2 / 2)

        for i in comp:
            best = min(entries, key=lambda e: (dist[i].get(e, 1e9), cdist(i, e)))
            owner[i] = comp_id + entries.index(best)
        comp_id += len(entries)
    return owner


def _make_unit(path, gi, members, raw, core, contact, mids, opt) -> Unit:
    total = sum(raw[i][2] for i in members)
    keep, dropped = [], []
    for i in members:
        cid, _, area, _ = raw[i]
        if SPACE_CATS[cid][0] == "etc" and area < opt.min_space_ratio * total:
            dropped.append(i)
        else:
            keep.append(i)

    # 실 키 부여: 같은 용도가 여럿이면 넓은 순으로 1,2,3…
    by_kind: dict[str, list[int]] = {}
    for i in keep:
        by_kind.setdefault(SPACE_CATS[raw[i][0]][0], []).append(i)
    sid_of: dict[int, str] = {}
    for kind, idx in by_kind.items():
        idx.sort(key=lambda i: -raw[i][2])
        for r, i in enumerate(idx, 1):
            sid_of[i] = kind if len(idx) == 1 else f"{kind}{r}"

    spaces = {sid_of[i]: Space(sid_of[i], SPACE_CATS[raw[i][0]][0], SPACE_CATS[raw[i][0]][1]
                               + ("" if sid_of[i] == SPACE_CATS[raw[i][0]][0] else sid_of[i][len(SPACE_CATS[raw[i][0]][0]):]),
                               raw[i][1], raw[i][2], raw[i][3]) for i in keep}
    con = {tuple(sorted((sid_of[i], sid_of[j]))): L for (i, j), L in contact.items()
           if i in sid_of and j in sid_of}
    con_mid = {tuple(sorted((sid_of[i], sid_of[j]))): mids[(i, j)] for (i, j) in contact
               if i in sid_of and j in sid_of}

    # 외기 접면: 경계 표본 중 세대 내 다른 실·샤프트·코어 어느 것에도 벽 하나 거리로 닿지 않는 것
    others = [raw[i][1] for i in members] + [c[1] for c in core]
    exterior = {}
    for i in keep:
        poly, bb = raw[i][1], raw[i][3]
        near = [q for q, j in zip(others, list(members) + [None] * len(core))
                if j != i and _bbox_gap(bb, _bb(q)) <= opt.wall_tol_px]
        free = sum(1 for p in _boundary_samples(poly, opt.sample_step_px)
                   if all(_poly_dist(p, q) > opt.wall_tol_px for q in near))
        exterior[sid_of[i]] = free * opt.sample_step_px

    return Unit(os.path.basename(path), gi, spaces, con, exterior, opt.px_per_m,
                dropped=[f"{SPACE_CATS[raw[i][0]][1]}({raw[i][2] / opt.px_per_m ** 2:.1f}㎡)" for i in dropped],
                contact_mid=con_mid, options=opt.as_dict())


def _bb(poly: list[Pt]) -> tuple[float, float, float, float]:
    xs, ys = [p[0] for p in poly], [p[1] for p in poly]
    return (min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))


# ═══════════════════════════════════════════════ STR: 문·창·벽
@dataclass
class StructSheet:
    source: str
    doors: list[dict]
    windows: list[dict]
    walls: list[dict]


def load_struct(path: str) -> StructSheet:
    data = read_coco(path)
    out = {"door": [], "window": [], "wall": []}
    for a in data["annotations"]:
        kind = STR_CATS.get(a["category_id"])
        if not kind:
            continue
        attrs = {k: v for k, v in a.get("attributes", {}).items() if k not in ("occluded", "rotation")}
        out[kind].append({"id": a["id"], "bbox": tuple(a["bbox"]),
                          "poly": _pts(a["segmentation"][0]) if a.get("segmentation") else [],
                          "type": next(iter(attrs.values()), "")})
    return StructSheet(os.path.basename(path), out["door"], out["window"], out["wall"])
