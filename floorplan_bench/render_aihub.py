"""AI 허브 라벨 JSON을 그대로 도면(SVG)으로 그린다.

    SPA  실 폴리곤을 용도별 색으로 + 실명·면적비, 세대 테두리·점수, 추정 문(●)과 연결선
    STR  벽(진회색)·문(주황)·창(파랑), 겹친 문·창은 빨강
    OBJ  위생·주방 기구 박스      OCR  글자를 제자리에

웹 스튜디오(docs/aihub.html)의 그림과 같은 색을 쓴다.
"""

from __future__ import annotations

from html import escape

from .aihub import CORE_CATS, OBJ_CATS, SPACE_CATS, STR_CATS, _pts

KIND_COLOR = {
    "living": "#f6d68b", "bed": "#a9cbe8", "kitchen": "#f3b38d", "entry": "#c9b6e4",
    "bath": "#9fd8d0", "balcony": "#d9e4c4", "dress": "#e8c3d4", "ac": "#d6d6d6",
    "etc": "#e4e0d6", "multi": "#c8dcb4",
}
CORE_COLOR = "#cfd4d8"
GRADE_COLOR = {"A": "#12705f", "B": "#2a7f8f", "C": "#9a6a10", "D": "#a8451a", "F": "#a8451a"}


def _extent(anns) -> tuple[float, float, float, float]:
    xs, ys = [], []
    for a in anns:
        x, y, w, h = a["bbox"]
        xs += [x, x + w]
        ys += [y, y + h]
    return (min(xs), min(ys), max(xs), max(ys)) if xs else (0, 0, 100, 100)


def _poly(pts, **attrs) -> str:
    d = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    extra = " ".join(f'{k.replace("_", "-")}="{v}"' for k, v in attrs.items())
    return f'<polygon points="{d}" {extra}/>'


def render_sheet(data: dict, kind: str = "SPA", units=None, results=None,
                 graph: bool = True, title: str = "") -> str:
    """라벨 한 장 → SVG 문자열. units·results(evaluate 결과)가 있으면 문·점수까지."""
    anns = [a for a in data.get("annotations", []) if a.get("category_id") != 12]
    x0, y0, x1, y1 = _extent(anns)
    pad = max(x1 - x0, y1 - y0) * 0.04
    x0, y0, x1, y1 = x0 - pad, y0 - pad, x1 + pad, y1 + pad
    W, H = x1 - x0, y1 - y0
    fs = max(W, H) / 110           # 글자 크기
    sw = max(W, H) / 900           # 선 굵기
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{x0:.0f} {y0:.0f} {W:.0f} {H:.0f}" '
           f'font-family="IBM Plex Sans KR, Apple SD Gothic Neo, sans-serif">',
           f'<rect x="{x0:.0f}" y="{y0:.0f}" width="{W:.0f}" height="{H:.0f}" fill="#fbfbf9"/>']
    if title:
        out.append(f'<text x="{x0 + pad / 2:.0f}" y="{y0 + fs * 1.6:.0f}" font-size="{fs * 1.2:.1f}" '
                   f'fill="#44586a">{escape(title)}</text>')

    if kind == "SPA":
        out += _spa(anns, units or [], results or [], graph, fs, sw)
    elif kind == "STR":
        out += _str(anns, fs, sw, results or [])
    else:
        for a in anns:
            x, y, w, h = a["bbox"]
            if kind == "OBJ":
                name = OBJ_CATS.get(a["category_id"], "?")
                out.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" fill="#e7eef2" '
                           f'stroke="#55707f" stroke-width="{sw:.2f}"/>')
                out.append(f'<text x="{x + w / 2:.1f}" y="{y + h / 2:.1f}" font-size="{fs * .7:.1f}" '
                           f'text-anchor="middle" dominant-baseline="middle" fill="#2c3e48">{escape(name)}</text>')
            else:
                txt = a.get("attributes", {}).get("OCR", "")
                out.append(f'<text x="{x:.1f}" y="{y + h:.1f}" font-size="{max(h, fs * .6):.1f}" '
                           f'fill="#2c3e48">{escape(txt)}</text>')
    out.append("</svg>")
    return "\n".join(out)


