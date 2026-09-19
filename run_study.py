"""전체 연구 실행 — 주 비교 + 환경 변수 10종 스윕 + 진단 실험 5종."""
from __future__ import annotations

import json, platform, sys, time
from datetime import datetime

import dimod, ortools
from floorplan_bench import diagnose, solve_dwave, solve_ortools
from floorplan_bench.env import PRESETS
from floorplan_bench.generate import generate_plans
from floorplan_bench.plan import FloorPlan
from floorplan_bench.qubo import build_bqm, bqm_stats
from floorplan_bench.spec import SPECS
from floorplan_bench.terms import TERM_META, raw_values

SPEC = SPECS["apartment_8x8"]
BASE_ENV = "balanced"
CPSAT_LIMIT = 60.0
SA_READS, SA_SWEEPS = 2000, 5000
SWAP_ITER, SWAP_RESTARTS = 300_000, 8
SEED = 1

def frag(a):
    return sum(1 for c in FloorPlan(SPEC.key, "", a).coordinates(SPEC).values()
               if c["components"] > 1)

def pack(a, energy, wall, **extra):
    """해를 찾지 못한 경우(plan=None)도 안전하게 기록한다."""
    if a is None:
        return {"assignment": None, "energy": None, "wall_time": wall,
                "terms": None, "components": None, "failed": True, **extra}
    return {"assignment": a, "energy": float(energy), "wall_time": wall,
            "terms": raw_values(SPEC, a), "components": frag(a), **extra}


def plan_of(r):
    return r["plan"].assignment if r.get("plan") else None


