"""Space Syntax 분석 결과 → HTML 리포트."""
from __future__ import annotations

import html, json, os
from datetime import date

from floorplan_bench.report import render_svg
from floorplan_bench.spacesyntax import CARRIER, SyntaxRules, build_graph
from floorplan_bench.syntax_render import (RAMP, RAMP_COOL, ramp_legend,
                                           render_cell_heatmap, render_jgraph,
                                           render_room_heatmap)

E = html.escape

GLOSSARY = [
    ("연결도", "Connectivity", "그 실에 직접 이어진 실의 수. 문이 몇 개인가와 같다."),
    ("평균 깊이", "Mean Depth", "그 실에서 다른 모든 실까지의 최단 이동 횟수의 평균. MD = TD/(k−1)."),
    ("상대 비대칭성", "RA", "평균 깊이를 0~1로 정규화한 값. RA = 2(MD−1)/(k−2). 작을수록 얕다."),
    ("실규모 보정 RA", "RRA", "노드 수가 다른 평면끼리 견줄 수 있게 다이아몬드 값 D<sub>k</sub>로 나눈 값."),
    ("통합도", "Integration", "1/RRA. <b>클수록 전체에서 접근하기 쉬운 중심 공간</b>이다."),
    ("제어값", "Control Value", "이웃한 실들의 연결도 역수의 합. 1보다 크면 주변을 통제하는 위치."),
    ("선택도", "Choice", "최단 경로가 그 실을 통과하는 빈도(매개 중심성). 동선이 지나가는 목."),
    ("깊이", "Step Depth", "외부(현관)에서 그 실까지 문을 몇 번 지나야 하는가."),
    ("명료성", "Intelligibility", "연결도와 통합도의 결정계수 r². 국소적으로 보이는 것이 전체 구조를 잘 예측하는가."),
    ("차이 계수", "H*", "공간 위계가 얼마나 고른가. 1에 가까울수록 평평(위계 없음)."),
    ("시각 통합도", "Visual Integration", "가시성 그래프(VGA) 위에서 잰 통합도. 눈으로 닿기 쉬운 정도."),
    ("아이소비스트", "Isovist", "한 지점에서 보이는 영역. 면적·둘레·최대 시선거리·드리프트로 기술한다."),
]


def _tbl(headers, rows, cls="") -> str:
    h = "".join(f'<th class="{c}">{E(t)}</th>' for t, c in headers)
    b = "".join("<tr>" + "".join(f'<td class="{c}">{v}</td>' for v, c in r) + "</tr>" for r in rows)
    return f'<div class="tw"><table class="{cls}"><thead><tr>{h}</tr></thead><tbody>{b}</tbody></table></div>'


def _f(v, d=3):
    if v is None: return "—"
    if isinstance(v, bool): return "O" if v else "X"
    if isinstance(v, float):
        return "—" if v != v else f"{v:.{d}f}"
    return str(v)