def _spa(anns, units, results, graph, fs, sw) -> list[str]:
    out = []
    for a in anns:
        cid = a["category_id"]
        if not a.get("segmentation") or not a["segmentation"][0]:
            continue
        pts = _pts(a["segmentation"][0])
        if cid in SPACE_CATS:
            out.append(_poly(pts, fill=KIND_COLOR[SPACE_CATS[cid][0]], stroke="#5b6b75",
                             stroke_width=f"{sw:.2f}", fill_opacity=".9"))
        elif cid in CORE_CATS:
            out.append(_poly(pts, fill=CORE_COLOR, stroke="#8a969d", stroke_width=f"{sw:.2f}",
                             stroke_dasharray=f"{sw * 4:.1f} {sw * 3:.1f}"))
    res_by = {r["unit"]: r for r in results}
    for u in units:
        r = res_by.get(u.uid)
        flagged = set()
        if r:
            for i in r["feasibility"]["issues"]:
                if i["level"] != "info":
                    flagged.update(i["rooms"])
            for row in r.get("criteria_rows", []):
                if row.get("room") and row["score"] is not None and row["score"] < 1 \
                        and row["criterion"]["effect"] != "weight":
                    flagged.add(row["room"])
        for k in flagged:
            if k in u.spaces:
                out.append(_poly(u.spaces[k].poly, fill="none", stroke="#c0392b",
                                 stroke_width=f"{sw * 3:.2f}"))
        # 연결(추정 문)
        if r and graph:
            for a_, b_ in r["doors_inferred"]:
                ca, cb = u.spaces[a_].centroid, u.spaces[b_].centroid
                out.append(f'<line x1="{ca[0]:.1f}" y1="{ca[1]:.1f}" x2="{cb[0]:.1f}" y2="{cb[1]:.1f}" '
                           f'stroke="#0d8f7c" stroke-width="{sw * 1.6:.2f}" stroke-opacity=".55"/>')
            for a_, b_ in r["doors_inferred"]:
                mid = u.contact_mid.get((a_, b_)) or u.contact_mid.get((b_, a_))
                if mid:
                    out.append(f'<circle cx="{mid[0]:.1f}" cy="{mid[1]:.1f}" r="{fs * .32:.1f}" '
                               f'fill="#0d8f7c" stroke="#fff" stroke-width="{sw:.2f}"/>')
        # 실 이름·면적비
        for k, s in u.spaces.items():
            cx, cy = s.centroid
            small = s.bbox[2] < fs * 3 or s.bbox[3] < fs * 1.8
            size = fs * (.55 if small else .8)
            out.append(f'<text x="{cx:.1f}" y="{cy:.1f}" font-size="{size:.1f}" text-anchor="middle" '
                       f'fill="#1e2a33" font-weight="500">{escape(s.name)}</text>')
            if not small:
                out.append(f'<text x="{cx:.1f}" y="{cy + size * 1.15:.1f}" font-size="{size * .75:.1f}" '
                           f'text-anchor="middle" fill="#5b6b75">{s.area_px / u.area_px:.0%}</text>')
        # 세대 테두리 + 점수
        xs = [p[0] for s in u.spaces.values() for p in s.poly]
        ys = [p[1] for s in u.spaces.values() for p in s.poly]
        bx0, by0, bx1, by1 = min(xs), min(ys), max(xs), max(ys)
        m = fs * .6
        out.append(f'<rect x="{bx0 - m:.1f}" y="{by0 - m:.1f}" width="{bx1 - bx0 + 2 * m:.1f}" '
                   f'height="{by1 - by0 + 2 * m:.1f}" fill="none" stroke="#1e2a33" '
                   f'stroke-width="{sw * 1.5:.2f}" stroke-dasharray="{sw * 8:.1f} {sw * 5:.1f}"/>')
        label = f"#{u.index} {u.uid.split('#')[0][-9:]} · " + (r["type"] if r else "")
        if r:
            sc = r["score"]
            label += f" · {sc['total']:.0f}점 {sc['grade']}"
        color = GRADE_COLOR.get((r["score"]["grade"][0] if r else "C"), "#44586a")
        out.append(f'<text x="{bx0 - m:.1f}" y="{by0 - m * 1.8:.1f}" font-size="{fs:.1f}" '
                   f'font-weight="600" fill="{color}">{escape(label)}</text>')
    return out


def _str(anns, fs, sw, issues) -> list[str]:
    bad = {i["door"] for i in issues} | {i["window"] for i in issues}
    out = []
    order = {11: 0, 10: 1, 9: 2}
    for a in sorted(anns, key=lambda a: order.get(a["category_id"], 3)):
        kind = STR_CATS.get(a["category_id"])
        if not kind or not a.get("segmentation") or not a["segmentation"][0]:
            continue
        pts = _pts(a["segmentation"][0])
        hit = a["id"] in bad
        if kind == "wall":
            out.append(_poly(pts, fill="#46525a", stroke="none"))
        elif kind == "door":
            out.append(_poly(pts, fill="#c0392b" if hit else "#e08a2c", stroke="#7a4a12",
                             stroke_width=f"{sw:.2f}", fill_opacity=".85"))
        else:
            out.append(_poly(pts, fill="#c0392b" if hit else "#5aa9e6", stroke="#1f5f8f",
                             stroke_width=f"{sw:.2f}", fill_opacity=".75"))
    return out
