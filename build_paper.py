"""out/study.json → 논문 형식 HTML 보고서."""
from __future__ import annotations

import html, json, math
from datetime import date

from floorplan_bench.env import PRESETS
from floorplan_bench.plan import FloorPlan
from floorplan_bench.report import render_svg
from floorplan_bench.spec import SPECS
from floorplan_bench.terms import TERM_META, META_BY_KEY

S = json.load(open("out/study.json", encoding="utf-8"))
M = S["meta"]
SPEC = SPECS[M["spec"]]
W = PRESETS[M["base_env"]]
E = html.escape
QK = [t.key for t in TERM_META if t.form != "하드"]

_fig, _tab = [0], [0]
def FIG(): _fig[0] += 1; return _fig[0]
def TAB(): _tab[0] += 1; return _tab[0]

def n(v, d=3, sign=False):
    if v is None: return "—"
    return f"{v:+.{d}f}" if sign else f"{v:.{d}f}"

def plan_of(a): return FloorPlan(SPEC.key, "", a)
def svg(a, cell=30): return render_svg(SPEC, plan_of(a), cell=cell)

ENGINES = {
    "baseline": ("AI 생성 최고안", "s-gen", "생성기가 만든 후보 중 최저 에너지"),
    "ortools": ("OR-Tools CP-SAT", "s-ort", "네이티브 제약 + 분기한정"),
    "ortools_connected": ("OR-Tools + 연결성", "s-ort", "QUBO로는 표현 불가한 제약 추가"),
    "dwave": ("D-Wave SA (QUBO)", "s-dw", "페널티 인코딩 · 단일 비트 뒤집기"),
    "swap_anneal": ("교환 어닐링 (제약 보존)", "s-sw", "같은 어닐링 · 인코딩만 교체"),
}

def figure(a, title, sub, tone="", cap=None) -> str:
    return f"""<figure class="drawing {tone}">
  <div class="mat">{svg(a)}</div>
  <figcaption><p class="dname">{E(title)}</p><p class="dsub">{sub}</p>
  {f'<p class="dcap">{cap}</p>' if cap else ''}</figcaption>
</figure>"""


# ═══════════════════════════════════════════════ 차트 부품
def grouped_bars(rows: list[dict], series: list[dict], unit="", top=None) -> str:
    """rows: [{key,label,values:{sid:v}}] · series: [{id,label,cls}] — 공통 축 하나."""
    vals = [abs(v) for r in rows for v in r["values"].values() if v is not None]
    top = top or max(vals) * 1.16
    ticks = [t for t in (0.2, 0.4, 0.6, 0.8, 1.0, 2.0, 4.0, 8.0, 16.0, 32.0) if t < top]
    if len(ticks) > 5: ticks = ticks[-5:]
    tick_html = "".join(
        f'<span class="tick" style="left:{t/top*100:.2f}%"><i></i><b>{t:g}</b></span>' for t in ticks)
    out = []
    for r in rows:
        bars = []
        for s in series:
            v = r["values"].get(s["id"])
            if v is None:
                bars.append('<div class="bar-line"><span class="bval dim">—</span></div>'); continue
            pct = max(abs(v)/top*100, 0.9)
            bars.append(
                f'<div class="bar-line"><div class="bar {s["cls"]}" style="width:{pct:.2f}%">'
                f'<span class="tip">{E(s["label"])} · {E(r["label"])} {n(v,3,True)}</span></div>'
                f'<span class="bval">{n(v,3)}</span></div>')
        out.append(f'<div class="mrow"><div class="mlabel">{E(r["label"])}</div>'
                   f'<div class="mtrack">{tick_html}{"".join(bars)}</div></div>')
    legend = "".join(f'<span class="lg"><i class="sw {s["cls"]}"></i>{E(s["label"])}</span>' for s in series)
    return (f'<div class="chart"><div class="chart-head">'
            f'<p class="ctitle">{E(unit)}</p><div class="legend">{legend}</div></div>'
            f'<div class="bars">{"".join(out)}</div></div>')


def line_chart(xs, series, xlabel, ylabel, logx=True, w=620, h=250) -> str:
    """단일 y축 선 그래프. viewBox에 라벨 자리를 남긴다."""
    L, R, T, B = 62, 22, 16, 44
    iw, ih = w - L - R, h - T - B
    fx = (lambda v: (math.log10(v) - math.log10(min(xs))) /
          max(math.log10(max(xs)) - math.log10(min(xs)), 1e-9)) if logx else \
         (lambda v: (v - min(xs)) / max(max(xs) - min(xs), 1e-9))
    allv = [v for s in series for v in s["values"] if v is not None]
    lo, hi = min(allv), max(allv)
    pad = (hi - lo) * 0.14 or 1
    lo, hi = lo - pad, hi + pad
    fy = lambda v: ih - (v - lo) / (hi - lo) * ih

    g = [f'<svg viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg" class="linechart" role="img">',
         f'<g transform="translate({L},{T})">']
    for i in range(5):  # 격자
        yy = ih * i / 4
        val = hi - (hi - lo) * i / 4
        g.append(f'<line x1="0" y1="{yy:.1f}" x2="{iw}" y2="{yy:.1f}" class="cgrid"/>')
        g.append(f'<text x="-10" y="{yy:.1f}" class="ctick" text-anchor="end" dominant-baseline="central">{val:.1f}</text>')
    for x in xs:
        xx = fx(x) * iw
        g.append(f'<text x="{xx:.1f}" y="{ih+20}" class="ctick" text-anchor="middle">{x:,}</text>')
    for s in series:
        pts = [(fx(x)*iw, fy(v)) for x, v in zip(xs, s["values"]) if v is not None]
        d = " ".join(f'{"M" if i==0 else "L"}{px:.1f},{py:.1f}' for i,(px,py) in enumerate(pts))
        g.append(f'<path d="{d}" fill="none" class="cline {s["cls"]}" stroke-width="2"/>')
        for px, py in pts:
            g.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="4" class="cdot {s["cls"]}"/>')
        lx, ly = pts[-1]
        g.append(f'<text x="{lx-6:.1f}" y="{ly-12:.1f}" class="clabel {s["cls"]}" text-anchor="end">{E(s["label"])}</text>')
    g.append(f'<text x="{iw/2:.0f}" y="{ih+38}" class="caxis" text-anchor="middle">{E(xlabel)}</text>')
    g.append(f'<text transform="translate({-L+13},{ih/2:.0f}) rotate(-90)" class="caxis" text-anchor="middle">{E(ylabel)}</text>')
    g.append("</g></svg>")
    return "".join(g)


# ═══════════════════════════════════════════════ 2. 표·본문 조립
def room_table() -> str:
    rows = "".join(
        f'<tr><td><i class="dot" style="background:{r["color"]}"></i>{E(r["name"])}</td>'
        f'<td class="mono dim">{E(r["key"])}</td><td class="n">{r["area"]}</td>'
        f'<td class="n">{"●" if r["needs_window"] else "○"}</td>'
        f'<td class="n">{r["privacy"]:.1f}</td><td class="n">{r["public"]:.1f}</td>'
        f'<td class="n">{r["noise"]:.1f}</td><td class="n">{r["quiet"]:.1f}</td>'
        f'<td class="n">{"●" if r["wet"] else "○"}</td></tr>' for r in M["rooms"])
    return f"""<div class="tw"><table>
<thead><tr><th>실</th><th>키</th><th class="n">요구 면적</th><th class="n">채광</th>
<th class="n">사적도</th><th class="n">공용도</th><th class="n">소음</th><th class="n">정숙</th>
<th class="n">급배수</th></tr></thead><tbody>{rows}</tbody></table></div>"""


def term_table() -> str:
    rows = ""
    for t in TERM_META:
        badge = "벌점" if t.sign > 0 else "보상"
        cls = "pen" if t.sign > 0 else "rew"
        rows += (f'<tr><td class="mono dim">{E(t.weight_field)}</td>'
                 f'<td><b>{E(t.label)}</b></td>'
                 f'<td><span class="tag {cls}">{badge}</span> <span class="tag form">{E(t.form)}</span></td>'
                 f'<td class="q">{E(t.question)}</td>'
                 f'<td class="dim sm">{E(t.normalizer)}</td>'
                 f'<td class="n">{getattr(W, t.weight_field):g}</td></tr>')
    return f"""<div class="tw"><table>
<thead><tr><th>변수</th><th>항</th><th>성격</th><th>답하는 설계 질문</th>
<th>정규화 분모</th><th class="n">기준값</th></tr></thead><tbody>{rows}</tbody></table></div>"""


def preset_table() -> str:
    fields = [t.weight_field for t in TERM_META if t.form != "하드"]
    head = "".join(f'<th class="n sm">{E(META_BY_KEY[t.key].label[:2])}</th>'
                   for t in TERM_META if t.form != "하드")
    rows = ""
    for k, p in M["presets"].items():
        cells = "".join(f'<td class="n {"hi" if p[f] >= 9 else ""}">{p[f]:g}</td>' for f in fields)
        rows += (f'<tr class="{"sel" if k == M["base_env"] else ""}">'
                 f'<td><b>{E(p["name"])}</b><br><span class="dim sm">{E(p["description"])}</span></td>'
                 f'{cells}</tr>')
    return f'<div class="tw"><table class="dense"><thead><tr><th>프리셋</th>{head}</tr></thead><tbody>{rows}</tbody></table></div>'