def plan_block(spec, plan, res, rules, idx) -> str:
    g = build_graph(spec, plan, rules)
    integ = {k: v["measures"]["integration"] for k, v in res["rooms"].items() if k != CARRIER}
    depth = {k: v["syntactic"]["step_depth_from_carrier"] for k, v in res["rooms"].items() if k != CARRIER}
    depth = {k: (float(v) if v is not None else float("nan")) for k, v in depth.items()}
    gl = res["global"]

    ivals = [v for v in integ.values() if v == v]
    dvals = [v for v in depth.values() if v == v]

    panels = [
        ("평면도 <span class='dim'>실측 좌표</span>", f'<div class="mat">{render_svg(spec, plan, cell=30)}</div>', ""),
        ("정당화 그래프 <span class='dim'>위상 좌표</span>",
         f'<div class="mat jg">{render_jgraph(g, res)}</div>',
         "세로축이 현관으로부터의 깊이다. 색이 진할수록 통합도가 높다."),
        ("통합도 <span class='dim'>실 단위</span>",
         f'<div class="mat">{render_room_heatmap(spec, plan, integ)}</div>',
         ramp_legend(min(ivals), max(ivals), "통합도", RAMP) if ivals else ""),
        ("현관 깊이 <span class='dim'>실 단위</span>",
         f'<div class="mat">{render_room_heatmap(spec, plan, depth, fmt="{:.0f}")}</div>',
         ramp_legend(min(dvals), max(dvals), "깊이", RAMP) if dvals else ""),
    ]
    if "vga" in res:
        vi = {c: v["visual_integration"] for c, v in res["vga"].items()}
        vvals = [v for v in vi.values() if v == v]
        panels.append(("시각 통합도 <span class='dim'>셀 단위 VGA</span>",
                       f'<div class="mat">{render_cell_heatmap(spec, plan, res["vga"], "visual_integration")}</div>',
                       ramp_legend(min(vvals), max(vvals), "시각 통합도", RAMP_COOL) if vvals else ""))
        panels.append(("아이소비스트 면적 <span class='dim'>셀 단위</span>",
                       f'<div class="mat">{render_cell_heatmap(spec, plan, res["vga"], "isovist_area")}</div>',
                       "한 지점에서 보이는 칸 수. 밝을수록 시야가 좁다."))

    panel_html = "".join(
        f'<figure class="panel"><figcaption class="ptitle">{t}</figcaption>{body}'
        f'{f"<p class=pnote>{note}</p>" if note else ""}</figure>'
        for t, body, note in panels)

    rows = []
    order = sorted(res["rooms"].items(),
                   key=lambda kv: -(kv[1]["measures"]["integration"]
                                    if kv[1]["measures"]["integration"] == kv[1]["measures"]["integration"] else -9))
    for k, v in order:
        m, s, met = v["measures"], v["syntactic"], v["metric"]
        vis = v.get("visual", {})
        color = spec.room_by_key[k].color if k != CARRIER else "#e63946"
        rows.append([
            (f'<i class="dot" style="background:{color}"></i><b>{E(v["label"])}</b>', ""),
            (f'{met["centroid"][0]:.1f}, {met["centroid"][1]:.1f}' if met else "—", "n dim"),
            (f'{s["jx"]:+.1f}, {s["depth"]}', "n"),
            (_f(s["step_depth_from_carrier"]), "n"),
            (_f(m["connectivity"]), "n"), (_f(m["mean_depth"]), "n"),
            (_f(m["RRA"]), "n"), (f'<b>{_f(m["integration"])}</b>', "n strong"),
            (_f(m["control_value"]), "n"), (_f(m["choice"]), "n"),
            (_f(vis.get("mean_visual_integration")), "n dim"),
        ])
    tbl = _tbl([("실", ""), ("실측 좌표", "n"), ("위상 좌표 (jx, 깊이)", "n"), ("현관 깊이", "n"),
                ("연결도", "n"), ("평균깊이", "n"), ("RRA", "n"), ("통합도", "n"),
                ("제어값", "n"), ("선택도", "n"), ("시각 통합도", "n")], rows)

    doors = "".join(
        f'<tr><td>{E(e["a_label"])} ↔ {E(e["b_label"])}</td>'
        f'<td class="n">{f"{e['door_coord'][0]:.1f}, {e['door_coord'][1]:.1f}" if e["door_coord"] else "—"}</td>'
        f'<td class="n">{_f(e["shared_wall_cells"])}</td><td class="n">{_f(e["door_width_cells"])}</td></tr>'
        for e in res["edges"])

    return f"""<section class="planblock">
  <h2><span class="num">#{idx}</span>{E(plan.name)}</h2>
  <div class="statline">
    <span>노드 <b>{gl['node_count']}</b></span><span>간선 <b>{gl['edge_count']}</b></span>
    <span>시스템 평균깊이 <b>{_f(gl['mean_depth_system'])}</b></span>
    <span>현관 최대깊이 <b>{_f(gl['max_depth_from_carrier'])}</b></span>
    <span>명료성 r² <b>{_f(gl['intelligibility'])}</b></span>
    <span>차이계수 H* <b>{_f(gl['difference_factor'])}</b></span>
    {f"<span>시각 통합도 <b>{_f(gl.get('mean_visual_integration'))}</b></span>" if 'mean_visual_integration' in gl else ""}
    <span class="{'good' if gl['connected'] else 'warn'}">{'모든 실 도달 가능' if gl['connected'] else '고립된 실 있음'}</span>
  </div>
  <div class="panels">{panel_html}</div>
  <h3>실별 좌표와 지표</h3>
  {tbl}
  <h3>문 — 투과성 간선과 좌표</h3>
  <div class="tw"><table><thead><tr><th>연결</th><th class="n">문 좌표</th>
    <th class="n">공유 벽(칸)</th><th class="n">문 폭(칸)</th></tr></thead><tbody>{doors}</tbody></table></div>
</section>"""


