"""도면 렌더링과 비교 리포트."""

from __future__ import annotations

import html

from .env import EnvWeights
from .plan import FloorPlan
from .spec import BuildingSpec

from .terms import LABELS, QUALITY_KEYS, TERM_META

TERM_LABELS = {k: LABELS[k] for k in QUALITY_KEYS}


def render_svg(spec: BuildingSpec, plan: FloorPlan, cell: int = 34, label: bool = True) -> str:
    """도면을 SVG로 그린다. 방 경계에만 굵은 벽선을 넣는다."""
    W, H = spec.width * cell, spec.height * cell
    pad = 6
    out = [
        f'<svg viewBox="0 0 {W + pad * 2} {H + pad * 2}" '
        f'xmlns="http://www.w3.org/2000/svg" class="plan-svg" role="img">',
        f'<rect x="0" y="0" width="{W + pad * 2}" height="{H + pad * 2}" fill="none"/>',
        f'<g transform="translate({pad},{pad})">',
    ]

    # 셀 채우기
    for i, key in enumerate(plan.assignment):
        x, y = spec.xy(i)
        color = spec.room_by_key[key].color if key else "#f2f2f2"
        out.append(
            f'<rect x="{x * cell}" y="{y * cell}" width="{cell}" height="{cell}" '
            f'fill="{color}" stroke="rgba(0,0,0,.07)" stroke-width="1"/>'
        )

    # 방 경계 = 벽
    walls = []
    for y in range(spec.height):
        for x in range(spec.width):
            i = spec.idx(x, y)
            if x + 1 < spec.width and plan.assignment[i] != plan.assignment[spec.idx(x + 1, y)]:
                walls.append(((x + 1) * cell, y * cell, (x + 1) * cell, (y + 1) * cell))
            if y + 1 < spec.height and plan.assignment[i] != plan.assignment[spec.idx(x, y + 1)]:
                walls.append((x * cell, (y + 1) * cell, (x + 1) * cell, (y + 1) * cell))
    for x1, y1, x2, y2 in walls:
        out.append(
            f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
            f'stroke="#1a1a1a" stroke-width="2.4" stroke-linecap="square"/>'
        )
    out.append(
        f'<rect x="0" y="0" width="{W}" height="{H}" fill="none" '
        f'stroke="#1a1a1a" stroke-width="3.5"/>'
    )

    # 방 이름
    if label:
        for key, info in plan.coordinates(spec).items():
            if not info["cells"]:
                continue
            cx, cy = info["centroid"]
            out.append(
                f'<text x="{cx * cell:.1f}" y="{cy * cell:.1f}" text-anchor="middle" '
                f'dominant-baseline="central" font-size="{max(9, cell * 0.30):.0f}" '
                f'fill="#12303f" font-weight="600" '
                f'style="paint-order:stroke;stroke:rgba(255,255,255,.85);stroke-width:3px">'
                f'{html.escape(info["name"])}</text>'
            )

    # 현관 표시
    ex, ey = spec.entrance
    out.append(
        f'<circle cx="{(ex + 0.5) * cell}" cy="{(ey + 0.5) * cell}" r="{cell * 0.17:.1f}" '
        f'fill="#e63946" stroke="#fff" stroke-width="2"/>'
    )
    out.append("</g></svg>")
    return "".join(out)


def term_breakdown(spec: BuildingSpec, plan: FloorPlan, w: EnvWeights) -> list[dict]:
    """평가 항목별 기여도 — 왜 이 도면이 좋은지/나쁜지 설명한다."""
    t = plan.raw_terms(spec)
    rows = [
        {"key": m.key, "label": m.label, "raw": t[m.key],
         "weight": getattr(w, m.weight_field), "sign": m.sign,
         "contribution": m.sign * getattr(w, m.weight_field) * t[m.key]}
        for m in TERM_META if m.form != "하드"
    ]
    penalty = w.p_cell * t["cell_violation"] + w.p_area * t["area_error"]
    if penalty:
        rows.append({"key": "penalty", "label": "제약 위반 벌점", "raw": penalty / max(w.p_cell, 1),
                     "weight": 1.0, "contribution": penalty})
    return rows


def text_summary(spec, plan, w, title="") -> str:
    t = plan.raw_terms(spec)
    coords = plan.coordinates(spec)
    frag = [v["name"] for v in coords.values() if v["components"] > 1]
    lines = [
        f"{title} 에너지 {plan.score(spec, w):+.3f}  "
        f"(유효 {'O' if plan.is_feasible(spec) else 'X'})",
        "  " + "  ".join(f"{TERM_LABELS[k]} {t[k]:+.3f}" for k in TERM_LABELS),
    ]
    if frag:
        lines.append(f"  조각난 방: {', '.join(frag)}")
    return "\n".join(lines)