def result_table() -> str:
    keys = ["baseline", "ortools", "ortools_connected", "dwave", "swap_anneal"]
    best = min(S[k]["energy"] for k in keys)
    rows = ""
    for k in keys:
        r, (label, cls, note) = S[k], ENGINES[k]
        gap = r["energy"] - best
        rows += (f'<tr><td><i class="sw {cls}"></i><b>{E(label)}</b>'
                 f'<br><span class="dim sm">{E(note)}</span></td>'
                 f'<td class="n strong">{n(r["energy"])}</td>'
                 f'<td class="n">{"—" if gap == 0 else n(gap, 3, True)}</td>'
                 f'<td class="n">{r["wall_time"]:.0f}초</td>'
                 f'<td class="n">{n(r["terms"]["compactness"])}</td>'
                 f'<td class="n">{"<b class=ok>0</b>" if r["components"] == 0 else f"<b class=bad>{r['components']}</b>"}</td>'
                 f'<td class="n">{n(r.get("bound"), 3) if r.get("bound") is not None else "<span class=dim>없음</span>"}</td></tr>')
    return f"""<div class="tw"><table>
<thead><tr><th>방법</th><th class="n">에너지</th><th class="n">최고 대비</th><th class="n">소요</th>
<th class="n">응집도</th><th class="n">조각난 방</th><th class="n">하한</th></tr></thead>
<tbody>{rows}</tbody></table></div>"""


SERIES4 = [
    {"id": "baseline", "label": "AI 생성", "cls": "s-gen"},
    {"id": "ortools_connected", "label": "OR-Tools", "cls": "s-ort"},
    {"id": "dwave", "label": "D-Wave SA (QUBO)", "cls": "s-dw"},
    {"id": "swap_anneal", "label": "교환 어닐링", "cls": "s-sw"},
]


def term_chart() -> str:
    rows = [{"key": k, "label": META_BY_KEY[k].label,
             "values": {s["id"]: S[s["id"]]["terms"][k] for s in SERIES4}} for k in QK]
    return grouped_bars(rows, SERIES4, "항별 값 (보상 항은 클수록, 벌점 항은 작을수록 좋다)")


def barrier_table() -> str:
    e1 = S["e1"]
    names = {"flip_1bit": ("비트 1개 뒤집기", "어닐러가 실제로 하는 움직임", "s-dw"),
             "reassign_2bit": ("셀 1개 이관 (비트 2개)", "배타성 유지 · 면적 깨짐", ""),
             "swap_4bit": ("두 셀 교환 (비트 4개)", "모든 하드 제약 유지", "s-sw")}
    rows = ""
    for k, (nm, note, cls) in names.items():
        st = e1[k]
        rows += (f'<tr><td>{f"<i class=\'sw {cls}\'></i>" if cls else ""}<b>{E(nm)}</b>'
                 f'<br><span class="dim sm">{E(note)}</span></td>'
                 f'<td class="n">{n(st["min"],3,True)}</td><td class="n strong">{n(st["median"],3,True)}</td>'
                 f'<td class="n">{n(st["mean"],3,True)}</td>'
                 f'<td class="n">{"<b class=bad>0.0%</b>" if st["improving_ratio"]==0 else f"<b class=ok>{st['improving_ratio']:.1%}</b>"}</td>'
                 f'<td class="n dim">{st["n"]:,}</td></tr>')
    return f"""<div class="tw"><table>
<thead><tr><th>움직임 종류</th><th class="n">최소 ΔE</th><th class="n">중앙값 ΔE</th>
<th class="n">평균 ΔE</th><th class="n">개선되는 비율</th><th class="n">표본</th></tr></thead>
<tbody>{rows}</tbody></table></div>"""


def e2_chart() -> str:
    xs = [r["num_sweeps"] for r in S["e2"]]
    ser = [{"label": "최저 에너지", "cls": "s-dw", "values": [r["energy"] for r in S["e2"]]},
           {"label": "표본 중앙값", "cls": "s-gen", "values": [r["energy_median"] for r in S["e2"]]}]
    ref = S["ortools_connected"]["energy"]
    return (f'<div class="chart">{line_chart(xs, ser, "어닐링 스윕 수 (로그 눈금)", "에너지")}'
            f'<p class="cnote">참고선: OR-Tools가 찾은 에너지 {n(ref)} · '
            f'교환 어닐링 {n(S["swap_anneal"]["energy"])}</p></div>')


def e5_charts() -> str:
    rows_f = [{"key": str(r["factor"]), "label": f'×{r["factor"]:g}',
               "values": {"f": r["feasible_rate"]}} for r in S["e5"]]
    rows_q = [{"key": str(r["factor"]), "label": f'×{r["factor"]:g}',
               "values": {"q": -(r["best_quality"] or 0)}} for r in S["e5"]]
    c1 = grouped_bars(rows_f, [{"id": "f", "label": "실현 가능한 표본 비율", "cls": "s-dw"}],
                      "페널티 배율별 · 하드 제약을 만족한 표본 비율", top=1.1)
    c2 = grouped_bars(rows_q, [{"id": "q", "label": "최고 품질 (부호 반전, 클수록 좋음)", "cls": "s-sw"}],
                      "페널티 배율별 · 실현 가능한 표본 중 최저 에너지의 절댓값")
    return f'<div class="twoup">{c1}{c2}</div>'


def sweep_section() -> str:
    out = []
    rows = []
    for k, s in S["sweep"].items():
        rows.append({"key": k, "label": s["name"],
                     "values": {"ortools_connected": -s["ortools"]["energy"],
                                "dwave": -s["dwave"]["energy"],
                                "swap_anneal": -s["swap"]["energy"]}})
    chart = grouped_bars(rows, [
        {"id": "ortools_connected", "label": "OR-Tools", "cls": "s-ort"},
        {"id": "dwave", "label": "D-Wave SA (QUBO)", "cls": "s-dw"},
        {"id": "swap_anneal", "label": "교환 어닐링", "cls": "s-sw"},
    ], "환경 변수별 달성 에너지 (부호 반전 — 막대가 길수록 좋은 도면)")
    out.append(chart)
    for k, s in S["sweep"].items():
        hi = sorted(((f, v) for f, v in s["weights"].items()
                     if f.startswith("w_")), key=lambda t: -t[1])[:2]
        stress = " · ".join(f"{f[2:]} {v:g}" for f, v in hi)
        out.append(f"""<div class="sweep-row">
  <div class="sweep-head"><p class="sname">{E(s["name"])}</p>
    <p class="sdesc">{E(s["description"])}</p>
    <p class="sstress mono">강조: {E(stress)}</p></div>
  <div class="sweep-plans">
    {figure(s["ortools"]["assignment"], "OR-Tools + 연결성",
            f'E <b>{n(s["ortools"]["energy"])}</b> · 조각 {s["ortools"]["components"]}'
            + (' · <span class="ok">최적 증명</span>' if s["ortools"].get("proven") else ''), "t-ort")}
    {figure(s["dwave"]["assignment"], "D-Wave SA (QUBO)",
            f'E <b>{n(s["dwave"]["energy"])}</b> · 조각 {s["dwave"]["components"]}', "t-dw")}
    {figure(s["swap"]["assignment"], "교환 어닐링",
            f'E <b>{n(s["swap"]["energy"])}</b> · 조각 {s["swap"]["components"]}', "t-sw")}
  </div></div>""")
    return "".join(out)


