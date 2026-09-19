"""Space Syntax 분석 — 도면을 '위상 공간의 좌표'로 옮긴다.

Hillier & Hanson, *The Social Logic of Space*(1984)의 공간구문론을 격자 평면도에
적용한다. 핵심 발상은 평면을 실측 거리(metric)가 아니라 **연결 관계(topology)**로
다시 좌표화하는 것이다.

이 모듈이 뽑아내는 세 벌의 좌표:
  1) 실측 좌표  metric   — 각 실의 중심점·바운딩박스 (기존 2단계 산출물)
  2) 위상 좌표  syntactic — 정당화 그래프(j-graph)의 (깊이, 가로위치)
  3) 시각 좌표  visual    — VGA(가시성 그래프 분석)의 셀별 시각 통합도

무엇을 '연결'로 볼 것인지는 SyntaxRules가 정한다. 같은 도면이라도 규칙이 바뀌면
위상 좌표가 달라진다 — 그것이 이 프로그램의 입력이다.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

from .plan import FloorPlan
from .spec import BuildingSpec

CARRIER = "__carrier__"


# ═══════════════════════════════════════════════ 규칙 (프로그램의 입력)
@dataclass(frozen=True)
class SyntaxRules:
    """무엇을 공간으로 보고 무엇을 연결로 볼 것인가."""

    # ── 투과성(permeability): 두 실이 이어졌다고 볼 조건 ──────────────
    door_min_cells: int = 1
    """두 실이 연결되려면 최소 몇 칸의 벽을 맞대야 하는가.
    1 = 한 칸만 닿아도 문을 놓을 수 있다고 본다. 2 이상이면 좁은 접면은 무시한다."""

    door_width_cells: int = 1
    """문 하나의 폭(칸). 시선 계산에서 이만큼만 뚫린 것으로 본다."""

    door_position: str = "center"
    """문을 접면의 어디에 놓는가. center | first | last"""

    # ── 외부(carrier) 노드 ────────────────────────────────────────
    include_carrier: bool = True
    """외부 공간을 노드로 포함한다. 공간구문론의 표준 관행."""

    carrier_mode: str = "entrance"
    """외부와 이어지는 실을 정하는 규칙.
    entrance = 현관 셀이 속한 실만 | perimeter = 외벽에 닿은 모든 실"""

    # ── 정규화 ────────────────────────────────────────────────────
    normalize: str = "rra"
    """통합도를 무엇으로 정규화할 것인가. ra = 상대 비대칭성 | rra = 실규모 보정"""

    # ── 시각 그래프(VGA) ─────────────────────────────────────────
    vga_enabled: bool = True
    vga_step: float = 0.04
    """시선 판정 샘플 간격(칸 단위). 작을수록 정확하고 느리다."""

    def as_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "SyntaxRules":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


DEFAULT_RULES = SyntaxRules()

PRESET_RULES: dict[str, SyntaxRules] = {
    "standard": SyntaxRules(),
    "strict_door": SyntaxRules(door_min_cells=2, door_width_cells=1),
    "open_plan": SyntaxRules(door_min_cells=1, door_width_cells=3),
    "multi_entry": SyntaxRules(carrier_mode="perimeter"),
    "no_carrier": SyntaxRules(include_carrier=False),
}


# ═══════════════════════════════════════════════ 벽·문 추출
@dataclass
class WallRun:
    """두 실 사이의 연속된 접면 한 구간."""

    room_a: str
    room_b: str
    orient: str  # "V" 세로벽 | "H" 가로벽
    fixed: int  # 세로벽이면 x, 가로벽이면 y
    start: int  # 구간 시작(세로벽이면 y, 가로벽이면 x)
    length: int
    edges: list[tuple[int, int]] = field(default_factory=list)  # 이 구간을 이루는 셀 쌍

    @property
    def midpoint(self) -> tuple[float, float]:
        """접면 중앙의 평면 좌표 — 문이 놓일 자리."""
        mid = self.start + self.length / 2
        return (float(self.fixed), mid) if self.orient == "V" else (mid, float(self.fixed))


def wall_runs(spec: BuildingSpec, plan: FloorPlan) -> list[WallRun]:
    """서로 다른 실이 맞닿은 벽을 연속 구간(run)으로 묶는다."""
    a = plan.assignment
    # (실쌍, 방향, 고정좌표) → [(가변좌표, 셀쌍)]
    buckets: dict[tuple, list[tuple[int, tuple[int, int]]]] = {}
    for c, d in spec.neighbor_pairs:
        ra, rb = a[c], a[d]
        if ra is None or rb is None or ra == rb:
            continue
        (xc, yc), (xd, yd) = spec.xy(c), spec.xy(d)
        pair = tuple(sorted((ra, rb)))
        if xd == xc + 1:  # 가로 이웃 → 세로벽
            key, var = (pair, "V", xd), yc
        else:  # 세로 이웃 → 가로벽
            key, var = (pair, "H", yd), xc
        buckets.setdefault(key, []).append((var, (c, d)))

    runs: list[WallRun] = []
    for (pair, orient, fixed), items in buckets.items():
        items.sort()
        run_start, run_len, edges = items[0][0], 1, [items[0][1]]
        for prev, (var, edge) in zip(items, items[1:]):
            if var == prev[0] + 1:
                run_len += 1
                edges.append(edge)
            else:
                runs.append(WallRun(pair[0], pair[1], orient, fixed, run_start, run_len, edges))
                run_start, run_len, edges = var, 1, [edge]
        runs.append(WallRun(pair[0], pair[1], orient, fixed, run_start, run_len, edges))
    return runs


def doors(spec: BuildingSpec, plan: FloorPlan, rules: SyntaxRules) -> dict[tuple[str, str], dict]:
    """규칙에 따라 실 쌍마다 문을 놓는다. 가장 긴 접면 구간에 하나."""
    best: dict[tuple[str, str], WallRun] = {}
    for run in wall_runs(spec, plan):
        key = (run.room_a, run.room_b)
        if run.length < rules.door_min_cells:
            continue
        if key not in best or run.length > best[key].length:
            best[key] = run

    out = {}
    for key, run in best.items():
        w = min(rules.door_width_cells, run.length)
        if rules.door_position == "first":
            off = 0
        elif rules.door_position == "last":
            off = run.length - w
        else:
            off = (run.length - w) // 2
        open_edges = set(run.edges[off:off + w])
        out[key] = {
            "run": run, "width": w,
            "open_edges": open_edges,
            "coord": run.midpoint,
            "shared_length": run.length,
        }
    return out


# ═══════════════════════════════════════════════ 볼록공간 그래프
@dataclass
class SyntaxGraph:
    nodes: list[str]
    adj: dict[str, set[str]]
    labels: dict[str, str]
    door_coords: dict[tuple[str, str], tuple[float, float]]
    rules: SyntaxRules

    def degree(self, v: str) -> int:
        return len(self.adj[v])


def build_graph(spec: BuildingSpec, plan: FloorPlan, rules: SyntaxRules) -> SyntaxGraph:
    dr = doors(spec, plan, rules)
    nodes = [r.key for r in spec.rooms if plan.cells_of(r.key)]
    adj: dict[str, set[str]] = {v: set() for v in nodes}
    door_coords: dict[tuple[str, str], tuple[float, float]] = {}

    for (ra, rb), info in dr.items():
        if ra in adj and rb in adj:
            adj[ra].add(rb)
            adj[rb].add(ra)
            door_coords[(ra, rb)] = info["coord"]

    labels = {r.key: r.name for r in spec.rooms}
    if rules.include_carrier:
        nodes = [CARRIER] + nodes
        adj[CARRIER] = set()
        labels[CARRIER] = "외부"
        if rules.carrier_mode == "perimeter":
            targets = {plan.assignment[c] for c in spec.cells
                       if spec.is_perimeter(c) and plan.assignment[c]}
        else:
            ent = plan.assignment[spec.entrance_idx]
            targets = {ent} if ent else set()
        for t in targets:
            if t in adj:
                adj[CARRIER].add(t)
                adj[t].add(CARRIER)
                ex, ey = spec.entrance
                door_coords[tuple(sorted((CARRIER, t)))] = (ex + 0.5, ey + 0.5)

    return SyntaxGraph(nodes, adj, labels, door_coords, rules)


# ═══════════════════════════════════════════════ 구문론 지표
def bfs_depths(g: SyntaxGraph, src: str) -> dict[str, int]:
    depth = {src: 0}
    queue = [src]
    while queue:
        nxt = []
        for v in queue:
            for u in g.adj[v]:
                if u not in depth:
                    depth[u] = depth[v] + 1
                    nxt.append(u)
        queue = nxt
    return depth


def diamond_value(k: int) -> float:
    """Hillier의 다이아몬드 값 D_k — 노드 수가 다른 그래프를 견줄 수 있게 한다."""
    if k < 4:
        return float("nan")
    return 2.0 * (k * (math.log2((k + 2) / 3.0) - 1.0) + 1.0) / ((k - 1) * (k - 2))


def betweenness(g: SyntaxGraph) -> dict[str, float]:
    """Choice(통과 가능성) = Brandes 알고리즘의 매개 중심성."""
    cb = {v: 0.0 for v in g.nodes}
    for s in g.nodes:
        stack, preds = [], {v: [] for v in g.nodes}
        sigma = {v: 0.0 for v in g.nodes}
        dist = {v: -1 for v in g.nodes}
        sigma[s], dist[s] = 1.0, 0
        queue = [s]
        while queue:
            v = queue.pop(0)
            stack.append(v)
            for w in g.adj[v]:
                if dist[w] < 0:
                    dist[w] = dist[v] + 1
                    queue.append(w)
                if dist[w] == dist[v] + 1:
                    sigma[w] += sigma[v]
                    preds[w].append(v)
        delta = {v: 0.0 for v in g.nodes}
        while stack:
            w = stack.pop()
            for v in preds[w]:
                delta[v] += sigma[v] / sigma[w] * (1 + delta[w])
            if w != s:
                cb[w] += delta[w]
    n = len(g.nodes)
    norm = ((n - 1) * (n - 2)) if n > 2 else 1
    return {v: c / norm for v, c in cb.items()}


def analyze_graph(g: SyntaxGraph) -> dict:
    """노드별 구문론 지표 + 전역 지표."""
    k = len(g.nodes)
    d_k = diamond_value(k)
    choice = betweenness(g)
    carrier_depth = bfs_depths(g, CARRIER) if CARRIER in g.adj else {}

    nodes: dict[str, dict] = {}
    for v in g.nodes:
        depths = bfs_depths(g, v)
        reach = [d for u, d in depths.items() if u != v]
        disconnected = len(reach) < k - 1
        td = sum(reach)
        md = td / (k - 1) if k > 1 else float("nan")
        ra = 2.0 * (md - 1.0) / (k - 2) if k > 2 else float("nan")
        rra = ra / d_k if d_k == d_k and d_k else float("nan")
        base = rra if g.rules.normalize == "rra" else ra
        nodes[v] = {
            "label": g.labels.get(v, v),
            "connectivity": g.degree(v),
            "total_depth": td,
            "mean_depth": md,
            "RA": ra,
            "RRA": rra,
            "integration": (1.0 / base) if base and base == base and base > 0 else float("nan"),
            "control_value": sum(1.0 / g.degree(u) for u in g.adj[v] if g.degree(u)),
            "choice": choice[v],
            "step_depth_from_carrier": carrier_depth.get(v),
            "disconnected": disconnected,
        }

    # 전역 지표
    ints = [n["integration"] for n in nodes.values() if n["integration"] == n["integration"]]
    cons = [nodes[v]["connectivity"] for v in nodes if nodes[v]["integration"] == nodes[v]["integration"]]
    glob = {
        "node_count": k,
        "edge_count": sum(g.degree(v) for v in g.nodes) // 2,
        "diamond_value": d_k,
        "mean_depth_system": sum(n["mean_depth"] for n in nodes.values()) / k if k else float("nan"),
        "mean_integration": sum(ints) / len(ints) if ints else float("nan"),
        "max_depth_from_carrier": max((d for d in carrier_depth.values()), default=None),
        "intelligibility": _r2(cons, ints),
        "difference_factor": _difference_factor([nodes[v]["RA"] for v in nodes]),
        "connected": all(not n["disconnected"] for n in nodes.values()),
    }
    return {"nodes": nodes, "global": glob}


def _r2(xs, ys) -> float:
    """명료성(intelligibility) = 연결도와 통합도의 결정계수 r²."""
    n = len(xs)
    if n < 3:
        return float("nan")
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return float("nan")
    return (sxy * sxy) / (sxx * syy)


def _difference_factor(ras: list[float]) -> float:
    """Hillier의 차이 계수 H* — 공간 위계가 얼마나 고른가 (1에 가까울수록 평평)."""
    vals = [r for r in ras if r == r and r > 0]
    if len(vals) < 2:
        return float("nan")
    t = sum(vals)
    h = -sum((v / t) * math.log(v / t) for v in vals)
    return h / math.log(len(vals))


# ═══════════════════════════════════════════════ 가시성 그래프 (VGA)
def passable_edges(spec: BuildingSpec, plan: FloorPlan, rules: SyntaxRules) -> set:
    """지나갈 수 있는(=시선이 통하는) 셀 쌍. 같은 실이거나 문이 뚫린 곳."""
    a = plan.assignment
    open_e = {(c, d) for c, d in spec.neighbor_pairs
              if a[c] is not None and a[c] == a[d]}
    for info in doors(spec, plan, rules).values():
        open_e |= info["open_edges"]
    return open_e


def _edge_open(open_e: set, c: int, d: int) -> bool:
    return (c, d) in open_e or (d, c) in open_e


def _step_ok(spec: BuildingSpec, open_e: set, prev: int, cur: int) -> bool:
    (px, py), (cx, cy) = spec.xy(prev), spec.xy(cur)
    dx, dy = cx - px, cy - py
    if abs(dx) + abs(dy) == 1:
        return _edge_open(open_e, prev, cur)
    if abs(dx) == 1 and abs(dy) == 1:  # 모서리 통과 — 두 경로 중 하나라도 열려야 한다
        for mx, my in ((cx, py), (px, cy)):
            m = spec.idx(mx, my)
            if _edge_open(open_e, prev, m) and _edge_open(open_e, m, cur):
                return True
    return False


def visibility_graph(spec: BuildingSpec, plan: FloorPlan, rules: SyntaxRules) -> dict[int, set[int]]:
    """셀 중심끼리 직선 시선이 통하는지 판정해 가시성 그래프를 만든다."""
    open_e = passable_edges(spec, plan, rules)
    vis: dict[int, set[int]] = {c: set() for c in spec.cells}
    step = max(rules.vga_step, 0.005)

    for i, ca in enumerate(spec.cells):
        x0, y0 = spec.xy(ca)
        x0, y0 = x0 + 0.5, y0 + 0.5
        for cb in spec.cells[i + 1:]:
            x1, y1 = spec.xy(cb)
            x1, y1 = x1 + 0.5, y1 + 0.5
            dx, dy = x1 - x0, y1 - y0
            n = max(2, int(math.hypot(dx, dy) / step))
            prev, blocked = ca, False
            for s in range(1, n + 1):
                t = s / n
                gx = min(spec.width - 1e-9, max(0.0, x0 + dx * t))
                gy = min(spec.height - 1e-9, max(0.0, y0 + dy * t))
                cur = spec.idx(int(gx), int(gy))
                if cur != prev:
                    if not _step_ok(spec, open_e, prev, cur):
                        blocked = True
                        break
                    prev = cur
            if not blocked:
                vis[ca].add(cb)
                vis[cb].add(ca)
    return vis


def analyze_vga(spec: BuildingSpec, plan: FloorPlan, vis: dict[int, set[int]],
                rules: SyntaxRules) -> dict:
    """셀별 시각 지표 — Turner et al.(2001)의 VGA + Benedikt(1979)의 아이소비스트."""
    k = len(spec.cells)
    d_k = diamond_value(k)
    cells: dict[int, dict] = {}

    for c in spec.cells:
        # 가시성 그래프 위에서의 깊이 (BFS)
        depth = {c: 0}
        queue = [c]
        while queue:
            nxt = []
            for v in queue:
                for u in vis[v]:
                    if u not in depth:
                        depth[u] = depth[v] + 1
                        nxt.append(u)
            queue = nxt
        reach = [d for u, d in depth.items() if u != c]
        md = sum(reach) / len(reach) if reach else float("nan")
        ra = 2.0 * (md - 1.0) / (k - 2) if k > 2 else float("nan")
        rra = ra / d_k if d_k == d_k and d_k else float("nan")
        base = rra if rules.normalize == "rra" else ra
        integ = (1.0 / base) if base and base == base and base > 0 else float("nan")

        # 군집 계수 — 보이는 것끼리 서로 보이는 비율
        nb = vis[c]
        pairs = len(nb) * (len(nb) - 1) / 2
        links = sum(1 for i, u in enumerate(sorted(nb)) for v in sorted(nb)[i + 1:] if v in vis[u])
        clustering = links / pairs if pairs else 0.0

        # 아이소비스트 (보이는 영역의 기하)
        seen = nb | {c}
        cx, cy = spec.xy(c)
        cx, cy = cx + 0.5, cy + 0.5
        radials = [math.hypot(spec.xy(s)[0] + 0.5 - cx, spec.xy(s)[1] + 0.5 - cy) for s in seen]
        perim = 0
        for s in seen:
            sx, sy = spec.xy(s)
            for ddx, ddy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx_, ny_ = sx + ddx, sy + ddy
                if not (0 <= nx_ < spec.width and 0 <= ny_ < spec.height) or spec.idx(nx_, ny_) not in seen:
                    perim += 1
        gx = sum(spec.xy(s)[0] + 0.5 for s in seen) / len(seen)
        gy = sum(spec.xy(s)[1] + 0.5 for s in seen) / len(seen)

        cells[c] = {
            "x": spec.xy(c)[0], "y": spec.xy(c)[1],
            "room": plan.assignment[c],
            "visual_connectivity": len(nb),
            "visual_mean_depth": md,
            "visual_integration": integ,
            "clustering": clustering,
            "isovist_area": len(seen),
            "isovist_perimeter": perim,
            "isovist_compactness": (4 * math.pi * len(seen) / (perim ** 2)) if perim else float("nan"),
            "isovist_max_radial": max(radials) if radials else 0.0,
            "isovist_mean_radial": sum(radials) / len(radials) if radials else 0.0,
            "isovist_drift": math.hypot(gx - cx, gy - cy),
        }

    ints = [v["visual_integration"] for v in cells.values() if v["visual_integration"] == v["visual_integration"]]
    cons = [v["visual_connectivity"] for v in cells.values() if v["visual_integration"] == v["visual_integration"]]
    return {
        "cells": cells,
        "global": {
            "mean_visual_integration": sum(ints) / len(ints) if ints else float("nan"),
            "mean_visual_connectivity": sum(v["visual_connectivity"] for v in cells.values()) / k,
            "visual_intelligibility": _r2(cons, ints),
            "mean_clustering": sum(v["clustering"] for v in cells.values()) / k,
        },
    }


# ═══════════════════════════════════════════════ 정당화 그래프 좌표
def jgraph_layout(g: SyntaxGraph, root: str | None = None) -> tuple[dict, dict]:
    """깊이를 세로축으로 삼는 정당화 그래프(j-graph) 좌표를 계산한다.

    이것이 '평면을 Space Syntax에 맞게 다시 좌표화한' 결과다.
    y = 뿌리로부터의 깊이, x = 같은 깊이 안에서의 가로 위치.
    """
    root = root or (CARRIER if CARRIER in g.adj else g.nodes[0])
    depth = bfs_depths(g, root)
    levels: dict[int, list[str]] = {}
    for v, d in depth.items():
        levels.setdefault(d, []).append(v)
    # 연결되지 않은 노드는 맨 아래 별도 층에
    orphan = [v for v in g.nodes if v not in depth]
    if orphan:
        levels[max(levels) + 1 if levels else 0] = orphan

    pos: dict[str, tuple[float, int]] = {}
    for d in sorted(levels):
        group = levels[d]
        if d == 0:
            order = group
        else:
            def key(v):
                ps = [pos[u][0] for u in g.adj[v] if depth.get(u) == d - 1 and u in pos]
                return (sum(ps) / len(ps) if ps else 0.0, g.labels.get(v, v))
            order = sorted(group, key=key)
        mid = (len(order) - 1) / 2
        for i, v in enumerate(order):
            pos[v] = (i - mid, d)
    return pos, depth


# ═══════════════════════════════════════════════ 통합 추출기 (프로그램의 본체)
def extract(spec: BuildingSpec, plan: FloorPlan, rules: SyntaxRules = DEFAULT_RULES) -> dict:
    """도면 + 규칙 → Space Syntax 좌표 및 지표 일체."""
    g = build_graph(spec, plan, rules)
    res = analyze_graph(g)
    pos, depth = jgraph_layout(g)
    coords = plan.coordinates(spec)
    dr = doors(spec, plan, rules)

    rooms = {}
    for v in g.nodes:
        m = res["nodes"][v]
        jx, jy = pos.get(v, (0.0, -1))
        entry = {
            "key": v, "label": m["label"],
            # 1) 실측 좌표
            "metric": None if v == CARRIER else {
                "centroid": coords[v]["centroid"], "bbox": coords[v]["bbox"],
                "area": coords[v]["area"], "cells": coords[v]["cells"],
                "components": coords[v]["components"],
            },
            # 2) 위상 좌표 (j-graph)
            "syntactic": {"jx": jx, "depth": jy,
                          "step_depth_from_carrier": m["step_depth_from_carrier"]},
            # 지표
            "measures": {kk: m[kk] for kk in
                         ("connectivity", "total_depth", "mean_depth", "RA", "RRA",
                          "integration", "control_value", "choice", "disconnected")},
        }
        rooms[v] = entry

    edges = []
    for a_, b_ in {tuple(sorted((v, u))) for v in g.nodes for u in g.adj[v]}:
        key = (a_, b_)
        info = dr.get(key) or dr.get((b_, a_))
        edges.append({
            "a": a_, "b": b_,
            "a_label": g.labels.get(a_, a_), "b_label": g.labels.get(b_, b_),
            "door_coord": g.door_coords.get(key),
            "shared_wall_cells": info["shared_length"] if info else None,
            "door_width_cells": info["width"] if info else None,
        })

    out = {
        "rules": rules.as_dict(),
        "plan": {"name": plan.name, "source": plan.source, "spec": spec.key},
        "rooms": rooms,
        "edges": sorted(edges, key=lambda e: (e["a"], e["b"])),
        "global": res["global"],
    }

    if rules.vga_enabled:
        vis = visibility_graph(spec, plan, rules)
        vga = analyze_vga(spec, plan, vis, rules)
        out["vga"] = vga["cells"]
        out["global"].update(vga["global"])
        # 3) 시각 좌표 — 실 단위로 평균 낸 값
        for v in g.nodes:
            if v == CARRIER:
                continue
            cs = [vga["cells"][c] for c in plan.cells_of(v)]
            if cs:
                rooms[v]["visual"] = {
                    "mean_visual_integration": sum(c["visual_integration"] for c in cs) / len(cs),
                    "mean_visual_connectivity": sum(c["visual_connectivity"] for c in cs) / len(cs),
                    "mean_isovist_area": sum(c["isovist_area"] for c in cs) / len(cs),
                }
    return out
