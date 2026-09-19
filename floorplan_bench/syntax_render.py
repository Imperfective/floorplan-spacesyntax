"""Space Syntax 결과 시각화 — 정당화 그래프와 지표 히트맵."""

from __future__ import annotations

import html
import math

from .plan import FloorPlan
from .spacesyntax import CARRIER, SyntaxGraph
from .spec import BuildingSpec

# 순차 램프(단일 색상, 밝음 → 어두움). 무지개는 쓰지 않는다.
RAMP = ["#f7ede2", "#f2dcc2", "#e9c193", "#dda263", "#c8823a", "#a76420", "#7d4913"]
RAMP_COOL = ["#e8f1f2", "#cfe4e6", "#a9d0d4", "#7ab6bd", "#4e97a0", "#2f757e", "#1b545c"]


def ramp_color(t: float, ramp=RAMP) -> str:
    """0~1 값을 램프 색으로. NaN은 중립 회색."""
    if t != t:
        return "#dcdcdc"
    t = min(1.0, max(0.0, t))
    i = t * (len(ramp) - 1)
    return ramp[int(round(i))]


def _norm(vals: dict, key=None):
    xs = [v if key is None else v[key] for v in vals.values()]
    xs = [x for x in xs if x == x]
    if not xs:
        return lambda v: float("nan")
    lo, hi = min(xs), max(xs)
    span = hi - lo or 1.0
    return lambda v: (v - lo) / span if v == v else float("nan")