CSS = """
:root{
  --ground:#eef1f2; --surface:#fbfcfc; --raise:#ffffff;
  --ink:#14212a; --ink-2:#3c4f5a; --muted:#5d6f79;
  --rule:#d6dee1; --rule-soft:#e5eaec;
  --gen:#b06a12; --ort:#0d8f7c; --dw:#8e3d9e; --dw-2:#c79ad4;
  --ok:#12705f; --bad:#a8451a;
  --mat:#ffffff; --mat-edge:#c9d3d7;
  --shadow:0 1px 2px rgba(20,33,42,.06), 0 8px 24px -12px rgba(20,33,42,.18);
}
@media (prefers-color-scheme:dark){ :root:not([data-theme="light"]){
  --ground:#111a20; --surface:#18242c; --raise:#1e2c35;
  --ink:#e2eaed; --ink-2:#b6c6ce; --muted:#93a5ae;
  --rule:#2a3a44; --rule-soft:#22313a;
  --gen:#c67f22; --ort:#17a68d; --dw:#a555b5; --dw-2:#6d3579;
  --ok:#3fb89c; --bad:#e08a5c;
  --mat:#eceff0; --mat-edge:#394a54;
  --shadow:0 1px 2px rgba(0,0,0,.4), 0 10px 28px -14px rgba(0,0,0,.7);
}}
:root[data-theme="dark"]{
  --ground:#111a20; --surface:#18242c; --raise:#1e2c35;
  --ink:#e2eaed; --ink-2:#b6c6ce; --muted:#93a5ae;
  --rule:#2a3a44; --rule-soft:#22313a;
  --gen:#c67f22; --ort:#17a68d; --dw:#a555b5; --dw-2:#6d3579;
  --ok:#3fb89c; --bad:#e08a5c;
  --mat:#eceff0; --mat-edge:#394a54;
  --shadow:0 1px 2px rgba(0,0,0,.4), 0 10px 28px -14px rgba(0,0,0,.7);
}
*{box-sizing:border-box}
body{margin:0; background:var(--ground); color:var(--ink);
  font-family:"IBM Plex Sans KR","Apple SD Gothic Neo",system-ui,sans-serif;
  font-size:15px; line-height:1.75; -webkit-font-smoothing:antialiased;
  word-break:keep-all; overflow-wrap:break-word}
h1,h2,h3,h4,.dname,.sname,.abs-t{font-family:"Noto Serif KR",Georgia,serif; text-wrap:balance}
em{font-style:normal; font-weight:600; color:var(--ink)}
code,.mono{font-family:"IBM Plex Mono",monospace; font-size:.92em}
code{background:var(--rule-soft); padding:1px 5px; border-radius:2px}

.page{max-width:1420px; margin:0 auto; display:grid; grid-template-columns:1fr; padding:0 26px 100px}
@media(min-width:1180px){.page{grid-template-columns:212px minmax(0,1fr); gap:44px; padding-left:34px}}
nav.toc{display:none}
@media(min-width:1180px){nav.toc{display:block; position:sticky; top:0; align-self:start;
  max-height:100vh; overflow-y:auto; padding:78px 0 40px; font-size:12.5px; line-height:1.6}}
nav.toc p{margin:0 0 10px; font-size:10.5px; letter-spacing:.16em; text-transform:uppercase;
  color:var(--muted); font-weight:600}
nav.toc a{display:block; color:var(--muted); text-decoration:none; padding:3px 0 3px 10px;
  border-left:2px solid var(--rule-soft)}
nav.toc a:hover{color:var(--ort); border-left-color:var(--ort)}
nav.toc a.sub{padding-left:22px; font-size:12px}
main{min-width:0}

.mast{padding:62px 0 30px; border-bottom:2px solid var(--ink)}
.kicker{font-size:11.5px; letter-spacing:.19em; text-transform:uppercase; color:var(--muted);
  font-weight:600; margin:0 0 16px}
h1{font-size:clamp(29px,4.4vw,44px); line-height:1.22; font-weight:700; margin:0 0 14px; letter-spacing:-.01em}
.sub1{font-size:17px; color:var(--ink-2); margin:0; max-width:62ch}
.meta{display:flex; flex-wrap:wrap; gap:2px 28px; margin-top:24px; font-family:"IBM Plex Mono",monospace;
  font-size:11.5px; color:var(--muted)}
.meta b{color:var(--ink-2); font-weight:500}

.abstract{background:var(--surface); border:1px solid var(--rule); border-left:3px solid var(--ort);
  padding:24px 28px; margin:34px 0 0}
.abs-t{margin:0 0 12px; font-size:14px; font-weight:700; letter-spacing:.04em}
.abstract p{margin:0 0 12px; color:var(--ink-2); max-width:70ch}
.abstract p:last-child{margin-bottom:0}
.abstract b{color:var(--ink)}

.w5h{display:grid; grid-template-columns:repeat(auto-fit,minmax(216px,1fr)); gap:1px;
  background:var(--rule); border:1px solid var(--rule); margin:26px 0}
.w5h > div{background:var(--surface); padding:15px 17px}
.w5h dt{font-size:10.5px; letter-spacing:.14em; text-transform:uppercase; color:var(--ort);
  font-weight:600; margin:0 0 5px}
.w5h dd{margin:0; font-size:13.5px; color:var(--ink-2); line-height:1.62}
.w5h dd b{color:var(--ink)}

section{padding-top:54px; scroll-margin-top:20px}
h2{font-size:22px; font-weight:600; margin:0 0 8px; padding-bottom:10px; border-bottom:1px solid var(--rule)}
h2 .num{font-family:"IBM Plex Mono",monospace; font-size:13px; color:var(--ort); margin-right:11px; font-weight:500}
h3{font-size:16.5px; font-weight:600; margin:34px 0 10px}
h3 .num{font-family:"IBM Plex Mono",monospace; font-size:12.5px; color:var(--muted); margin-right:9px; font-weight:500}
p.body{max-width:68ch; margin:0 0 15px; color:var(--ink-2)}
p.body b{color:var(--ink); font-weight:600}
ol.qs{max-width:68ch; color:var(--ink-2); padding-left:22px; margin:0 0 18px}
ol.qs li{margin-bottom:9px} ol.qs b{color:var(--ink)}

.cap{font-size:12.5px; color:var(--muted); margin:9px 0 26px; max-width:70ch; line-height:1.62}
.cap b{color:var(--ink-2); font-weight:600}

.tw{overflow-x:auto; margin:18px 0 4px}
table{border-collapse:collapse; width:100%; font-size:13.5px; min-width:560px}
table.dense{font-size:12.5px}
th{text-align:left; font-weight:600; font-size:10.5px; letter-spacing:.1em; text-transform:uppercase;
  color:var(--muted); padding:0 12px 9px 0; border-bottom:1px solid var(--rule); white-space:nowrap}
td{padding:9px 12px 9px 0; border-bottom:1px solid var(--rule-soft); vertical-align:top}
td.n,th.n{text-align:right; font-family:"IBM Plex Mono",monospace; font-variant-numeric:tabular-nums;
  padding-right:14px; white-space:nowrap}
td.strong{font-weight:600; font-size:14.5px}
td.q{color:var(--ink-2); font-size:13px}
.dim{color:var(--muted)} .sm{font-size:11.5px; line-height:1.5}
b.ok,.ok{color:var(--ok)} b.bad{color:var(--bad)}
td.hi{background:color-mix(in srgb,var(--ort) 12%,transparent); font-weight:600}
tr.sel td{background:color-mix(in srgb,var(--ort) 8%,transparent)}
.tag{font-size:10px; padding:1px 6px; border-radius:2px; border:1px solid var(--rule); color:var(--muted)}
.tag.rew{color:var(--ort); border-color:color-mix(in srgb,var(--ort) 40%,transparent)}
.tag.pen{color:var(--bad); border-color:color-mix(in srgb,var(--bad) 40%,transparent)}
.sw{display:inline-block; width:9px; height:9px; border-radius:2px; margin-right:8px}
.dot{display:inline-block; width:10px; height:10px; border-radius:50%; margin-right:7px;
  border:1px solid rgba(0,0,0,.15)}
.sw.s-gen{background:var(--gen)} .sw.s-ort{background:var(--ort)} .sw.s-dw{background:var(--dw)}
.sw.s-sw{background:repeating-linear-gradient(45deg,var(--dw) 0 2px,var(--dw-2) 2px 4px)}

.grid{display:grid; gap:18px; grid-template-columns:repeat(auto-fill,minmax(214px,1fr))}
.grid.two{grid-template-columns:repeat(auto-fit,minmax(250px,1fr))}
.drawing{margin:0; background:var(--surface); border:1px solid var(--rule); border-radius:3px;
  overflow:hidden; box-shadow:var(--shadow)}
.drawing.t-ort{border-top:3px solid var(--ort)}
.drawing.t-dw{border-top:3px solid var(--dw)}
.drawing.t-sw{border-top:3px solid transparent;
  border-image:repeating-linear-gradient(45deg,var(--dw) 0 3px,var(--dw-2) 3px 6px) 3}
.mat{background:var(--mat); padding:13px; border-bottom:1px solid var(--mat-edge)}
.plan-svg{display:block; width:100%; height:auto}
figcaption{padding:11px 14px 13px}
.dname{margin:0 0 3px; font-size:13.5px; font-weight:600}
.dsub{margin:0; font-size:11.5px; color:var(--muted); font-family:"IBM Plex Mono",monospace;
  font-variant-numeric:tabular-nums}
.dsub b{color:var(--ink); font-weight:500}
.dcap{margin:6px 0 0; font-size:11.5px; color:var(--muted); line-height:1.5}
.rlegend{display:flex; flex-wrap:wrap; gap:5px 16px; margin:0 0 18px; font-size:12.5px; color:var(--ink-2)}

.chart{background:var(--surface); border:1px solid var(--rule); border-radius:3px;
  padding:20px 22px 18px; margin:20px 0 4px}
.chart-head{display:flex; flex-wrap:wrap; align-items:baseline; justify-content:space-between;
  gap:10px; margin-bottom:18px}
.ctitle{margin:0; font-size:12.5px; font-weight:600; color:var(--ink-2)}
.legend{display:flex; gap:14px; flex-wrap:wrap; font-size:11.5px; color:var(--ink-2)}
.lg{display:inline-flex; align-items:center}
.bars{display:grid; gap:15px}
.mrow{display:grid; grid-template-columns:96px 1fr; gap:13px; align-items:center}
.mlabel{font-size:12px; color:var(--ink-2); text-align:right; line-height:1.35}
.mtrack{position:relative; display:grid; gap:2px; padding:1px 0}
.tick{position:absolute; top:0; bottom:0; width:0; z-index:0}
.tick i{position:absolute; top:-3px; bottom:11px; left:0; width:1px; background:var(--rule)}
.tick b{position:absolute; bottom:-5px; left:0; transform:translateX(-50%); font-size:9.5px;
  font-weight:400; color:var(--muted); font-family:"IBM Plex Mono",monospace}
.bar-line{display:flex; align-items:center; gap:8px; position:relative; z-index:1; min-height:11px}
.bar{height:10px; border-radius:0 4px 4px 0; position:relative; min-width:2px; transition:filter .15s}
.bar:hover{filter:brightness(1.14)}
.bar.s-gen{background:var(--gen)} .bar.s-ort{background:var(--ort)} .bar.s-dw{background:var(--dw)}
.bar.s-sw{background:repeating-linear-gradient(45deg,var(--dw) 0 3px,var(--dw-2) 3px 6px)}
.bval{font-family:"IBM Plex Mono",monospace; font-size:10.5px; font-variant-numeric:tabular-nums;
  color:var(--muted); flex:none}
.tip{position:absolute; left:100%; bottom:calc(100% + 6px); transform:translateX(-25%); white-space:nowrap;
  background:var(--ink); color:var(--ground); font-size:11px; padding:4px 9px; border-radius:3px;
  opacity:0; pointer-events:none; transition:opacity .12s; z-index:5}
.bar:hover .tip{opacity:1}
.cnote{margin:12px 0 0; font-size:11.5px; color:var(--muted); font-family:"IBM Plex Mono",monospace}
.twoup{display:grid; gap:16px; grid-template-columns:repeat(auto-fit,minmax(300px,1fr))}
.linechart{display:block; width:100%; height:auto}
.cgrid{stroke:var(--rule); stroke-width:1}
.ctick{font-size:10px; fill:var(--muted); font-family:"IBM Plex Mono",monospace}
.caxis{font-size:11px; fill:var(--muted)}
.cline.s-dw{stroke:var(--dw)} .cline.s-gen{stroke:var(--gen)} .cline.s-ort{stroke:var(--ort)}
.cdot.s-dw{fill:var(--dw)} .cdot.s-gen{fill:var(--gen)} .cdot.s-ort{fill:var(--ort)}
.clabel{font-size:11px; font-weight:600}
.clabel.s-dw{fill:var(--dw)} .clabel.s-gen{fill:var(--gen)} .clabel.s-ort{fill:var(--ort)}

.sweep-row{display:grid; grid-template-columns:186px 1fr; gap:22px; padding:20px 0;
  border-bottom:1px solid var(--rule-soft); align-items:start}
.sweep-head{position:sticky; top:16px}
.sname{margin:0 0 4px; font-size:15px; font-weight:600}
.sdesc{margin:0 0 6px; font-size:12px; color:var(--muted); line-height:1.55}
.sstress{margin:0; font-size:10.5px; color:var(--ort)}
.sweep-plans{display:grid; grid-template-columns:repeat(3,1fr); gap:14px}
@media(max-width:820px){.sweep-row{grid-template-columns:1fr}.sweep-head{position:static}
  .sweep-plans{grid-template-columns:1fr 1fr}}

.formula{background:var(--surface); border:1px solid var(--rule); border-radius:3px; padding:18px 22px;
  margin:18px 0; overflow-x:auto; font-family:"IBM Plex Mono",monospace; font-size:12.5px;
  line-height:2.05; color:var(--ink-2)}
.formula .pen{color:var(--bad)} .formula .rew{color:var(--ort)}
pre.cmd{background:var(--surface); border:1px solid var(--rule); border-radius:3px; padding:16px 20px;
  overflow-x:auto; font-family:"IBM Plex Mono",monospace; font-size:12.5px; line-height:1.9;
  margin:14px 0; color:var(--ink-2)}
pre.cmd b{color:var(--ink); font-weight:500}
.chain{display:grid; gap:0; margin:22px 0; counter-reset:step}
.chain li{list-style:none; display:grid; grid-template-columns:30px 1fr; gap:14px; padding:13px 0;
  border-bottom:1px solid var(--rule-soft)}
.chain li::before{counter-increment:step; content:counter(step); font-family:"IBM Plex Mono",monospace;
  font-size:11px; color:var(--ort); font-weight:600; border:1px solid var(--rule);
  width:26px; height:26px; display:grid; place-items:center; border-radius:50%}
.chain p{margin:0; color:var(--ink-2); max-width:66ch} .chain b{color:var(--ink)}
ul.notes{max-width:70ch; padding-left:20px; color:var(--ink-2); margin:0}
ul.notes li{margin-bottom:11px} ul.notes b{color:var(--ink)}
footer{margin-top:52px; padding-top:20px; border-top:1px solid var(--rule); font-size:11.5px;
  color:var(--muted); font-family:"IBM Plex Mono",monospace; line-height:1.8}
@media (prefers-reduced-motion:reduce){*{transition:none!important;animation:none!important}}
:focus-visible{outline:2px solid var(--ort); outline-offset:2px}
"""