def build_html(spec, plans, results, rules: SyntaxRules, rules_name, comparison, path) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    rule_rows = [[(f'<code>{E(k)}</code>', ""), (f'<b>{E(str(v))}</b>', "n")]
                 for k, v in rules.as_dict().items()]
    rule_tbl = _tbl([("규칙", ""), ("값", "n")], rule_rows)

    blocks = "".join(plan_block(spec, p, r, rules, i + 1)
                     for i, (p, r) in enumerate(zip(plans, results)))

    comp = ""
    if comparison:
        rows = [[(f'<b>{E(c["rules"])}</b>', ""),
                 (_f(c["node_count"]), "n"), (_f(c["edge_count"]), "n"),
                 (_f(c["mean_depth_system"]), "n"), (_f(c["max_depth_from_carrier"]), "n"),
                 (_f(c["intelligibility"]), "n"), (_f(c["difference_factor"]), "n"),
                 (_f(c.get("mean_visual_integration")), "n")] for c in comparison]
        comp = f"""<section>
  <h2><span class="num">비교</span>규칙을 바꾸면 위상이 달라진다</h2>
  <p class="body">같은 도면({E(plans[0].name)})에 규칙 프리셋을 바꿔 적용한 결과다.
    문으로 인정할 최소 접면 길이, 외부와 이어지는 실의 범위, 문 폭 — 이런 규칙 하나가
    그래프의 간선 수와 깊이 구조를 통째로 바꾼다. <b>Space Syntax의 결과는 규칙의 함수다.</b></p>
  {_tbl([("규칙 프리셋",""),("노드","n"),("간선","n"),("시스템 평균깊이","n"),("현관 최대깊이","n"),
         ("명료성 r²","n"),("차이계수 H*","n"),("시각 통합도","n")], rows)}
</section>"""

    gloss = "".join(
        f'<div><dt>{E(ko)} <span class="en">{E(en)}</span></dt><dd>{desc}</dd></div>'
        for ko, en, desc in GLOSSARY)

    css = """
:root{--ground:#eef1f2;--surface:#fbfcfc;--ink:#14212a;--ink-2:#3c4f5a;--muted:#5d6f79;
 --rule:#d6dee1;--rule-soft:#e5eaec;--acc:#0d8f7c;--warm:#b06a12;--bad:#a8451a;
 --mat:#fff;--mat-edge:#c9d3d7;--shadow:0 1px 2px rgba(20,33,42,.06),0 8px 22px -12px rgba(20,33,42,.18)}
@media(prefers-color-scheme:dark){:root:not([data-theme="light"]){--ground:#111a20;--surface:#18242c;
 --ink:#e2eaed;--ink-2:#b6c6ce;--muted:#93a5ae;--rule:#2a3a44;--rule-soft:#22313a;--acc:#17a68d;
 --warm:#c67f22;--bad:#e08a5c;--mat:#eceff0;--mat-edge:#394a54;
 --shadow:0 1px 2px rgba(0,0,0,.4),0 10px 26px -14px rgba(0,0,0,.7)}}
:root[data-theme="dark"]{--ground:#111a20;--surface:#18242c;--ink:#e2eaed;--ink-2:#b6c6ce;
 --muted:#93a5ae;--rule:#2a3a44;--rule-soft:#22313a;--acc:#17a68d;--warm:#c67f22;--bad:#e08a5c;
 --mat:#eceff0;--mat-edge:#394a54;--shadow:0 1px 2px rgba(0,0,0,.4),0 10px 26px -14px rgba(0,0,0,.7)}
*{box-sizing:border-box}
body{margin:0;background:var(--ground);color:var(--ink);font-size:15px;line-height:1.72;
 font-family:"IBM Plex Sans KR","Apple SD Gothic Neo",system-ui,sans-serif;
 word-break:keep-all;overflow-wrap:break-word;-webkit-font-smoothing:antialiased}
h1,h2,h3,.ptitle{font-family:"Noto Serif KR",Georgia,serif;text-wrap:balance}
code{font-family:"IBM Plex Mono",monospace;font-size:.9em;background:var(--rule-soft);padding:1px 5px;border-radius:2px}
.wrap{max-width:1180px;margin:0 auto;padding:0 26px 90px}
.mast{padding:58px 0 28px;border-bottom:2px solid var(--ink)}
.kicker{font-size:11.5px;letter-spacing:.19em;text-transform:uppercase;color:var(--muted);font-weight:600;margin:0 0 15px}
h1{font-size:clamp(28px,4.4vw,42px);line-height:1.22;font-weight:700;margin:0 0 13px}
.lede{font-size:16.5px;color:var(--ink-2);margin:0;max-width:62ch}
.meta{display:flex;flex-wrap:wrap;gap:2px 26px;margin-top:22px;font-family:"IBM Plex Mono",monospace;
 font-size:11.5px;color:var(--muted)}
.meta b{color:var(--ink-2);font-weight:500}
section{padding-top:50px}
h2{font-size:21px;font-weight:600;margin:0 0 10px;padding-bottom:10px;border-bottom:1px solid var(--rule)}
h2 .num{font-family:"IBM Plex Mono",monospace;font-size:12.5px;color:var(--acc);margin-right:11px;font-weight:500}
h3{font-size:15px;font-weight:600;margin:28px 0 8px;color:var(--ink-2)}
p.body{max-width:68ch;margin:0 0 14px;color:var(--ink-2)}
p.body b{color:var(--ink);font-weight:600}
.statline{display:flex;flex-wrap:wrap;gap:6px 20px;margin:0 0 20px;font-size:12.5px;
 color:var(--muted);font-family:"IBM Plex Mono",monospace}
.statline b{color:var(--ink);font-weight:600}
.statline .good{color:var(--acc)} .statline .warn{color:var(--bad)}
.panels{display:grid;gap:16px;grid-template-columns:repeat(auto-fit,minmax(240px,1fr))}
@media(min-width:900px){.panels{grid-template-columns:repeat(3,1fr)}}
.panel{margin:0;background:var(--surface);border:1px solid var(--rule);border-radius:3px;
 overflow:hidden;box-shadow:var(--shadow);display:flex;flex-direction:column}
.ptitle{padding:11px 14px 9px;font-size:12.5px;font-weight:600;border-bottom:1px solid var(--rule-soft)}
.ptitle .dim{font-weight:400;font-size:11px}
.mat{background:var(--mat);padding:12px;flex:1}
.mat.jg{display:flex;align-items:center;justify-content:center}
.jgraph{max-height:340px}
.plan-svg,.jgraph{display:block;width:100%;height:auto}
.jlevel{stroke:#d8dfe2;stroke-width:1;stroke-dasharray:3 4}
.jdepth{font-size:10px;fill:#8697a0;font-family:"IBM Plex Mono",monospace}
.jedge{stroke:#5d6f79;stroke-width:1.6}
.jnode{stroke:#1e2a33;stroke-width:1.6}
.jcarrier{stroke:#e63946;stroke-width:2.2}
.jlabel{font-size:10.5px;fill:#1e2a33;font-weight:600}
.pnote{margin:0;padding:9px 14px 11px;font-size:11px;color:var(--muted);line-height:1.5;
 border-top:1px solid var(--rule-soft)}
.ramp{display:flex;align-items:center;gap:6px;font-size:10px;color:var(--muted);
 font-family:"IBM Plex Mono",monospace;flex-wrap:wrap}
.ramp .rlab{font-family:inherit;color:var(--ink-2)}
.rbar{display:inline-flex;height:9px;border-radius:2px;overflow:hidden;flex:1;min-width:60px}
.rbar i{flex:1}
.tw{overflow-x:auto;margin:14px 0 4px}
table{border-collapse:collapse;width:100%;font-size:13px;min-width:560px}
th{text-align:left;font-weight:600;font-size:10.5px;letter-spacing:.09em;text-transform:uppercase;
 color:var(--muted);padding:0 12px 8px 0;border-bottom:1px solid var(--rule);white-space:nowrap}
td{padding:8px 12px 8px 0;border-bottom:1px solid var(--rule-soft);vertical-align:baseline}
td.n,th.n{text-align:right;font-family:"IBM Plex Mono",monospace;font-variant-numeric:tabular-nums;
 padding-right:14px;white-space:nowrap}
td.strong{font-weight:600;color:var(--warm)}
.dim{color:var(--muted)}
.dot{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:7px;
 border:1px solid rgba(0,0,0,.15)}
.gloss{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:1px;
 background:var(--rule);border:1px solid var(--rule);margin:18px 0}
.gloss>div{background:var(--surface);padding:14px 16px}
.gloss dt{font-size:13px;font-weight:600;margin:0 0 4px}
.gloss dt .en{font-family:"IBM Plex Mono",monospace;font-size:10.5px;color:var(--acc);
 font-weight:400;margin-left:6px}
.gloss dd{margin:0;font-size:12.5px;color:var(--ink-2);line-height:1.6}
pre.cmd{background:var(--surface);border:1px solid var(--rule);border-radius:3px;padding:15px 19px;
 overflow-x:auto;font-family:"IBM Plex Mono",monospace;font-size:12.5px;line-height:1.9;color:var(--ink-2)}
pre.cmd b{color:var(--ink);font-weight:500}
footer{margin-top:50px;padding-top:20px;border-top:1px solid var(--rule);font-size:11.5px;
 color:var(--muted);font-family:"IBM Plex Mono",monospace}
@media(prefers-reduced-motion:reduce){*{transition:none!important}}
:focus-visible{outline:2px solid var(--acc);outline-offset:2px}
"""

    doc = f"""<meta charset="utf-8">
<title>공간구문 좌표 추출기</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans+KR:wght@400;500;600&family=Noto+Serif+KR:wght@600;700&display=swap">
<style>{css}</style>
<div class="wrap">
<header class="mast">
  <p class="kicker">Space Syntax · 규칙 → 도면 → 좌표</p>
  <h1>평면을 위상으로 다시 적는다</h1>
  <p class="lede">실측 좌표로 그려진 도면을 공간구문론의 좌표계로 옮긴다.
    무엇을 '연결'로 볼 것인지는 규칙이 정하고, 그 규칙이 바뀌면 같은 도면도 다른 구조가 된다.</p>
  <div class="meta">
    <span>규칙 <b>{E(rules_name)}</b></span>
    <span>대상 <b>{E(spec.name)}</b></span>
    <span>도면 <b>{len(plans)}장</b></span>
    <span>추출일 <b>{date.today().isoformat()}</b></span>
  </div>
</header>

<section>
  <h2><span class="num">규칙</span>무엇을 연결로 볼 것인가</h2>
  <p class="body">공간구문론의 지표는 모두 <b>그래프</b> 위에서 계산된다. 따라서 결과는
    "어떤 그래프를 만들었는가"에 전적으로 달려 있다. 이 프로그램은 그 판단을 규칙으로 드러내
    바꿔 볼 수 있게 한다.</p>
  {rule_tbl}
  <p class="body"><code>door_min_cells</code>는 두 실이 몇 칸 이상 벽을 맞대야 문을 놓을 수 있다고 볼지,
    <code>carrier_mode</code>는 외부와 이어지는 실을 현관 하나로 볼지 외벽에 닿은 모든 실로 볼지,
    <code>door_width_cells</code>는 시선이 얼마나 뚫리는지를 정한다.
    <code>normalize</code>가 <code>rra</code>면 노드 수가 다른 평면끼리도 견줄 수 있다.</p>
</section>

{blocks}
{comp}

<section>
  <h2><span class="num">용어</span>지표 읽는 법</h2>
  <div class="gloss">{gloss}</div>
</section>

<section>
  <h2><span class="num">출력</span>추출된 좌표 쓰기</h2>
  <p class="body">세 벌의 좌표가 함께 나온다 — <b>실측</b>(중심점·바운딩박스),
    <b>위상</b>(정당화 그래프의 jx·깊이), <b>시각</b>(셀별 VGA 통합도).
    CSV는 엑셀·QGIS·R로 바로 열 수 있고, JSON은 그래프 구조와 문 좌표까지 담는다.</p>
  <pre class="cmd"><span class="dim"># 규칙 템플릿 만들기 → 값을 고쳐서 쓴다</span>
<b>python syntax_cli.py --dump-rules rules.json</b>

<span class="dim"># 도면 넣고 좌표 뽑기</span>
<b>python syntax_cli.py --plans out/plans.json --rules rules.json</b>
<b>python syntax_cli.py --plan-file myplan.txt --rules strict_door</b>

<span class="dim"># 규칙을 바꿔가며 비교</span>
<b>python syntax_cli.py --plans out/plans.json --compare-rules</b>

<span class="dim"># 산출물</span>
out/syntax/syntax.json        <span class="dim">그래프·문 좌표·전체 지표</span>
out/syntax/syntax_rooms.csv   <span class="dim">실별 실측/위상/시각 좌표 + 지표</span>
out/syntax/syntax_edges.csv   <span class="dim">문 좌표와 공유 벽 길이</span>
out/syntax/syntax_cells.csv   <span class="dim">셀별 VGA·아이소비스트</span></pre>
</section>

<footer>Hillier &amp; Hanson(1984) 공간구문론 · Turner et al.(2001) VGA · Benedikt(1979) 아이소비스트<br>
규칙 {E(json.dumps(rules.as_dict(), ensure_ascii=False))}</footer>
</div>"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(doc)