def render_jgraph(g: SyntaxGraph, extract_result: dict, cell: int = 74,
                  color_by: str = "integration") -> str:
    """정당화 그래프(j-graph) — 깊이를 세로축으로 삼은 위상 좌표계."""
    rooms = extract_result["rooms"]
    pts = {k: (v["syntactic"]["jx"], v["syntactic"]["depth"]) for k, v in rooms.items()}
    if not pts:
        return ""
    xs = [p[0] for p in pts.values()]
    ys = [p[1] for p in pts.values()]
    minx, maxx, maxy = min(xs), max(xs), max(ys)
    pad_x, pad_y, top = 96, 46, 30
    W = int((maxx - minx + 1) * cell) + pad_x * 2
    H = int(maxy * cell) + pad_y + top + 34

    nx = lambda x: pad_x + (x - minx) * cell
    ny = lambda y: top + y * cell

    vals = {k: v["measures"].get(color_by, float("nan")) for k, v in rooms.items()}
    f = _norm(vals)

    out = [f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" class="jgraph" role="img">']
    # 깊이 층 안내선
    for d in range(int(maxy) + 1):
        y = ny(d)
        out.append(f'<line x1="{pad_x - 52}" y1="{y}" x2="{W - 24}" y2="{y}" class="jlevel"/>')
        out.append(f'<text x="{pad_x - 60}" y="{y}" class="jdepth" text-anchor="end" '
                   f'dominant-baseline="central">깊이 {d}</text>')
    # 간선
    for e in extract_result["edges"]:
        if e["a"] not in pts or e["b"] not in pts:
            continue
        (x1, y1), (x2, y2) = pts[e["a"]], pts[e["b"]]
        out.append(f'<line x1="{nx(x1)}" y1="{ny(y1)}" x2="{nx(x2)}" y2="{ny(y2)}" class="jedge"/>')
    # 노드
    for k, (x, y) in pts.items():
        cx, cy = nx(x), ny(y)
        fill = ramp_color(f(vals[k]))
        label = html.escape(rooms[k]["label"])
        if k == CARRIER:
            r = 13
            out.append(f'<rect x="{cx-r}" y="{cy-r}" width="{2*r}" height="{2*r}" '
                       f'transform="rotate(45 {cx} {cy})" fill="none" class="jcarrier"/>')
        else:
            out.append(f'<circle cx="{cx}" cy="{cy}" r="15" fill="{fill}" class="jnode"/>')
        out.append(f'<text x="{cx}" y="{cy + 30}" class="jlabel" text-anchor="middle">{label}</text>')
    out.append("</svg>")
    return "".join(out)


def render_room_heatmap(spec: BuildingSpec, plan: FloorPlan, values: dict[str, float],
                        cell: int = 30, ramp=RAMP, fmt="{:.2f}") -> str:
    """실 단위 지표를 평면도 위에 칠한다."""
    f = _norm(values)
    W, H, pad = spec.width * cell, spec.height * cell, 5
    out = [f'<svg viewBox="0 0 {W+pad*2} {H+pad*2}" xmlns="http://www.w3.org/2000/svg" '
           f'class="plan-svg" role="img"><g transform="translate({pad},{pad})">']
    for i, key in enumerate(plan.assignment):
        x, y = spec.xy(i)
        col = ramp_color(f(values.get(key, float("nan"))), ramp) if key else "#f2f2f2"
        out.append(f'<rect x="{x*cell}" y="{y*cell}" width="{cell}" height="{cell}" '
                   f'fill="{col}" stroke="rgba(0,0,0,.05)"/>')
    for y in range(spec.height):
        for x in range(spec.width):
            i = spec.idx(x, y)
            if x + 1 < spec.width and plan.assignment[i] != plan.assignment[spec.idx(x+1, y)]:
                out.append(f'<line x1="{(x+1)*cell}" y1="{y*cell}" x2="{(x+1)*cell}" '
                           f'y2="{(y+1)*cell}" stroke="#1a1a1a" stroke-width="2.2"/>')
            if y + 1 < spec.height and plan.assignment[i] != plan.assignment[spec.idx(x, y+1)]:
                out.append(f'<line x1="{x*cell}" y1="{(y+1)*cell}" x2="{(x+1)*cell}" '
                           f'y2="{(y+1)*cell}" stroke="#1a1a1a" stroke-width="2.2"/>')
    out.append(f'<rect x="0" y="0" width="{W}" height="{H}" fill="none" stroke="#1a1a1a" stroke-width="3"/>')
    for key, info in plan.coordinates(spec).items():
        if not info["cells"]:
            continue
        cx, cy = info["centroid"]
        v = values.get(key, float("nan"))
        txt = fmt.format(v) if v == v else "—"
        name = info["name"]
        bw = (info["bbox"][2] - info["bbox"][0]) * cell  # 실이 쓸 수 있는 가로 폭(px)
        fs_name = max(6.5, min(cell * 0.29, bw * 0.92 / max(len(name), 1) * 1.75))
        fs_val = max(6.5, min(cell * 0.26, bw * 0.92 / max(len(txt), 1) * 1.75))
        stroke = 'paint-order:stroke;stroke:rgba(255,255,255,.92);stroke-width:2.6px'
        out.append(f'<text x="{cx*cell:.1f}" y="{cy*cell-3:.1f}" text-anchor="middle" '
                   f'font-size="{fs_name:.1f}" fill="#1e2a33" font-weight="600" style="{stroke}">'
                   f'{html.escape(name)}</text>')
        out.append(f'<text x="{cx*cell:.1f}" y="{cy*cell+fs_name*0.95+2:.1f}" text-anchor="middle" '
                   f'font-size="{fs_val:.1f}" fill="#1e2a33" font-family="monospace" '
                   f'style="{stroke}">{txt}</text>')
    ex, ey = spec.entrance
    out.append(f'<circle cx="{(ex+0.5)*cell}" cy="{(ey+0.5)*cell}" r="{cell*0.16:.1f}" '
               f'fill="#e63946" stroke="#fff" stroke-width="2"/>')
    out.append("</g></svg>")
    return "".join(out)


def render_cell_heatmap(spec: BuildingSpec, plan: FloorPlan, cells: dict,
                        key: str, cell: int = 30, ramp=RAMP_COOL) -> str:
    """셀 단위 VGA 지표 히트맵."""
    vals = {c: cells[c][key] for c in cells}
    f = _norm(vals)
    W, H, pad = spec.width * cell, spec.height * cell, 5
    out = [f'<svg viewBox="0 0 {W+pad*2} {H+pad*2}" xmlns="http://www.w3.org/2000/svg" '
           f'class="plan-svg" role="img"><g transform="translate({pad},{pad})">']
    for c in spec.cells:
        x, y = spec.xy(c)
        out.append(f'<rect x="{x*cell}" y="{y*cell}" width="{cell}" height="{cell}" '
                   f'fill="{ramp_color(f(vals[c]), ramp)}"/>')
    for y in range(spec.height):
        for x in range(spec.width):
            i = spec.idx(x, y)
            if x + 1 < spec.width and plan.assignment[i] != plan.assignment[spec.idx(x+1, y)]:
                out.append(f'<line x1="{(x+1)*cell}" y1="{y*cell}" x2="{(x+1)*cell}" '
                           f'y2="{(y+1)*cell}" stroke="#12303f" stroke-width="2.2"/>')
            if y + 1 < spec.height and plan.assignment[i] != plan.assignment[spec.idx(x, y+1)]:
                out.append(f'<line x1="{x*cell}" y1="{(y+1)*cell}" x2="{(x+1)*cell}" '
                           f'y2="{(y+1)*cell}" stroke="#12303f" stroke-width="2.2"/>')
    out.append(f'<rect x="0" y="0" width="{W}" height="{H}" fill="none" stroke="#12303f" stroke-width="3"/>')
    ex, ey = spec.entrance
    out.append(f'<circle cx="{(ex+0.5)*cell}" cy="{(ey+0.5)*cell}" r="{cell*0.16:.1f}" '
               f'fill="#e63946" stroke="#fff" stroke-width="2"/>')
    out.append("</g></svg>")
    return "".join(out)


def ramp_legend(lo: float, hi: float, label: str, ramp=RAMP) -> str:
    stops = "".join(f'<i style="background:{c}"></i>' for c in ramp)
    return (f'<div class="ramp"><span class="rlab">{html.escape(label)}</span>'
            f'<span class="rlo">{lo:.2f}</span><span class="rbar">{stops}</span>'
            f'<span class="rhi">{hi:.2f}</span></div>')
