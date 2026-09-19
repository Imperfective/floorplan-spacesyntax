"""Space Syntax 좌표 추출기.

    규칙을 정하고 → 도면을 넣으면 → Space Syntax 좌표와 지표를 뽑는다.

사용 예
    # 규칙 템플릿 만들기
    python syntax_cli.py --dump-rules examples/rules.json

    # 도면 분석 (규칙 프리셋)
    python syntax_cli.py --plans out/plans.json --rules standard

    # 규칙 파일로 분석
    python syntax_cli.py --plans out/plans.json --rules rules.json

    # 아스키 도면 한 장 분석
    python syntax_cli.py --plan-file examples/example_plan.txt --rules strict_door

    # 규칙을 바꿔가며 같은 도면이 어떻게 달라지는지 비교
    python syntax_cli.py --plans out/plans.json --compare-rules
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys

from floorplan_bench.plan import FloorPlan, load_plans
from floorplan_bench.spacesyntax import (CARRIER, DEFAULT_RULES, PRESET_RULES,
                                         SyntaxRules, build_graph, extract)
from floorplan_bench.spec import SPECS

MEASURE_COLS = ["connectivity", "total_depth", "mean_depth", "RA", "RRA",
                "integration", "control_value", "choice"]
GLOBAL_COLS = ["node_count", "edge_count", "mean_depth_system", "mean_integration",
               "max_depth_from_carrier", "intelligibility", "difference_factor",
               "connected", "mean_visual_integration", "mean_visual_connectivity",
               "visual_intelligibility", "mean_clustering"]


# ────────────────────────────────────────────── 입력
def load_rules(arg: str) -> tuple[SyntaxRules, str]:
    if arg in PRESET_RULES:
        return PRESET_RULES[arg], arg
    if os.path.exists(arg):
        with open(arg, encoding="utf-8") as f:
            data = json.load(f)
        return SyntaxRules.from_dict(data), os.path.basename(arg)
    raise SystemExit(f"규칙을 찾을 수 없습니다: '{arg}'\n"
                     f"프리셋: {list(PRESET_RULES)} 또는 JSON 파일 경로")


def load_plan_file(path: str, spec) -> list[FloorPlan]:
    """도면 입력 — plans.json / 사각형 JSON / 아스키 격자 텍스트를 모두 받는다."""
    if path.endswith(".json"):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list) and data and "assignment" in data[0]:
            return [FloorPlan.from_dict(d) for d in data]
        if isinstance(data, list) and data and "room" in data[0]:
            return [FloorPlan.from_rects(spec, data, os.path.basename(path), "file")
                    .repair(spec)]
        if isinstance(data, dict) and "rects" in data:
            return [FloorPlan.from_rects(spec, data["rects"],
                                         data.get("name", os.path.basename(path)), "file")
                    .repair(spec)]
        raise SystemExit("JSON 형식을 알 수 없습니다. plans.json 또는 [{room,x,y,w,h}] 목록이어야 합니다.")

    # 아스키 격자: 실 키 또는 실 이름 첫 글자
    with open(path, encoding="utf-8") as f:
        lines = [ln.rstrip("\n") for ln in f if ln.strip()]
    by_key = {r.key: r.key for r in spec.rooms}
    by_initial = {r.name[0]: r.key for r in spec.rooms}
    rows = []
    for ln in lines:
        toks = ln.replace(",", " ").split()
        if len(toks) != spec.width:
            toks = list(ln.replace(" ", ""))
        rows.append(toks)
    if len(rows) != spec.height or any(len(r) != spec.width for r in rows):
        raise SystemExit(f"격자 크기가 맞지 않습니다. {spec.width}×{spec.height}를 기대했습니다.")
    assignment = []
    for row in rows:
        for t in row:
            assignment.append(by_key.get(t) or by_initial.get(t[0]))
    return [FloorPlan(spec.key, os.path.basename(path), assignment, "file").repair(spec)]


# ────────────────────────────────────────────── 출력
def write_csvs(results: list[dict], outdir: str) -> None:
    with open(f"{outdir}/syntax_rooms.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["plan", "room_key", "room", "metric_cx", "metric_cy", "area",
                    "jgraph_x", "jgraph_depth", "step_depth_from_carrier",
                    *MEASURE_COLS, "mean_visual_integration", "mean_visual_connectivity"])
        for r in results:
            for k, v in r["rooms"].items():
                m, s, met = v["measures"], v["syntactic"], v["metric"]
                vis = v.get("visual", {})
                w.writerow([r["plan"]["name"], k, v["label"],
                            f'{met["centroid"][0]:.3f}' if met else "",
                            f'{met["centroid"][1]:.3f}' if met else "",
                            met["area"] if met else "",
                            f'{s["jx"]:.2f}', s["depth"], s["step_depth_from_carrier"],
                            *[f'{m[c]:.5f}' if isinstance(m[c], float) else m[c] for c in MEASURE_COLS],
                            f'{vis.get("mean_visual_integration", float("nan")):.5f}',
                            f'{vis.get("mean_visual_connectivity", float("nan")):.3f}'])

    with open(f"{outdir}/syntax_edges.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["plan", "a", "b", "a_label", "b_label", "door_x", "door_y",
                    "shared_wall_cells", "door_width_cells"])
        for r in results:
            for e in r["edges"]:
                dc = e["door_coord"] or ("", "")
                w.writerow([r["plan"]["name"], e["a"], e["b"], e["a_label"], e["b_label"],
                            f"{dc[0]:.2f}" if dc[0] != "" else "",
                            f"{dc[1]:.2f}" if dc[1] != "" else "",
                            e["shared_wall_cells"], e["door_width_cells"]])

    if any("vga" in r for r in results):
        with open(f"{outdir}/syntax_cells.csv", "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            keys = ["x", "y", "room", "visual_connectivity", "visual_mean_depth",
                    "visual_integration", "clustering", "isovist_area", "isovist_perimeter",
                    "isovist_compactness", "isovist_max_radial", "isovist_mean_radial",
                    "isovist_drift"]
            w.writerow(["plan", "cell", *keys])
            for r in results:
                for c, v in r.get("vga", {}).items():
                    w.writerow([r["plan"]["name"], c,
                                *[f"{v[k]:.5f}" if isinstance(v[k], float) else v[k] for k in keys]])


def print_report(r: dict, rules_name: str) -> None:
    g = r["global"]
    print(f"\n{'═'*74}\n  {r['plan']['name']}   (규칙: {rules_name})\n{'═'*74}")
    print(f"  {'실':<11}{'연결':>5}{'평균깊이':>9}{'RRA':>8}{'통합도':>8}"
          f"{'제어값':>8}{'선택도':>8}{'깊이':>6}{'j좌표':>8}")
    order = sorted(r["rooms"].items(),
                   key=lambda kv: -(kv[1]["measures"]["integration"]
                                    if kv[1]["measures"]["integration"] == kv[1]["measures"]["integration"] else -9))
    for k, v in order:
        m, s = v["measures"], v["syntactic"]
        print(f"  {v['label']:<11}{m['connectivity']:>5}{m['mean_depth']:>9.3f}{m['RRA']:>8.3f}"
              f"{m['integration']:>8.3f}{m['control_value']:>8.3f}{m['choice']:>8.3f}"
              f"{str(s['step_depth_from_carrier']):>6}{s['jx']:>8.1f}")
    print(f"  {'─'*70}")
    print(f"  노드 {g['node_count']} · 간선 {g['edge_count']} · 시스템 평균깊이 {g['mean_depth_system']:.3f} · "
          f"현관 최대깊이 {g['max_depth_from_carrier']}")
    print(f"  명료성(r²) {g['intelligibility']:.3f} · 차이계수 H* {g['difference_factor']:.3f} · "
          f"연결됨 {'O' if g['connected'] else 'X'}")
    if "mean_visual_integration" in g:
        print(f"  시각 통합도 {g['mean_visual_integration']:.3f} · 시각 연결도 {g['mean_visual_connectivity']:.1f} · "
              f"시각 명료성 {g['visual_intelligibility']:.3f} · 군집계수 {g['mean_clustering']:.3f}")


def compare_rules(spec, plan, outdir) -> list[dict]:
    print(f"\n{'═'*74}\n  규칙 비교 — 같은 도면, 다른 규칙  ({plan.name})\n{'═'*74}")
    print(f"  {'규칙':<14}{'노드':>5}{'간선':>5}{'평균깊이':>9}{'최대깊이':>9}"
          f"{'명료성':>8}{'H*':>7}{'시각통합':>9}")
    rows = []
    for name, rules in PRESET_RULES.items():
        r = extract(spec, plan, rules)
        g = r["global"]
        rows.append({"rules": name, "rules_detail": rules.as_dict(), **{k: g.get(k) for k in GLOBAL_COLS}})
        print(f"  {name:<14}{g['node_count']:>5}{g['edge_count']:>5}{g['mean_depth_system']:>9.3f}"
              f"{str(g['max_depth_from_carrier']):>9}{g['intelligibility']:>8.3f}"
              f"{g['difference_factor']:>7.3f}{g.get('mean_visual_integration', float('nan')):>9.3f}")
    with open(f"{outdir}/rules_comparison.json", "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2, default=str)
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description="Space Syntax 좌표 추출기")
    ap.add_argument("--spec", default="apartment_8x8", choices=list(SPECS))
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--plans", help="plans.json 경로 (여러 장)")
    src.add_argument("--plan-file", help="도면 파일 (아스키 격자 .txt 또는 사각형 .json)")
    src.add_argument("--generate", type=int, metavar="N", help="도면 N장을 즉석 생성해 분석")
    ap.add_argument("--rules", default="standard",
                    help=f"규칙 프리셋 {list(PRESET_RULES)} 또는 JSON 파일 경로")
    ap.add_argument("--dump-rules", metavar="PATH", help="규칙 템플릿 JSON을 쓰고 종료")
    ap.add_argument("--compare-rules", action="store_true", help="규칙 프리셋별 결과를 비교")
    ap.add_argument("--no-vga", action="store_true", help="가시성 분석(VGA)을 건너뛴다")
    ap.add_argument("--limit", type=int, default=3, help="콘솔에 출력할 도면 수")
    ap.add_argument("--out", default="out/syntax")
    ap.add_argument("--html", default="out/syntax/report.html")
    args = ap.parse_args()

    if args.dump_rules:
        with open(args.dump_rules, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_RULES.as_dict(), f, ensure_ascii=False, indent=2)
        print(f"규칙 템플릿을 {args.dump_rules}에 썼습니다. 값을 고쳐 --rules로 넘기세요.")
        print(json.dumps(DEFAULT_RULES.as_dict(), ensure_ascii=False, indent=2))
        return

    spec = SPECS[args.spec]
    os.makedirs(args.out, exist_ok=True)
    rules, rules_name = load_rules(args.rules)
    if args.no_vga:
        rules = SyntaxRules.from_dict({**rules.as_dict(), "vga_enabled": False})

    if args.plan_file:
        plans = load_plan_file(args.plan_file, spec)
    elif args.generate:
        from floorplan_bench.generate import generate_procedural
        plans = generate_procedural(spec, args.generate, seed=1)
    elif args.plans:
        plans = load_plans(args.plans)
    elif os.path.exists("out/plans.json"):
        plans = load_plans("out/plans.json")
    else:
        from floorplan_bench.generate import generate_procedural
        plans = generate_procedural(spec, 4, seed=1)
        print("입력 도면이 없어 4장을 생성했습니다. (--plans / --plan-file / --generate)")

    plans = [p for p in plans if p.spec_key == spec.key] or plans
    print(f"규칙 '{rules_name}': {json.dumps(rules.as_dict(), ensure_ascii=False)}")
    print(f"도면 {len(plans)}장 · 격자 {spec.width}×{spec.height}")

    results = []
    for p in plans:
        r = extract(spec, p, rules)
        r["assignment"] = p.assignment
        results.append(r)
    for r in results[:args.limit]:
        print_report(r, rules_name)

    comparison = compare_rules(spec, plans[0], args.out) if args.compare_rules else None

    with open(f"{args.out}/syntax.json", "w", encoding="utf-8") as f:
        json.dump({"spec": spec.key, "rules": rules.as_dict(), "rules_name": rules_name,
                   "results": results}, f, ensure_ascii=False, indent=1, default=str)
    write_csvs(results, args.out)

    from syntax_report import build_html
    build_html(spec, plans, results, rules, rules_name, comparison, args.html)
    print(f"\n→ {args.out}/syntax.json · syntax_rooms.csv · syntax_edges.csv"
          f"{' · syntax_cells.csv' if not args.no_vga else ''}")
    print(f"→ {args.html}")


if __name__ == "__main__":
    main()