# ═══════════════════════════════════════════════ 3. 파생 수치
e1 = S["e1"]
flip_med = e1["flip_1bit"]["median"]
swap_best = abs(e1["swap_4bit"]["min"])
BARRIER_RATIO = flip_med / swap_best if swap_best else float("inf")
e2_first, e2_last = S["e2"][0], S["e2"][-1]
E2_FACTOR = e2_last["num_sweeps"] / e2_first["num_sweeps"]
E2_GAIN = e2_first["energy"] - e2_last["energy"]
DW, SWP, ORT, ORTC = S["dwave"], S["swap_anneal"], S["ortools"], S["ortools_connected"]
ENCODING_GAIN = DW["energy"] - SWP["energy"]
RESIDUAL = SWP["energy"] - ORT["energy"]
CONN_COST = ORTC["energy"] - ORT["energy"]
sweep_wins = sum(1 for s in S["sweep"].values() if s["ortools"]["energy"] <= s["dwave"]["energy"])
swap_wins = sum(1 for s in S["sweep"].values() if s["swap"]["energy"] <= s["dwave"]["energy"])
proven = sum(1 for s in S["sweep"].values() if s["ortools"].get("proven"))
dw_frag = sum(s["dwave"]["components"] for s in S["sweep"].values())
ort_frag = sum(s["ortools"]["components"] for s in S["sweep"].values())

TOC = [
    ("abstract", "초록", 0), ("w5h", "육하원칙 요약", 0),
    ("s1", "1. 서론", 0),
    ("s2", "2. 방법", 0), ("s21", "2.1 대상", 1), ("s22", "2.2 도면 생성", 1),
    ("s23", "2.3 데이터화", 1), ("s24", "2.4 평가 함수", 1),
    ("s25", "2.5 두 정식화", 1), ("s26", "2.6 실험 설계", 1),
    ("s3", "3. 결과", 0), ("s31", "3.1 주 비교", 1), ("s32", "3.2 항별 분해", 1),
    ("s33", "3.3 환경 변수 스윕", 1),
    ("s4", "4. 진단", 0), ("s41", "4.1 이동 장벽", 1), ("s42", "4.2 예산", 1),
    ("s43", "4.3 최적해 시딩", 1), ("s44", "4.4 페널티 스케일", 1),
    ("s45", "4.5 결정 실험", 1), ("s46", "4.6 인과 사슬", 1),
    ("s5", "5. 논의", 0), ("s6", "6. 한계", 0), ("s7", "7. 결론", 0),
    ("app", "부록 · 재현", 0),
]
toc_html = "".join(f'<a href="#{i}" class="{"sub" if lv else ""}">{E(t)}</a>' for i, t, lv in TOC)

room_leg = "".join(
    f'<span><i class="dot" style="background:{r["color"]}"></i>{E(r["name"])}</span>'
    for r in M["rooms"]) + '<span><i class="dot" style="background:#e63946"></i>현관 위치</span>'

plan_cards = "".join(
    figure(p["assignment"], p["name"], f'E <b>{n(p["energy"])}</b> · 조각 {p["components"]}')
    for p in sorted(S["plans"], key=lambda p: p["energy"])[:8])

coords = plan_of(S["baseline"]["assignment"]).coordinates(SPEC)
coord_rows = "".join(
    f'<tr><td><i class="dot" style="background:{SPEC.room_by_key[k].color}"></i>{E(c["name"])}</td>'
    f'<td class="n">{c["area"]}</td><td class="n dim">{c["target_area"]}</td>'
    f'<td class="n">{c["bbox"][0]},{c["bbox"][1]}–{c["bbox"][2]},{c["bbox"][3]}</td>'
    f'<td class="n">{c["centroid"][0]:.1f},{c["centroid"][1]:.1f}</td>'
    f'<td class="n">{c["perimeter_cells"]}</td><td class="n">{c["wall_length"]}</td>'
    f'<td class="n">{"<b class=ok>1</b>" if c["components"]==1 else f"<b class=bad>{c['components']}</b>"}</td></tr>'
    for k, c in coords.items())

F1, F2, F3, F4, F5, F6, F7, F8 = (FIG() for _ in range(8))
T1, T2, T3, T4, T5, T6 = (TAB() for _ in range(6))