def dump(S, path="out/study.json"):
    """단계마다 중간 저장 — 뒤에서 실패해도 앞의 결과를 잃지 않는다."""
    json.dump(S, open(path, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1, default=str)

t_all = time.perf_counter()
S: dict = {"meta": {
    "date": datetime.now().isoformat(timespec="seconds"),
    "spec": SPEC.key, "spec_name": SPEC.name,
    "grid": [SPEC.width, SPEC.height], "cells": SPEC.n_cells,
    "rooms": [{"key": r.key, "name": r.name, "area": r.area,
               "needs_window": r.needs_window, "privacy": r.privacy, "public": r.public,
               "noise": r.noise, "quiet": r.quiet, "wet": r.wet, "color": r.color}
              for r in SPEC.rooms],
    "entrance": list(SPEC.entrance), "plumbing_core": list(SPEC.plumbing_core),
    "adjacency": [[a, b, wt] for a, b, wt in SPEC.adjacency_pairs()],
    "terms": [{"key": t.key, "label": t.label, "sign": t.sign, "form": t.form,
               "weight_field": t.weight_field, "question": t.question,
               "normalizer": t.normalizer} for t in TERM_META],
    "presets": {k: v.as_dict() for k, v in PRESETS.items()},
    "base_env": BASE_ENV,
    "budgets": {"cpsat_seconds": CPSAT_LIMIT, "sa_reads": SA_READS,
                "sa_sweeps": SA_SWEEPS, "swap_iter": SWAP_ITER,
                "swap_restarts": SWAP_RESTARTS, "seed": SEED},
    "env": {"python": sys.version.split()[0], "platform": platform.platform(),
            "machine": platform.machine(), "processor": platform.processor(),
            "ortools": ortools.__version__ if hasattr(ortools, "__version__") else "9.15.6755",
            "dimod": dimod.__version__},
}}
W = PRESETS[BASE_ENV]
S["meta"]["bqm"] = bqm_stats(build_bqm(SPEC, W))

# ── 1단계 생성 ────────────────────────────────────────────────
print("[1] 도면 생성", flush=True)
plans, backend = generate_plans(SPEC, 8, "auto", W.description, SEED)
S["backend"] = backend
S["plans"] = [{"name": p.name, "source": p.source, "assignment": p.assignment,
               "energy": p.score(SPEC, W), "terms": p.raw_terms(SPEC),
               "components": frag(p.assignment),
               "rationale": p.meta.get("rationale", "")} for p in plans]
baseline = min(plans, key=lambda p: p.score(SPEC, W))
S["baseline"] = pack(baseline.assignment, baseline.score(SPEC, W), 0.0, name=baseline.name)
print(f"    {backend} · {len(plans)}장 · 최고 {baseline.score(SPEC, W):+.3f}", flush=True)

# ── 주 비교 ──────────────────────────────────────────────────
print("[4] 주 비교", flush=True)
o = solve_ortools.solve(SPEC, W, time_limit=CPSAT_LIMIT)
S["ortools"] = pack(o["plan"].assignment, o["energy"], o["wall_time"],
                    status=o["status"], proven=o["proven_optimal"],
                    bound=o["best_bound"], branches=o["branches"],
                    model_vars=o["model_vars"], quad_terms=o["quad_terms"])
print(f"    CP-SAT        {o['energy']:+8.3f} 하한{o['best_bound']:+8.3f} 조각{frag(o['plan'].assignment)}", flush=True)

oc = solve_ortools.solve(SPEC, W, time_limit=CPSAT_LIMIT, connected=True,
                         hint=baseline.assignment)
S["ortools_connected"] = pack(oc["plan"].assignment, oc["energy"], oc["wall_time"],
                              status=oc["status"], proven=oc["proven_optimal"],
                              bound=oc["best_bound"])
print(f"    CP-SAT+연결성 {oc['energy']:+8.3f} 하한{oc['best_bound']:+8.3f} 조각{frag(oc['plan'].assignment)}", flush=True)

d = solve_dwave.solve(SPEC, W, sampler="sa", num_reads=SA_READS, num_sweeps=SA_SWEEPS)
S["dwave"] = pack(d["plan"].assignment, d["repaired_energy"], d["wall_time"],
                  sampler=d["sampler"], is_quantum=d["is_quantum"],
                  raw_energy=d["energy"], feasible_raw=d["feasible_raw"],
                  violations=d["violations"], num_samples=d["num_samples"],
                  energy_best=d["energy_best"], energy_median=d["energy_median"],
                  energy_worst=d["energy_worst"])
print(f"    D-Wave SA     {d['repaired_energy']:+8.3f} 조각{frag(d['plan'].assignment)}", flush=True)

sw = diagnose.e4_swap_annealer(SPEC, W, n_iter=SWAP_ITER, n_restarts=SWAP_RESTARTS)
S["swap_anneal"] = pack(sw["assignment"], sw["energy"], sw["wall_time"],
                        feasible=sw["feasible"])
print(f"    교환 어닐링    {sw['energy']:+8.3f} 조각{sw['components']} ({sw['wall_time']:.0f}s)", flush=True)

# ── 진단 실험 ────────────────────────────────────────────────
print("[진단] E1 이동 장벽", flush=True)
S["e1"] = diagnose.e1_barriers(SPEC, W, n_states=40, n_moves=40, seed=SEED)
for k in ("flip_1bit", "reassign_2bit", "swap_4bit"):
    st = S["e1"][k]
    print(f"    {k:16s} 중앙값{st['median']:+8.3f} 개선{st['improving_ratio']:5.1%}", flush=True)

print("[진단] E2 어닐링 예산", flush=True)
S["e2"] = diagnose.e2_budget(SPEC, W, num_reads=200, seed=SEED)

print("[진단] E3 최적해에서 출발", flush=True)
S["e3"] = diagnose.e3_seeded(SPEC, W, oc["plan"].assignment,
                             num_reads=100, num_sweeps=SA_SWEEPS, seed=SEED)
print(f"    시작 {S['e3']['seed_energy']:+.3f}(조각{S['e3']['seed_components']}) "
      f"→ 종료 {S['e3']['final_energy']:+.3f}(조각{S['e3']['final_components']})", flush=True)

print("[진단] E5 페널티 스케일", flush=True)
S["e5"] = diagnose.e5_penalty(SPEC, W, num_reads=400, num_sweeps=SA_SWEEPS, seed=SEED)

# ── 환경 변수 10종 스윕 ────────────────────────────────────────
print("[스윕] 환경 변수 10종 × 3엔진", flush=True)
S["sweep"] = {}
for key, w in PRESETS.items():
    t0 = time.perf_counter()
    oo = solve_ortools.solve(SPEC, w, time_limit=CPSAT_LIMIT, connected=True,
                             hint=baseline.assignment)
    dd = solve_dwave.solve(SPEC, w, sampler="sa", num_reads=SA_READS, num_sweeps=SA_SWEEPS)
    ss = diagnose.e4_swap_annealer(SPEC, w, n_iter=SWAP_ITER, n_restarts=SWAP_RESTARTS)
    S["sweep"][key] = {
        "name": w.name, "description": w.description, "weights": w.as_dict(),
        "ortools": pack(plan_of(oo), oo.get("energy"), oo["wall_time"],
                        proven=oo.get("proven_optimal"), bound=oo.get("best_bound"),
                        status=oo.get("status")),
        "dwave": pack(plan_of(dd), dd["repaired_energy"], dd["wall_time"],
                      raw_energy=dd["energy"], feasible_raw=dd["feasible_raw"],
                      energy_best=dd["energy_best"], energy_median=dd["energy_median"]),
        "swap": pack(ss["assignment"], ss["energy"], ss["wall_time"],
                     feasible=ss["feasible"]),
    }
    print(f"    {key:13s} CP-SAT{oo['energy']:+8.3f}(조각{frag(oo['plan'].assignment)})  "
          f"D-Wave{dd['repaired_energy']:+8.3f}(조각{frag(dd['plan'].assignment)})  "
          f"교환{ss['energy']:+8.3f}(조각{ss['components']})  {time.perf_counter()-t0:.0f}s", flush=True)

S["meta"]["total_wall_time"] = time.perf_counter() - t_all
dump(S)
print(f"\n→ out/study.json 저장 (총 {S['meta']['total_wall_time']/60:.1f}분)", flush=True)
