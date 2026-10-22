"""AI 허브 라벨 JSON으로 도면을 평가하고 그린다 — PNG 인식 단계 없이.

    ① 정답지 만들기: 실제 아파트 라벨(SPA) 폴더 → 지표별 분포(전체 + 침실 수별 층)
    python aihub_eval.py baseline <라벨폴더> -o out/baseline.json

    ② 평가 구조(조건·반영방식·변수) 정하기 — 웹 스튜디오에서 내보낸 JSON과 같은 형식
    python aihub_eval.py config -o my.json                      # 기본 세트를 파일로
    python aihub_eval.py config --preset 시공가능성만 -o a.json
    python aihub_eval.py config --check my.json                 # 문법·지표 확인

    ③ 채점 (+ 통계 — 웹 '통계' 탭과 같은 JSON, 웹에서 '통계 불러오기'로 열린다)
    python aihub_eval.py score <파일|폴더> --baseline out/baseline.json --config my.json -v --csv out/s.csv                                --stats out/stats.json --name "3R2B 시공성 v1" --memo "회의 10/23"

    ④ 도면 그리기 (SVG)
    python aihub_eval.py render <파일|폴더> -o out/svg --baseline out/baseline.json --config my.json

    ⑤ 구조(STR) 라벨의 문·창 겹침 검사
    python aihub_eval.py struct <STR 파일|폴더>
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import sys

from floorplan_bench.aihub import label_type, load_struct, load_units, read_coco
from floorplan_bench.criteria import MEASURES, PRESETS, Config, load_config, parse_dsl, to_dsl
from floorplan_bench.evaluate import (CRITERIA, FEATURES, build_baseline, default_params, evaluate,
                                      features, permeability, split_params, struct_checks,
                                      to_json, type_key)
from floorplan_bench.render_aihub import render_sheet
from floorplan_bench.stats import aggregate, stat_row


def json_files(path: str, kind: str | None) -> list[str]:
    if os.path.isfile(path):
        return [path]
    files = sorted(glob.glob(os.path.join(path, "**", "*.json"), recursive=True))
    return [f for f in files if kind is None or label_type(read_coco(f), f) == kind]


def write(path: str | None, text: str):
    if not path:
        return
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"→ {path}", file=sys.stderr)


def read_baseline(path):
    if not path:
        return None
    with open(path, encoding="utf-8") as f:
        base = json.load(f)
    if base.get("version") != 2:
        print(f"경고: {path}는 옛 형식의 정답지라 정답지 근접도를 계산하지 않습니다 — "
              "'baseline' 명령으로 다시 만드세요.", file=sys.stderr)
        return None
    return base


def cmd_baseline(a):
    cfg = load_config(a.config)
    lo, ep = split_params(cfg.params)
    rows = []
    for f in json_files(a.path, "SPA"):
        for u in load_units(f, lo):
            feat, _ = features(u, permeability(u, ep))
            rows.append({"unit": u.uid, "type": type_key(u), **feat})
    base = build_baseline(rows)
    base["params"] = cfg.params
    print(f"세대 {base['n_units']}개 · 유형 분포 {base['type_counts']}")
    top = next(iter(base["type_counts"]), None)
    if top:
        print(f"최다 유형: {top} ({base['type_counts'][top]}세대) — 평형 대용 기준")
    print(f"지표 {len(base['all'])}개 · 침실 수별 층 "
          + (", ".join(f"{k}실 {v['n']}세대" for k, v in base["strata"].items()) or "없음"))
    # 반올림하지 않는다 — 이산 지표의 누적분포는 값이 같은지로 센다
    write(a.out, to_json({**base, "rows": rows}, ndigits=None))


def evaluate_path(path, cfg, base):
    lo, ep = split_params(cfg.params)
    for f in json_files(path, "SPA"):
        units = load_units(f, lo)
        yield f, units, [evaluate(u, base, ep, cfg) for u in units]


def cmd_score(a):
    cfg, base = load_config(a.config), read_baseline(a.baseline)
    results, rows = [], []
    for f, _, rs in evaluate_path(a.path, cfg, base):
        results += rs
        rows += [stat_row(r, os.path.basename(f)) for r in rs]
    if a.stats:
        if not cfg.params:
            cfg.params = default_params()
        write(a.stats, to_json(aggregate(rows, cfg, a.name, a.memo, base)))
    for r in results:
        sc = r["score"]
        print(f"{r['unit']:<26} {r['type']:<6} {sc['total']:5.1f}점 {sc['grade']:<2} "
              f"(기본 {sc['base']:5.1f} − 감점 {sc['penalty']:4.1f}"
              f"{' · 필수조건 탈락 ' + str(sc['gated']) if sc['gated'] else ''})")
        typ = r.get("typicality")
        if a.verbose and typ:
            doms = " · ".join(f"{d} {x['score']:.0f}" for d, x in typ["domains"].items())
            print(f"    정답지 근접도 {typ['score']:.1f} [{typ['reference']}] {doms}")
        if a.verbose:
            for row in r["criteria_rows"]:
                c = row["criterion"]
                if row["score"] is None or row["score"] >= 1:
                    continue
                tgt = f"{c['room']}.{c['measure']}" if c.get("room") else f"@{c['measure']}"
                v = row["value"]
                vs = f"{v:.3g}" if isinstance(v, (int, float)) else "-"
                eff = {"weight": f"w={c['weight']:g}", "penalty": f"−{row.get('deduct', 0):.1f}",
                       "gate": "필수 탈락"}[c["effect"]]
                where = f" [{r['measures']['rooms'][row['room']]['name']}]" if row.get("room") else ""
                print(f"    {tgt:<26} 값 {vs:<7} 조건점수 {row['score']:.2f}  {eff}{where}")
    write(a.out, to_json({"criteria_basis": CRITERIA, "config": cfg.as_dict(), "results": results}))
    if a.csv:
        cols = ["unit", "type", "est_area_m2", "total", "grade", "base", "penalty", "gated"] \
               + [f"@{k}" for k, v in MEASURES.items() if v["scope"] == "global"]                + [k for k in FEATURES if k != "geno_dist"]   # geno_dist는 정답지와 견줄 때만 계산된다
        os.makedirs(os.path.dirname(a.csv) or ".", exist_ok=True)
        with open(a.csv, "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(cols)
            for r in results:
                row = {"unit": r["unit"], "type": r["type"], "est_area_m2": r["est_area_m2"],
                       **r["score"], **{f"@{k}": v for k, v in r["measures"]["global"].items()},
                       **r["features"]}
                w.writerow([row.get(c, "") for c in cols])
        print(f"→ {a.csv}", file=sys.stderr)


def cmd_render(a):
    cfg, base = load_config(a.config), read_baseline(a.baseline)
    lo, ep = split_params(cfg.params)
    os.makedirs(a.out, exist_ok=True)
    for f in json_files(a.path, None):
        data = read_coco(f)
        kind = label_type(data, f)
        units, results = [], []
        if kind == "SPA":
            units = load_units(f, lo)
            results = [evaluate(u, base, ep, cfg) for u in units]
        elif kind == "STR":
            results = struct_checks(load_struct(f), ep.door_window_min_overlap)
        svg = render_sheet(data, kind, units, results, graph=not a.no_graph,
                           title=f"{os.path.basename(f)} · {kind}")
        dst = os.path.join(a.out, os.path.splitext(os.path.basename(f))[0] + ".svg")
        with open(dst, "w", encoding="utf-8") as fh:
            fh.write(svg)
        print(f"→ {dst}")


def cmd_config(a):
    if a.check:
        cfg = load_config(a.check)
        print(f"조건 {len(cfg.criteria)}개 · 변수 {cfg.params or '(기본값)'}")
        print(to_dsl(cfg.criteria))
        split_params(cfg.params)
        return
    if a.list:
        for k, v in MEASURES.items():
            print(f"{'@' if v['scope'] == 'global' else '.'}{k:<24} {v['label']:<16} {v['hint']}")
        return
    cs, errs = parse_dsl(PRESETS[a.preset])
    assert not errs, errs
    cfg = Config(params=default_params(), criteria=cs)
    text = json.dumps(cfg.as_dict(), ensure_ascii=False, indent=2)
    if a.out:
        write(a.out, text)
    else:
        print(text)


def cmd_struct(a):
    out = []
    for f in json_files(a.path, "STR"):
        sh = load_struct(f)
        iss = struct_checks(sh)
        out.append({"sheet": sh.source, "doors": len(sh.doors), "windows": len(sh.windows), "issues": iss})
        print(f"{sh.source:<28} 문 {len(sh.doors):3d} 창 {len(sh.windows):3d}  문·창 겹침 {len(iss)}")
        if a.verbose:
            for i in iss:
                print("    " + i["message"])
    write(a.out, to_json(out))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("baseline", help="실제 아파트 라벨로 정답지 분포 만들기")
    b.add_argument("path")
    b.add_argument("-o", "--out", default="out/baseline.json")
    b.add_argument("--config", help="변수(params)를 쓸 설정 파일")
    b.set_defaults(fn=cmd_baseline)

    s = sub.add_parser("score", help="세대별 채점")
    s.add_argument("path")
    s.add_argument("--baseline")
    s.add_argument("--config", help="조건·반영방식·변수 설정(.json) 또는 조건 문법(.txt)")
    s.add_argument("-o", "--out")
    s.add_argument("--csv")
    s.add_argument("--stats", help="통계 JSON (웹 스튜디오 '통계 불러오기'로 열림)")
    s.add_argument("--name", default="", help="통계 기록 이름")
    s.add_argument("--memo", default="", help="통계 기록 메모")
    s.add_argument("-v", "--verbose", action="store_true", help="못 맞춘 조건을 보여준다")
    s.set_defaults(fn=cmd_score)

    r = sub.add_parser("render", help="라벨 JSON → SVG 도면")
    r.add_argument("path")
    r.add_argument("-o", "--out", default="out/svg")
    r.add_argument("--baseline")
    r.add_argument("--config")
    r.add_argument("--no-graph", action="store_true", help="추정 문·연결선을 그리지 않는다")
    r.set_defaults(fn=cmd_render)

    c = sub.add_parser("config", help="평가 구조 설정 파일 만들기·확인")
    c.add_argument("--preset", default="시공가능성 + 공간구문", choices=list(PRESETS))
    c.add_argument("-o", "--out")
    c.add_argument("--check", metavar="FILE")
    c.add_argument("--list", action="store_true", help="쓸 수 있는 지표 목록")
    c.set_defaults(fn=cmd_config)

    t = sub.add_parser("struct", help="STR 라벨 문·창 겹침 검사")
    t.add_argument("path")
    t.add_argument("-o", "--out")
    t.add_argument("-v", "--verbose", action="store_true")
    t.set_defaults(fn=cmd_struct)

    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