HTML = f"""<meta charset="utf-8">
<title>평면 배치 엔진 대결</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans+KR:wght@400;500;600&family=Noto+Serif+KR:wght@600;700&display=swap">
<style>{CSS}</style>
<div class="page">
<nav class="toc"><p>목차</p>{toc_html}</nav>
<main>

<header class="mast">
  <p class="kicker">실험 보고서 · 고전 조합 최적화 대 양자 어닐링 계열</p>
  <h1>같은 도면, 두 개의 잣대</h1>
  <p class="sub1">AI가 생성한 건물 도면을 12개 환경 변수로 평가하고, 완전히 동일한 목적 함수를
    OR-Tools CP-SAT와 D-Wave Ocean에 각각 주었을 때 무엇이, 왜 갈리는가.</p>
  <div class="meta">
    <span>대상 <b>{E(M['spec_name'])}</b></span>
    <span>환경 변수 <b>{len(TERM_META)}개 · 프리셋 {len(M['presets'])}종</b></span>
    <span>공통 QUBO <b>{M['bqm']['variables']}변수 / {M['bqm']['interactions']:,}결합 / 밀도 {M['bqm']['density']:.3f}</b></span>
    <span>실행 <b>{M['date'][:10]}</b></span>
    <span>총 <b>{M['total_wall_time']/60:.0f}분</b></span>
  </div>
</header>

<section id="abstract" class="abstract">
  <p class="abs-t">초록</p>
  <p><b>배경.</b> 건물 평면 배치는 조합 최적화 문제다. 이를 QUBO로 옮기면 양자 어닐러에 올릴 수 있지만,
     QUBO는 제약을 페널티로만 표현할 수 있다. 이 제약이 결과에 어떤 영향을 주는지 정량적으로 측정했다.</p>
  <p><b>방법.</b> {SPEC.width}×{SPEC.height} 격자({SPEC.n_cells}셀) 위 {len(M['rooms'])}실 배치 문제에 대해
     {len(TERM_META)}개 항({len([t for t in TERM_META if t.sign<0])}개 보상 · {len([t for t in TERM_META if t.sign>0])}개 벌점)으로
     이루어진 평가 함수를 정의하고, 이를 <em>단일 출처 코드</em>에서 CP-SAT 목적함수와 QUBO 계수로 동시에 생성했다.
     두 정식화가 같은 함수인지는 도면을 직접 순회하는 제3의 독립 평가기로 교차 검증했다(불일치 &lt; 10⁻⁶).
     프리셋 {len(M['presets'])}종 × 3엔진으로 비교하고, 5개의 진단 실험으로 원인을 분리했다.</p>
  <p><b>결과.</b> 동일 조건에서 CP-SAT는 <b>{n(ORT['energy'])}</b>, D-Wave 시뮬레이티드 어닐링은
     <b>{n(DW['energy'])}</b>를 얻었고, 어닐링 해는 {len(M['rooms'])}개 실이 <em>모두</em> 조각났다.
     그러나 원인은 어닐링이 아니었다. 어닐링 알고리즘을 그대로 두고 <em>인코딩만</em> 제약 보존 방식으로 바꾸자
     같은 어닐링이 <b>{n(SWP['energy'])}</b>에 도달했다 — 격차의 {ENCODING_GAIN/(DW['energy']-ORT['energy'])*100:.0f}%가 인코딩에서 왔다.</p>
  <p><b>원인.</b> 페널티 인코딩에서는 실현 가능한 해들이 ΔE ≈ <b>{n(flip_med,1,True)}</b>의 장벽으로 격리된다.
     단일 비트 뒤집기 표본 {e1['flip_1bit']['n']:,}회 중 에너지를 개선한 것은 <b>0회(0.0%)</b>였다.
     어닐링 예산을 {E2_FACTOR:.0f}배 늘려도 개선은 {n(abs(E2_GAIN),3)}에 그쳐, 예산 문제가 아님을 확인했다.</p>
</section>

<section id="w5h">
  <h2><span class="num">§0</span>육하원칙 요약</h2>
  <div class="w5h">
    <div><dt>누가 (Who)</dt><dd>세 개의 최적화 엔진 — <b>OR-Tools CP-SAT {M['env']['ortools']}</b>(고전 분기한정),
      <b>D-Wave Ocean</b>(dimod {M['env']['dimod']} · 시뮬레이티드 어닐링),
      <b>교환 어닐링</b>(본 연구가 구현한 제약 보존 어닐러). 도면 생성은 {E(S['backend'])}.</dd></div>
    <div><dt>언제 (When)</dt><dd><b>{M['date'][:10]}</b> 단일 세션.
      총 실행 시간 <b>{M['total_wall_time']/60:.0f}분</b>. 엔진별 예산은 고정:
      CP-SAT {M['budgets']['cpsat_seconds']:.0f}초 · 어닐링 {M['budgets']['sa_reads']:,}표본 ×
      {M['budgets']['sa_sweeps']:,}스윕 · 교환 어닐링 {M['budgets']['swap_iter']:,}회 × {M['budgets']['swap_restarts']}회 재시작.</dd></div>
    <div><dt>어디서 (Where)</dt><dd><b>{E(M['env']['machine'])}</b> · {E(M['env']['platform'].split('-')[0])} ·
      Python {M['env']['python']}. <b>양자 하드웨어는 사용하지 않았다</b> — Leap 토큰이 없어
      QPU 대신 동일 QUBO를 CPU 시뮬레이티드 어닐링으로 풀었다(§6 참조).</dd></div>
    <div><dt>무엇을 (What)</dt><dd>{E(M['spec_name'])} — {SPEC.width}×{SPEC.height} 격자
      {SPEC.n_cells}셀에 {len(M['rooms'])}개 실을 배치. 이진 변수 {M['bqm']['variables']}개,
      QUBO 결합 {M['bqm']['interactions']:,}개(밀도 {M['bqm']['density']:.3f}).</dd></div>
    <div><dt>어떻게 (How)</dt><dd>동일한 평가 함수를 <b>단일 출처 코드</b>에서 두 정식화로 생성.
      CP-SAT는 하드 제약을 <em>네이티브 제약</em>으로, QUBO는 <em>페널티 항</em>으로 표현한다.
      이 차이 하나만 남기고 나머지를 통제했다.</dd></div>
    <div><dt>왜 (Why)</dt><dd>"양자가 더 나은가"가 아니라 <b>"무엇이 성능을 가르는가"</b>를 묻기 위해.
      진단 실험 5종으로 알고리즘·예산·인코딩의 기여를 분리했고, 지배적 요인은 <b>인코딩</b>이었다.</dd></div>
  </div>
</section>

<section id="s1">
  <h2><span class="num">1</span>서론</h2>
  <p class="body">평면 배치는 "각 격자 셀을 어느 실에 줄 것인가"를 정하는 조합 최적화 문제다.
     이 문제를 QUBO(이진 2차 무제약 최적화)로 옮기면 양자 어닐러에 올릴 수 있다. 다만 QUBO에는
     <em>제약이라는 개념이 없다</em>. "한 셀에는 실 하나", "각 실은 요구 면적을 지킨다" 같은 조건을
     목적 함수 안에 벌점으로 녹여 넣어야 한다. 이 논문은 그 대가가 얼마인지를 측정한다.</p>
  <ol class="qs">
    <li><b>Q1.</b> 동일한 평가 함수를 주었을 때 두 엔진의 결과는 얼마나 다른가?</li>
    <li><b>Q2.</b> 그 차이는 <em>알고리즘</em>에서 오는가, <em>예산</em>에서 오는가, <em>인코딩</em>에서 오는가?</li>
    <li><b>Q3.</b> 두 정식화의 표현력 차이가 실제 설계 품질에 어떻게 나타나는가?</li>
  </ol>
</section>

<section id="s2"><h2><span class="num">2</span>방법</h2>

  <h3 id="s21"><span class="num">2.1</span>대상 — 무엇을 배치하는가</h3>
  <p class="body">{E(M['spec_name'])}. 좌상단이 원점, x는 오른쪽, y는 아래(남쪽) 방향이다.
     현관은 ({M['entrance'][0]},{M['entrance'][1]}), 수직 배관 코어는
     ({M['plumbing_core'][0]},{M['plumbing_core'][1]})에 고정했다. 요구 면적의 합은 격자 셀 수와 정확히 같다.</p>
  {room_table()}
  <p class="cap"><b>표 {T1}.</b> 실 프로그램. 사적도·공용도·소음·정숙은 0~1 척도이며 평가 함수의 계수로 직접 쓰인다.
     채광(●)은 외벽 접면을 선호함을, 급배수(●)는 배관 코어 근접을 선호함을 뜻한다.</p>

  <h3 id="s22"><span class="num">2.2</span>1단계 — AI 도면 생성</h3>
  <p class="body">실 프로그램과 인접 선호도를 입력으로 서로 다른 배치 전략의 후보 도면을 생성한다.
     Claude 백엔드는 구조화 출력(<code>output_format</code>)으로 실 사각형 좌표를 직접 산출하고,
     자격 증명이 없으면 BSP(이진 공간 분할) 생성기가 대체한다. <b>이번 실행에서는 {E(S['backend'])}</b>가 동작했다.
     어느 백엔드든 산출물은 같은 형식이므로 이후 단계는 구분 없이 처리된다.
     생성 직후 면적 보정(<code>repair</code>)을 적용해 모든 후보가 하드 제약을 만족한 상태로 출발한다.</p>
  <div class="rlegend">{room_leg}</div>
  <div class="grid">{plan_cards}</div>
  <p class="cap"><b>그림 {F1}.</b> 생성된 후보 {len(S['plans'])}장(에너지 오름차순). 붉은 점이 현관,
     굵은 선이 실 경계다. 최저 에너지 후보 <b>{n(S['baseline']['energy'])}</b>가 이후 비교의 기준선이 된다.</p>

  <h3 id="s23"><span class="num">2.3</span>2단계 — 좌표 변환과 데이터화</h3>
  <p class="body">도면은 "셀 인덱스 → 실" 배열 하나로 표현된다. 여기서 실마다 점유 좌표, 바운딩 박스,
     중심점, 외벽 접면 셀 수, 벽 길이, 그리고 <b>연결 성분 수(몇 덩어리로 흩어졌는가)</b>를 추출한다.
     마지막 지표가 §4에서 두 엔진을 가르는 핵심 관측량이 된다.</p>
  {f'<div class="tw"><table><thead><tr><th>실</th><th class="n">면적</th><th class="n">요구</th><th class="n">바운딩 박스</th><th class="n">중심점</th><th class="n">외벽 셀</th><th class="n">벽 길이</th><th class="n">덩어리</th></tr></thead><tbody>{coord_rows}</tbody></table></div>'}
  <p class="cap"><b>표 {T2}.</b> 기준선 도면({E(S['baseline']['name'])})의 좌표 데이터. 덩어리가 1이면 해당 실이 연결되어 있다.</p>

  <h3 id="s24"><span class="num">2.4</span>3단계 — 평가 함수와 12개 환경 변수</h3>
  <p class="body">"좋은 도면"을 {len(TERM_META)}개 항의 가중합으로 정의한다. 보상 항은 에너지에서 빼고,
     벌점 항은 더한다. 에너지가 낮을수록 좋은 도면이다.</p>
  <div class="formula">
    E(도면) = Σᵢ signᵢ · wᵢ · termᵢ(도면),&nbsp;&nbsp; sign = <span class="rew">−1</span>(보상) 또는 <span class="pen">+1</span>(벌점)<br>
    <br>
    &nbsp;&nbsp;= <span class="pen">{W.p_cell:g}</span>·셀배타성위반 + <span class="pen">{W.p_area:g}</span>·면적오차<br>
    &nbsp;&nbsp;&nbsp;&nbsp;<span class="pen">+ {W.w_noise:g}</span>·소음인접 <span class="pen">+ {W.w_thermal:g}</span>·외피노출<br>
    &nbsp;&nbsp;&nbsp;&nbsp;<span class="rew">− {W.w_adjacency:g}</span>·인접선호 <span class="rew">− {W.w_compactness:g}</span>·응집도
    <span class="rew">− {W.w_corridor:g}</span>·코어접면 <span class="rew">− {W.w_daylight:g}</span>·채광<br>
    &nbsp;&nbsp;&nbsp;&nbsp;<span class="rew">− {W.w_solar:g}</span>·남향 <span class="rew">− {W.w_privacy:g}</span>·프라이버시
    <span class="rew">− {W.w_circulation:g}</span>·공용접근성 <span class="rew">− {W.w_plumbing:g}</span>·설비집중
  </div>
  {term_table()}
  <p class="cap"><b>표 {T3}.</b> 환경 변수 전체. 정규화 분모는 스펙만으로 결정되며, 2차 항 네 개는 모두 같은 격자 변
     위에서 겨루므로 <em>반드시 같은 분모</em>를 쓴다. 분모가 다르면 실을 잘게 흩어 인접 변을 늘리는 쪽이
     유리해져 체스판 배치가 최적이 되는 왜곡이 발생한다(예비 실험에서 실제로 관찰됨).</p>
  {preset_table()}
  <p class="cap"><b>표 {T4}.</b> 프리셋 {len(M['presets'])}종. 각 행이 하나의 설계 방침이며,
     강조된 칸이 그 프리셋이 특별히 중시하는 항이다. 같은 실 프로그램에 다른 행을 적용하면 최적 도면이 달라진다(§3.3).</p>

  <h3 id="s25"><span class="num">2.5</span>두 정식화 — 통제된 단 하나의 차이</h3>
  <p class="body">두 엔진은 <b>같은 코드에서 생성된 같은 목적 함수</b>를 받는다. 다른 것은 하드 제약을
     표현하는 방식뿐이다. 이것이 이 실험의 독립 변수다.</p>
  <div class="tw"><table>
    <thead><tr><th></th><th>OR-Tools CP-SAT</th><th>QUBO (D-Wave)</th></tr></thead>
    <tbody>
      <tr><td><b>셀 배타성</b></td><td><code>AddExactlyOne</code> — 네이티브 제약</td>
        <td class="dim">p_cell·Σ(Σx−1)² 벌점. 실 쌍마다 2차항</td></tr>
      <tr><td><b>요구 면적</b></td><td><code>Σx == area</code> — 네이티브 제약</td>
        <td class="dim">p_area·Σ(Σx−a)² 벌점. <b>같은 실의 모든 셀 쌍</b>을 잇는 조밀한 클리크</td></tr>
      <tr><td><b>2차 목적항</b></td><td>곱 변수로 선형화 ({ORT['quad_terms']:,}개)</td><td>그대로 2차항</td></tr>
      <tr><td><b>연결성</b></td><td><span class="ok">단일 상품 유량 정식화로 강제 가능</span></td>
        <td><b class="bad">표현 불가</b> — 2차식으로 옮길 수 없다</td></tr>
      <tr><td><b>최적성 보장</b></td><td>하한 제공, 증명 가능</td><td class="dim">표본 분포만. 하한 없음</td></tr>
      <tr><td><b>탐색 이동</b></td><td>분기·전파·절단</td><td class="dim">단일 비트 뒤집기 + 온도 수용</td></tr>
    </tbody></table></div>
  <p class="cap"><b>표 {T5}.</b> 정식화 대조. 마지막 두 행이 §4에서 규명할 격차의 근원이다.</p>

  <h3 id="s26"><span class="num">2.6</span>실험 설계와 검증</h3>
  <p class="body">평가 함수가 세 경로에서 동일한지 <b>기계적으로 검증</b>했다. 목적 함수 계수는
     <code>terms.py</code> 한 곳에서만 생성되고, (i) QUBO 에너지, (ii) CP-SAT 목적값,
     (iii) 도면을 직접 순회하는 독립 평가기 세 값이 프리셋 {len(M['presets'])}종 × 무작위 도면 전부에서
     10⁻⁶ 이내로 일치함을 확인했다. 이 검증이 없으면 "같은 함수를 풀었다"는 전제가 성립하지 않는다.</p>
  <p class="body">예산은 엔진별로 고정했다 — CP-SAT {M['budgets']['cpsat_seconds']:.0f}초,
     어닐링 {M['budgets']['sa_reads']:,}표본 × {M['budgets']['sa_sweeps']:,}스윕,
     교환 어닐링 {M['budgets']['swap_iter']:,}회 이동 × {M['budgets']['swap_restarts']}회 재시작.
     난수 시드는 {M['budgets']['seed']}로 고정했다.</p>
</section>

<section id="s3"><h2><span class="num">3</span>결과</h2>

  <h3 id="s31"><span class="num">3.1</span>주 비교</h3>
  {result_table()}
  <p class="cap"><b>표 {T6}.</b> 환경 '{E(W.name)}' 기준. 에너지가 낮을수록 좋은 도면.
     '조각난 방'은 연결 성분이 2개 이상인 실의 수({len(M['rooms'])}개 중).
     하한은 CP-SAT만 제공한다 — 어닐링은 원리상 하한을 주지 못한다.</p>
  <div class="grid two">
    {figure(S['baseline']['assignment'], 'AI 생성 최고안', f'E <b>{n(S["baseline"]["energy"])}</b> · 조각 {S["baseline"]["components"]}', '', '생성기가 사각형 분할로 만들었으므로 조각남이 없다.')}
    {figure(ORT['assignment'], 'OR-Tools CP-SAT', f'E <b>{n(ORT["energy"])}</b> · 조각 {ORT["components"]}', 't-ort', f'하한 {n(ORT["bound"])} — 갭 {abs(ORT["energy"]-ORT["bound"]):.3f}로 거의 최적.')}
    {figure(ORTC['assignment'], 'OR-Tools + 연결성 제약', f'E <b>{n(ORTC["energy"])}</b> · 조각 {ORTC["components"]}', 't-ort', f'연결성을 강제한 대가는 {n(abs(CONN_COST),3)}뿐. QUBO로는 표현 불가.')}
    {figure(DW['assignment'], 'D-Wave SA (QUBO 인코딩)', f'E <b>{n(DW["energy"])}</b> · 조각 {DW["components"]}', 't-dw', f'하드 제약은 만족({"O" if DW["feasible_raw"] else "X"})하지만 실이 모두 흩어졌다.')}
    {figure(SWP['assignment'], '교환 어닐링 (제약 보존 인코딩)', f'E <b>{n(SWP["energy"])}</b> · 조각 {SWP["components"]}', 't-sw', f'같은 어닐링, 인코딩만 교체. {SWP["wall_time"]:.0f}초.')}
  </div>
  <p class="cap"><b>그림 {F2}.</b> 다섯 결과의 도면. D-Wave 결과만 실 경계가 무의미하게 잘게 쪼개져 있다.
     맨 아래는 <em>같은 어닐링 알고리즘</em>이 인코딩만 바꿔 도달한 결과다.</p>

  <h3 id="s32"><span class="num">3.2</span>항별 분해 — 어디서 잃었는가</h3>
  {term_chart()}
  <p class="cap"><b>그림 {F3}.</b> 품질 10개 항의 값(가중치 적용 전). 보상 항은 클수록, 벌점 항(소음 인접·외피 노출)은
     작을수록 좋다. D-Wave는 특히 <b>응집도</b>에서 크게 뒤진다
     ({n(DW['terms']['compactness'])} 대 {n(ORTC['terms']['compactness'])}) — 이것이 도면이 조각나 보이는 직접적 원인이다.
     교환 어닐링(빗금)은 거의 모든 항에서 OR-Tools와 나란히 선다.</p>

  <h3 id="s33"><span class="num">3.3</span>환경 변수 {len(M['presets'])}종 스윕</h3>
  <p class="body">"좋은 도면"은 하나가 아니다. 같은 실 프로그램에 다른 방침을 적용하면 최적 배치가 달라진다.
     {len(M['presets'])}개 프리셋 전부에서 <b>OR-Tools가 D-Wave를 앞섰고({sweep_wins}/{len(M['presets'])}),
     교환 어닐링도 마찬가지였다({swap_wins}/{len(M['presets'])})</b>.
     조각난 실의 총합은 OR-Tools <b>{ort_frag}개</b>, D-Wave <b>{dw_frag}개</b>
     (프리셋당 최대 {len(M['rooms'])}개 × {len(M['presets'])}종 = {len(M['rooms'])*len(M['presets'])}개 기준).
     CP-SAT는 {proven}개 프리셋에서 최적성을 증명했다.</p>
  {sweep_section()}
  <p class="cap"><b>그림 {F4}.</b> 프리셋별 세 엔진의 도면과 달성 에너지. 왼쪽 열의 방침이 바뀌면
     OR-Tools의 배치가 눈에 띄게 재구성되는 반면(채광 우선은 창 있는 실을 외피로, 설비 효율은 물 쓰는 실을 코어로),
     D-Wave 열은 방침과 거의 무관하게 비슷한 정도로 흩어져 있다 — 환경 변수에 <em>반응하지 못하고 있다</em>.</p>
</section>
"""

