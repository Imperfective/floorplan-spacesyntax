"""AI 생성 건물 도면 평가 — OR-Tools(고전) vs D-Wave(양자 어닐링) 비교.

    1. AI가 도면을 생성한다              (floorplan_bench.generate)
    2. 좌표로 변환해 데이터화한다        (floorplan_bench.plan)
    3. '좋은 도면'의 환경 변수를 정의한다 (floorplan_bench.env)
    4. 두 엔진으로 각각 비교한다          (solve_ortools / solve_dwave)

실행:
    .venv/bin/python main.py --spec apartment_8x8 --env balanced
"""

from __future__ import annotations

import argparse
import json
import os

from floorplan_bench import solve_dwave, solve_ortools
from floorplan_bench.env import PRESETS, get_env
from floorplan_bench.generate import generate_plans
from floorplan_bench.plan import save_plans
from floorplan_bench.qubo import build_bqm, bqm_stats
from floorplan_bench.report import TERM_LABELS, text_summary
from floorplan_bench.spec import SPECS

BAR = "═" * 78


def hdr(n: int, title: str) -> None:
    print(f"\n{BAR}\n  {n}단계 · {title}\n{BAR}")


def run(args) -> dict:
    spec = SPECS[args.spec]
    w = get_env(args.env)
    os.makedirs(args.outdir, exist_ok=True)
    results: dict = {"spec": spec.key, "spec_name": spec.name, "env": w.key}

    # ── 1단계 ────────────────────────────────────────────────────────
    hdr(1, f"AI 도면 생성 — {spec.name}")
    plans, backend = generate_plans(spec, args.n_plans, args.backend, w.description, args.seed)
    print(f"생성기: {backend}   도면 {len(plans)}장")
    for p in plans:
        print(f"  · {p.name:26s} 유효={'O' if p.is_feasible(spec) else 'X'}"
              + (f"  «{p.meta['rationale'][:44]}»" if p.meta.get("rationale") else ""))
    results["backend"] = backend

    # ── 2단계 ────────────────────────────────────────────────────────
    hdr(2, "좌표 변환 및 데이터화")
    coords = plans[0].coordinates(spec)
    print(f"예시: {plans[0].name}")
    print(f"  {'방':<10}{'면적':>6}{'요구':>6}{'덩어리':>7}{'외벽셀':>7}{'벽길이':>7}  바운딩박스")
    for key, c in coords.items():
        bb = c["bbox"]
        print(f"  {c['name']:<10}{c['area']:>6}{c['target_area']:>6}{c['components']:>7}"
              f"{c['perimeter_cells']:>7}{c['wall_length']:>7}  {bb}")
    save_plans(plans, f"{args.outdir}/plans.json")
    with open(f"{args.outdir}/coordinates.json", "w", encoding="utf-8") as f:
        json.dump({p.name: p.coordinates(spec) for p in plans}, f, ensure_ascii=False, indent=2)
    print(f"  → {args.outdir}/plans.json, {args.outdir}/coordinates.json 저장")

    # ── 3단계 ────────────────────────────────────────────────────────
    hdr(3, "'좋은 도면' 환경 변수")
    print(f"  {'키':<11}{'이름':<16}{'인접':>6}{'응집':>6}{'채광':>6}{'사적':>6}{'동선':>6}")
    for k, e in PRESETS.items():
        mark = "◀ 선택" if k == w.key else ""
        print(f"  {k:<11}{e.name:<16}{e.w_adjacency:>6.1f}{e.w_compactness:>6.1f}"
              f"{e.w_daylight:>6.1f}{e.w_privacy:>6.1f}{e.w_circulation:>6.1f} {mark}")

    # 같은 도면이라도 환경이 바뀌면 순위가 바뀐다
    print("\n  ▸ 환경 변수별 1위 도면 (같은 도면 집합, 다른 잣대)")
    env_rank = {}
    for k, e in PRESETS.items():
        ranked = sorted(plans, key=lambda p: p.score(spec, e))
        env_rank[k] = [(p.name, p.score(spec, e)) for p in ranked]
        print(f"    {e.name:<16} 1위 {ranked[0].name:<22} ({ranked[0].score(spec, e):+.3f})")
    results["env_rank"] = env_rank

    # ── 4단계 ────────────────────────────────────────────────────────
    hdr(4, f"엔진 비교 — 환경 '{w.name}'")
    bqm = build_bqm(spec, w)
    st = bqm_stats(bqm)
    print(f"공통 QUBO: 변수 {st['variables']}개, 결합 {st['interactions']}개, 밀도 {st['density']:.3f}")

    baseline = min(plans, key=lambda p: p.score(spec, w))
    print(f"\n[기준선] AI 생성 도면 중 최고: {baseline.name}")
    print(text_summary(spec, baseline, w, "         "))

    print(f"\n[A1] OR-Tools CP-SAT — D-Wave와 동일 조건(연결성 제약 없음), 제한시간 {args.time_limit}s")
    ort = solve_ortools.solve(spec, w, time_limit=args.time_limit)
    print(f"     상태={ort['status']}  최적성 증명={'O' if ort['proven_optimal'] else 'X'}  "
          f"하한={ort['best_bound']:+.3f}  {ort['wall_time']:.2f}s  분기 {ort['branches']:,}회")
    print(text_summary(spec, ort["plan"], w, "     "))

    print(f"\n[A2] OR-Tools CP-SAT + 연결성 제약 — QUBO로는 표현 불가능한 제약")
    ortc = solve_ortools.solve(spec, w, time_limit=args.time_limit, connected=True)
    print(f"     상태={ortc['status']}  최적성 증명={'O' if ortc['proven_optimal'] else 'X'}  "
          f"하한={ortc['best_bound']:+.3f}  {ortc['wall_time']:.2f}s")
    print(text_summary(spec, ortc["plan"], w, "     "))

    print(f"\n[B] D-Wave Ocean ({args.dwave}) — 같은 QUBO, 샘플 {args.num_reads}회")
    dw = solve_dwave.solve(spec, w, sampler=args.dwave,
                           num_reads=args.num_reads, num_sweeps=args.num_sweeps)
    v = dw["violations"]
    print(f"    엔진={dw['engine']}  양자하드웨어={'O' if dw['is_quantum'] else 'X(고전 시뮬레이션)'}  "
          f"{dw['wall_time']:.2f}s")
    print(f"    원시해 제약 충족={'O' if dw['feasible_raw'] else 'X'} "
          f"(빈 셀 {v['empty_cells']}, 중복 셀 {v['overlapped_cells']}, 면적오차제곱합 {v['total_area_sq_error']})")
    print(f"    샘플 에너지 최저 {dw['energy_best']:+.3f} / 중앙 {dw['energy_median']:+.3f} "
          f"/ 최악 {dw['energy_worst']:+.3f}")
    print(text_summary(spec, dw["plan"], w, "    "))

    # ── 최종 비교표 ───────────────────────────────────────────────────
    print(f"\n{BAR}\n  최종 비교 (에너지가 낮을수록 좋은 도면)\n{BAR}")
    rows = [
        ("AI 생성 최고안 (기준선)", baseline.score(spec, w), "-", baseline),
        ("OR-Tools (동일 조건)", ort["energy"], f"{ort['wall_time']:.2f}s", ort["plan"]),
        ("OR-Tools + 연결성 제약", ortc["energy"], f"{ortc['wall_time']:.2f}s", ortc["plan"]),
        (f"D-Wave {dw['sampler']}", dw["repaired_energy"], f"{dw['wall_time']:.2f}s", dw["plan"]),
    ]
    best_e = min(r[1] for r in rows)
    print(f"  {'방법':<26}{'에너지':>10}{'기준선 대비':>12}{'최고 대비':>11}{'시간':>9}  {'조각난 방':>9}")
    for name, e, t, plan in rows:
        frag = sum(1 for c in plan.coordinates(spec).values() if c["components"] > 1)
        vs_base = (baseline.score(spec, w) - e)
        gap = e - best_e
        print(f"  {name:<26}{e:>10.3f}{vs_base:>+12.3f}{gap:>+11.3f}{t:>9}  {frag:>9}")

    for name, e, t, plan in rows:
        print(f"\n  ── {name} ──")
        print("  " + plan.to_ascii(spec).replace("\n", "\n  "))

    results.update({
        "weights": w.as_dict(), "bqm": st,
        "plans": [{"name": p.name, "source": p.source, "score": p.score(spec, w),
                   "terms": p.raw_terms(spec), "assignment": p.assignment,
                   "rationale": p.meta.get("rationale", "")} for p in plans],
        "baseline": {"name": baseline.name, "energy": baseline.score(spec, w),
                     "assignment": baseline.assignment, "terms": baseline.raw_terms(spec)},
        "ortools": {k: v for k, v in ort.items() if k not in ("plan", "raw_x")}
        | {"assignment": ort["plan"].assignment, "terms": ort["plan"].raw_terms(spec)},
        "ortools_connected": {k: v for k, v in ortc.items() if k not in ("plan", "raw_x")}
        | {"assignment": ortc["plan"].assignment, "terms": ortc["plan"].raw_terms(spec)},
        "dwave": {k: v for k, v in dw.items() if k not in ("plan", "raw_plan", "raw_x", "bqm")}
        | {"assignment": dw["plan"].assignment, "raw_assignment": dw["raw_plan"].assignment,
           "terms": dw["plan"].raw_terms(spec)},
    })
    with open(f"{args.outdir}/results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n  → {args.outdir}/results.json 저장")
    return results


def main() -> None:
    ap = argparse.ArgumentParser(description="AI 도면 평가: OR-Tools vs D-Wave")
    ap.add_argument("--spec", default="apartment_8x8", choices=list(SPECS))
    ap.add_argument("--env", default="balanced", choices=list(PRESETS))
    ap.add_argument("--n-plans", type=int, default=6)
    ap.add_argument("--backend", default="auto", choices=["auto", "claude", "procedural"])
    ap.add_argument("--time-limit", type=float, default=30.0, help="CP-SAT 제한시간(초)")
    ap.add_argument("--dwave", default="auto", choices=["auto", "sa", "tabu", "qpu", "hybrid"])
    ap.add_argument("--num-reads", type=int, default=2000)
    ap.add_argument("--num-sweeps", type=int, default=4000)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--no-connectivity", action="store_true", help="연결성 제약 비교를 건너뛴다")
    ap.add_argument("--outdir", default="out")
    run(ap.parse_args())


if __name__ == "__main__":
    main()