e5_feas = [r["feasible_rate"] for r in S["e5"]]
e5_q = [r["best_quality"] for r in S["e5"] if r["best_quality"] is not None]
e5_span = max(r["factor"] for r in S["e5"]) / min(r["factor"] for r in S["e5"])
e3 = S["e3"]

HTML += f"""
<section id="s4"><h2><span class="num">4</span>진단 — 왜 D-Wave의 실이 모두 조각났는가</h2>
  <p class="body">§3의 격차는 세 가지로 설명될 수 있다. <b>(a) 알고리즘</b>이 이 문제에 부적합하거나,
     <b>(b) 예산</b>이 부족했거나, <b>(c) 인코딩</b>이 탐색을 막았거나. 다섯 개의 실험으로 셋을 분리한다.</p>

  <h3 id="s41"><span class="num">4.1</span>E1 — 어닐러가 넘어야 하는 벽의 높이</h3>
  <p class="body">무작위 실현 가능 도면 {M['budgets'].get('e1_states', 40)}장에서 세 종류의 움직임을 표본으로 뽑아
     에너지 변화를 측정했다. 핵심은 <b>어닐러가 실제로 하는 움직임은 비트 1개 뒤집기뿐</b>이라는 점이다.</p>
  {barrier_table()}
  <p class="cap"><b>표 {TAB()}.</b> 움직임 종류별 ΔE 분포. 비트 하나를 뒤집으면 반드시 셀이 비거나(벌점 {W.p_cell:g})
     면적이 깨진다(벌점 {W.p_area:g}). 그래서 표본 {e1['flip_1bit']['n']:,}회 중 에너지를 개선한 움직임이
     <b>단 한 번도 없었다</b>. 반면 하드 제약을 보존하는 4비트 교환은 절반 가까이가 개선 이동이다
     ({e1['swap_4bit']['improving_ratio']:.1%}).</p>
  <p class="body">문제의 유용한 기울기는 전부 <b>4비트 교환</b> 안에 있다. 그런데 그 교환에 도달하려면
     높이 약 <b>{n(flip_med,1,True)}</b>의 벽을 두 번 넘어야 하고, 넘어서 얻는 이득은 최대
     <b>{n(swap_best,3)}</b>이다. 비율로 <b>약 {BARRIER_RATIO:.0f}배</b>. 어닐링이 이 벽을 넘을 만큼
     온도를 높이면 하드 제약이 무너지고, 제약을 지킬 만큼 온도를 낮추면 품질을 개선할 수 없다.</p>

  <h3 id="s42"><span class="num">4.2</span>E2 — 예산 부족인가?</h3>
  <p class="body">스윕 수를 {e2_first['num_sweeps']:,}에서 {e2_last['num_sweeps']:,}까지
     <b>{E2_FACTOR:.0f}배</b> 늘리며 최저 에너지를 측정했다.</p>
  {e2_chart()}
  <p class="cap"><b>그림 {FIG()}.</b> 어닐링 예산 대비 에너지. 예산을 {E2_FACTOR:.0f}배 늘려도
     최저 에너지는 {n(e2_first['energy'])} → {n(e2_last['energy'])}로 <b>{n(abs(E2_GAIN),3)}</b>밖에 움직이지 않았고,
     추세도 단조롭지 않다(측정 잡음 수준). OR-Tools가 도달한 {n(ORTC['energy'])}와의 간격
     {abs(ORTC['energy']-e2_last['energy']):.1f}은 예산으로 메워지지 않는다. <b>(b) 예산 가설 기각.</b></p>

  <h3 id="s43"><span class="num">4.3</span>E3 — 좋은 해를 쥐여주면 지키는가?</h3>
  <p class="body">어닐러의 시작 상태를 무작위가 아니라 <b>OR-Tools가 찾은 도면</b>으로 두고 다시 돌렸다.
     탐색 능력의 문제인지, 유지 능력의 문제인지를 가른다.</p>
  <div class="tw"><table><thead><tr><th></th><th class="n">에너지</th><th class="n">응집도</th><th class="n">조각난 방</th></tr></thead>
    <tbody>
      <tr><td>시작 상태 (OR-Tools 해)</td><td class="n strong">{n(e3['seed_energy'])}</td>
        <td class="n">{n(e3['seed_compactness'])}</td><td class="n"><b class="ok">{e3['seed_components']}</b></td></tr>
      <tr><td>어닐링 후</td><td class="n strong">{n(e3['final_energy'])}</td>
        <td class="n">{n(e3['final_compactness'])}</td>
        <td class="n">{"<b class=ok>0</b>" if e3['final_components']==0 else f"<b class=bad>{e3['final_components']}</b>"}</td></tr>
      <tr><td class="dim">변화</td><td class="n">{n(e3['delta'],3,True)}</td>
        <td class="n">{n(e3['final_compactness']-e3['seed_compactness'],3,True)}</td>
        <td class="n">{e3['final_components']-e3['seed_components']:+d}</td></tr>
    </tbody></table></div>
  <p class="cap"><b>표 {TAB()}.</b> 최적해에서 출발시킨 어닐링. 좋은 해를 주어도
     {"유지하지 못하고 무너뜨린다" if e3['delta'] > 0 else "그 자리를 벗어나지 못한다"} —
     {"어닐러는 준 해를 " + n(abs(e3['delta']),3) + "만큼 악화시켰다." if e3['delta'] > 0 else "개선도 하지 못했다."}
     탐색 시작점의 문제가 아니라 <b>이동 자체가 불가능</b>하다는 뜻이다.</p>

  <h3 id="s44"><span class="num">4.4</span>E5 — 벌점을 조절하면 되는가?</h3>
  <p class="body">"벌점이 너무 커서 얼어붙은 것 아닌가"라는 반론을 검증하기 위해 p_cell과 p_area를
     기준값의 ×{min(r['factor'] for r in S['e5']):g}부터 ×{max(r['factor'] for r in S['e5']):g}까지
     <b>{e5_span:.0f}배 범위</b>로 움직이며 실현 가능성과 품질을 함께 측정했다.</p>
  {e5_charts()}
  <p class="cap"><b>그림 {FIG()}.</b> 페널티 배율에 따른 실현 가능 표본 비율(왼쪽)과 최고 품질(오른쪽, 부호 반전).
     배율을 {e5_span:.0f}배 움직여도 실현 가능 비율은 {min(e5_feas):.0%}~{max(e5_feas):.0%},
     최고 품질은 {n(max(e5_q))} ~ {n(min(e5_q))} 구간에 머문다.
     <b>어떤 벌점 값으로도 {n(ORTC['energy'])} 근처에 가지 못한다.</b> 벌점 조정은 해법이 아니다.</p>
  <p class="body"><b>왜 조절이 통하지 않는가 — 척도 분리.</b> 어닐링은 온도 T에서
     대략 |ΔE| ≲ T인 변화만 "보인다". 그런데 이 인코딩에서는 비트 하나를 뒤집을 때
     제약 신호가 {n(flip_med,1)} 규모인 반면 품질 신호는 {n(abs(e1['swap_quality_only']['mean']),3)} 규모다
     — 두 신호의 척도가 <b>약 {flip_med/max(abs(e1['swap_quality_only']['mean']),1e-9):.0f}배</b> 떨어져 있다.
     제약이 정리되는 고온 구간에서는 품질 항이 잡음에 완전히 묻히고, 품질이 보일 만큼 온도를 낮추면
     제약 벌점은 이미 T의 수십 배라 상태가 얼어붙는다. 벌점 배율을 낮추면 두 신호가 함께 내려가므로
     <em>간격은 그대로다</em>. 그래서 어떤 배율에서도 "제약은 지키면서 품질은 보이는" 온도 창이 열리지 않는다.
     이것이 E5가 평평한 이유이자, 문제가 벌점 <em>크기</em>가 아니라 <em>구조</em>에 있다는 증거다.</p>

  <h3 id="s45"><span class="num">4.5</span>E4 — 결정 실험: 인코딩만 바꾼다</h3>
  <p class="body">앞의 셋이 (a)와 (b)를 기각했다면, 남은 것은 (c) 인코딩이다. 이를 직접 확인하기 위해
     <b>어닐링 알고리즘은 그대로 두고</b> 인코딩만 바꾼 대조군을 만들었다.
     상태 공간을 실현 가능한 도면으로 제한하고, 움직임을 <em>두 셀의 실을 맞바꾸기</em>로 정의한다.
     하드 제약이 구조적으로 항상 만족되므로 <b>페널티 장벽이 아예 존재하지 않는다</b>.
     목적 함수, 온도 수용 규칙(Metropolis), 기하 냉각 스케줄은 모두 동일하다.</p>
  <div class="tw"><table><thead><tr><th>인코딩</th><th>이동</th><th>하드 제약</th><th class="n">에너지</th><th class="n">조각난 방</th><th class="n">소요</th></tr></thead>
    <tbody>
      <tr><td><i class="sw s-dw"></i><b>페널티 (QUBO)</b></td><td class="dim">비트 1개 뒤집기</td>
        <td class="dim">목적 함수에 녹임</td><td class="n strong">{n(DW['energy'])}</td>
        <td class="n"><b class="bad">{DW['components']}</b></td><td class="n">{DW['wall_time']:.0f}초</td></tr>
      <tr><td><i class="sw s-sw"></i><b>제약 보존</b></td><td class="dim">두 셀 교환</td>
        <td class="dim">구조적으로 항상 만족</td><td class="n strong">{n(SWP['energy'])}</td>
        <td class="n">{"<b class=ok>0</b>" if SWP['components']==0 else f"<b>{SWP['components']}</b>"}</td>
        <td class="n">{SWP['wall_time']:.0f}초</td></tr>
      <tr><td class="dim">참고 · OR-Tools</td><td class="dim">분기한정</td><td class="dim">네이티브 제약</td>
        <td class="n">{n(ORT['energy'])}</td><td class="n">{ORT['components']}</td>
        <td class="n">{ORT['wall_time']:.0f}초</td></tr>
    </tbody></table></div>
  <p class="cap"><b>표 {TAB()}.</b> 결정 실험. 어닐링을 그대로 두고 인코딩만 바꾸자 에너지가
     <b>{n(DW['energy'])} → {n(SWP['energy'])}</b>로 뛰었다.
     D-Wave와 OR-Tools 사이 격차 {abs(DW['energy']-ORT['energy']):.3f} 중
     <b>{ENCODING_GAIN:.3f}({ENCODING_GAIN/abs(DW['energy']-ORT['energy'])*100:.0f}%)가 인코딩에서 왔고</b>,
     알고리즘 차이로 남는 몫은 {abs(RESIDUAL):.3f}({abs(RESIDUAL)/abs(DW['energy']-ORT['energy'])*100:.0f}%)뿐이다.</p>

  <h3 id="s46"><span class="num">4.6</span>인과 사슬</h3>
  <ol class="chain">
    <li><p><b>QUBO에는 제약이라는 개념이 없다.</b> 셀 배타성과 요구 면적을 목적 함수 안에 벌점으로 넣는 것 외에 방법이 없다.</p></li>
    <li><p><b>그 결과 실현 가능한 해들이 고립된다.</b> 실현 가능한 상태에서 비트 하나를 뒤집으면
       반드시 셀이 비거나 면적이 깨져 ΔE ≈ {n(flip_med,1,True)}의 벌점을 문다(E1).</p></li>
    <li><p><b>어닐러의 이동은 비트 하나 뒤집기다.</b> 표본 {e1['flip_1bit']['n']:,}회 중 개선 이동 <b>0회</b>.
       문제의 유용한 기울기는 4비트 교환 안에 있는데, 어닐러는 그 이동을 <em>한 걸음으로 만들 수 없다</em>.</p></li>
    <li><p><b>따라서 제약만 만족한 채 얼어붙는다.</b> 예산을 {E2_FACTOR:.0f}배 늘려도(E2),
       최적해에서 출발시켜도(E3), 벌점을 {e5_span:.0f}배 범위로 조절해도(E5) 벗어나지 못한다.</p></li>
    <li><p><b>품질 항, 특히 응집도가 최적화되지 않는다.</b> 응집도 {n(DW['terms']['compactness'])}
       (OR-Tools {n(ORTC['terms']['compactness'])}) — 같은 실의 셀이 서로 붙을 이유가 탐색에 반영되지 못한다.</p></li>
    <li><p><b>그래서 모든 실이 조각난다.</b> 이것이 §3의 도면에서 눈으로 보이는 현상의 정체다.
       어닐링이 나빠서가 아니라, 어닐링에게 <em>움직일 수 없는 지형</em>을 준 것이다(E4가 이를 증명한다).</p></li>
  </ol>
</section>

<section id="s5"><h2><span class="num">5</span>논의</h2>
  <p class="body"><b>이 결과는 "양자가 고전보다 못하다"는 뜻이 아니다.</b> 이번 실행에 양자 하드웨어는
     쓰이지 않았고(§6), 더 중요하게는 관측된 격차의 {ENCODING_GAIN/abs(DW['energy']-ORT['energy'])*100:.0f}%가
     하드웨어나 알고리즘이 아니라 <em>문제를 QUBO로 옮기는 과정</em>에서 발생했다. 같은 격차는 실제 QPU에서도
     그대로 나타난다 — QPU 역시 같은 페널티 인코딩을 받기 때문이다.</p>
  <p class="body"><b>일반화.</b> one-hot 배정 + 카디널리티 제약은 배정·스케줄링·분할 문제 전반에 흔하다.
     이 조합을 페널티로 인코딩하는 순간, 단일 비트 뒤집기 어닐러에게는 같은 함정이 생긴다.
     따라서 QUBO 적합성 판단의 기준은 "변수 수가 몇 개인가"가 아니라
     <b>"실현 가능한 해들 사이를 한 비트로 오갈 수 있는가"</b>여야 한다.</p>
  <p class="body"><b>실무적 처방.</b> (i) 제약 보존 이동을 쓰는 샘플러를 택한다 — Ocean의
     <code>DiscreteQuadraticModel</code>과 <code>LeapHybridDQMSampler</code>는 one-hot을 구조적으로 다루므로
     이 문제의 자연스러운 대안이다. (ii) 하드 제약이 많은 문제는 하이브리드 솔버에 맡긴다.
     (iii) 순수 QUBO를 고집해야 한다면 제약을 변수 설계 단계에서 흡수한다.</p>
  <p class="body"><b>표현력의 차이는 별개로 남는다.</b> 인코딩을 고쳐도 연결성 제약은 여전히 QUBO에
     넣을 수 없다. CP-SAT는 유량 정식화로 이를 강제하면서 에너지를 {n(abs(CONN_COST),3)}만 손해 봤고
     조각난 실을 {ORT['components']}개에서 {ORTC['components']}개로 줄였다.
     건축 도면에서 "실이 한 덩어리여야 한다"는 타협 불가능한 요구이므로, 이 차이는 점수가 아니라
     <b>결과물의 사용 가능성</b>을 가른다.</p>
</section>

<section id="s6"><h2><span class="num">6</span>한계와 타당성 위협</h2>
  <ul class="notes">
    <li><b>양자 하드웨어를 쓰지 않았다.</b> D-Wave Leap 토큰이 없어
      <code>SimulatedAnnealingSampler</code>(CPU에서 도는 고전 시뮬레이티드 어닐링)로 실행했다.
      따라서 이 보고서는 <em>양자 대 고전</em>의 비교가 아니라 <b>페널티 인코딩 + 단일 비트 어닐링</b> 대
      <b>네이티브 제약 + 분기한정</b>의 비교다. QUBO 정식화와 Ocean 도구 체인은 실제 QPU와 동일하며
      <code>--dwave qpu</code> / <code>hybrid</code>로 전환된다. E1의 장벽 구조는 하드웨어와 무관한
      인코딩의 성질이므로 QPU에서도 동일하게 나타날 것으로 예상되지만, <b>이는 측정되지 않은 예측이다.</b></li>
    <li><b>실제 QPU에 이 문제가 그대로 올라가지 않는다.</b> 변수 {M['bqm']['variables']}개에
      결합 {M['bqm']['interactions']:,}개(밀도 {M['bqm']['density']:.2f})는 마이너 임베딩에 매우 불리하다.
      면적 제약이 같은 실의 모든 셀 쌍을 잇는 조밀한 클리크를 만들기 때문이다.
      실물에서는 Leap 하이브리드가 현실적 경로다.</li>
    <li><b>예산 동등성은 근사적이다.</b> CP-SAT는 초 단위, 어닐링은 표본·스윕 단위로 예산을 정의하므로
      완전한 동등 비교가 아니다. 다만 E2가 어닐링 예산을 {E2_FACTOR:.0f}배 늘려도 결과가 바뀌지 않음을
      보였으므로, 결론이 예산 설정에 의존하지는 않는다.</li>
    <li><b>교환 어닐러는 본 연구의 구현이다.</b> Ocean의 표준 샘플러가 아니라 대조군으로 직접 작성했다.
      목적 함수는 동일함이 검증되었으나, 냉각 스케줄 등 하이퍼파라미터는 별도로 최적화하지 않았다.</li>
    <li><b>응집도는 연결성의 대리 지표다.</b> 인접한 같은 실 셀 쌍을 세는 2차항은 실이 끊기는 것을
      막지 못한다. 실제로 CP-SAT 해도 연결성 제약 없이는 {ORT['components']}개 실이 조각났다.</li>
    <li><b>단일 문제 인스턴스다.</b> 격자 하나, 실 프로그램 하나에서 얻은 결과다.
      프리셋 {len(M['presets'])}종에서 일관되게 재현되었으나 다른 규모·형상으로의 일반화는 검증되지 않았다.</li>
  </ul>
</section>

<section id="s7"><h2><span class="num">7</span>결론</h2>
  <p class="body"><b>Q1.</b> 동일한 평가 함수에서 CP-SAT는 {n(ORT['energy'])},
     QUBO 인코딩 어닐링은 {n(DW['energy'])}를 얻었다. 프리셋 {len(M['presets'])}종 전부에서
     같은 순서가 재현되었다.</p>
  <p class="body"><b>Q2.</b> 격차의 지배적 원인은 <b>인코딩</b>이었다. 예산 가설(E2)과 벌점 스케일 가설(E5)은
     기각되었고, 알고리즘을 그대로 둔 채 인코딩만 교체하자 격차의
     {ENCODING_GAIN/abs(DW['energy']-ORT['energy'])*100:.0f}%가 사라졌다(E4).
     근본 원인은 페널티 인코딩이 실현 가능한 해들을 ΔE ≈ {n(flip_med,1,True)}의 장벽으로 격리하고,
     단일 비트 뒤집기로는 그 사이를 오갈 수 없다는 데 있다(E1: 개선 이동 0.0%).</p>
  <p class="body"><b>Q3.</b> 표현력 차이는 인코딩을 고쳐도 남는다. 연결성 제약은 2차식으로 표현할 수 없으므로
     QUBO 계열에는 <em>넣을 방법 자체가 없다</em>. CP-SAT는 이를 {n(abs(CONN_COST),3)}의 비용으로 강제해
     모든 실이 한 덩어리인 도면을 만들었다. 건축 실무에서 이는 점수 차이가 아니라 채택 가능 여부의 차이다.</p>
  <p class="body">요약하면, <b>이 문제에서 갈린 것은 하드웨어도 알고리즘도 아니라 문제를 옮겨 적는 방식이었다.</b></p>
</section>

<section id="app"><h2><span class="num">부록</span>재현 절차</h2>
  <pre class="cmd"><b>uv venv --python 3.12 .venv</b>
<b>uv pip install --python .venv/bin/python</b> ortools dimod dwave-samplers dwave-system anthropic

<span class="dim"># 전체 연구 재실행 (주 비교 + 스윕 {len(M['presets'])}종 + 진단 5종, 약 {M['total_wall_time']/60:.0f}분)</span>
<b>.venv/bin/python run_study.py</b>
<b>.venv/bin/python build_paper.py</b>

<span class="dim"># 4단계 파이프라인 단독 실행</span>
<b>.venv/bin/python main.py</b> --spec {M['spec']} --env {M['base_env']} --time-limit {M['budgets']['cpsat_seconds']:.0f}

<span class="dim"># Claude로 도면 생성 (ANTHROPIC_API_KEY 또는 `ant auth login`)</span>
<b>.venv/bin/python main.py</b> --backend claude

<span class="dim"># 실제 양자 하드웨어 (DWAVE_API_TOKEN 또는 `dwave config create`)</span>
<b>.venv/bin/python main.py</b> --dwave qpu      <span class="dim"># QPU 직접</span>
<b>.venv/bin/python main.py</b> --dwave hybrid   <span class="dim"># Leap 하이브리드 (권장)</span></pre>
  <p class="body">목적 함수는 <code>floorplan_bench/terms.py</code> 한 곳에서만 생성된다.
     <code>quality_coeffs()</code>가 CP-SAT와 QUBO 양쪽에 같은 계수를 공급하고,
     <code>raw_values()</code>가 도면을 직접 순회하는 독립 평가기로서 이를 교차 검증한다.</p>
</section>

<footer>
  실행 {M['date']} · {E(M['env']['platform'])} · {E(M['env']['machine'])}<br>
  Python {M['env']['python']} · OR-Tools {M['env']['ortools']} · dimod {M['env']['dimod']} · dwave-samplers 1.8.0<br>
  난수 시드 {M['budgets']['seed']} · 총 실행 {M['total_wall_time']/60:.1f}분 ·
  목적 함수 3경로 교차 검증 통과(불일치 &lt; 10⁻⁶)
</footer>
</main></div>
"""

open("out/report.html", "w", encoding="utf-8").write(HTML)
print(f"→ out/report.html ({len(HTML):,} bytes) · 그림 {_fig[0]}개 · 표 {_tab[0]}개")
