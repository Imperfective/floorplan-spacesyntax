"""진단 실험 — D-Wave 쪽 도면의 방이 모두 조각난 이유를 규명한다.

가설 H: 원인은 '어닐링'이 아니라 'QUBO 인코딩'이다.
  one-hot(셀 배타성) + 카디널리티(면적) 제약을 페널티로 녹이면,
  실현 가능한 해들은 서로 높은 페널티 장벽으로 격리된 고립점이 된다.
  단일 비트 뒤집기로 움직이는 어닐러는 이 장벽을 넘지 못하고,
  '제약은 만족하지만 품질은 임의에 가까운' 상태에서 얼어붙는다.

E1 이동 장벽 측정        — 움직임 종류별 ΔE 분포
E2 어닐링 예산 스윕      — 시간을 늘리면 나아지는가 (예산 부족인가, 구조 문제인가)
E3 좋은 해에서 출발      — 최적해를 주면 지키는가, 무너뜨리는가
E4 제약 보존 어닐러      — 인코딩만 바꾸고 어닐링은 그대로 두면 어떻게 되는가
E5 페널티 스케일 스윕    — 벌점을 낮추면 품질이 오르는가 (실현가능성과의 맞교환)
"""

from __future__ import annotations

import math
import random
import time

from .env import EnvWeights
from .plan import FloorPlan
from .qubo import build_bqm, sample_to_x, x_violations
from .spec import BuildingSpec
from .terms import quality_coeffs, raw_values


# ══════════════════════════════════════════ 품질 에너지의 국소 계산기
class QualityEnergy:
    """품질 항만의 에너지를 국소적으로(변한 셀 주변만) 다시 계산한다."""

    def __init__(self, spec: BuildingSpec, w: EnvWeights):
        self.spec = spec
        lin, quad, const = quality_coeffs(spec, w)
        self.lin = lin
        self.quad = quad
        self.const = const
        self.inc = {c: [] for c in spec.cells}  # 셀 → 맞닿은 변 목록
        for c, d in spec.neighbor_pairs:
            self.inc[c].append((c, d))
            self.inc[d].append((c, d))

    def _edge(self, a, c, d) -> float:
        u, v = (a[c], c), (a[d], d)
        if u is None or v is None:
            return 0.0
        k = (u, v) if u <= v else (v, u)
        return self.quad.get(k, 0.0)

    def total(self, a) -> float:
        e = self.const
        for c, key in enumerate(a):
            if key is not None:
                e += self.lin.get((key, c), 0.0)
        for c, d in self.spec.neighbor_pairs:
            e += self._edge(a, c, d)
        return e

    def local(self, a, cells) -> float:
        """주어진 셀들의 1차항 + 그 셀에 맞닿은 모든 변의 2차항."""
        e = 0.0
        seen = set()
        for c in cells:
            if a[c] is not None:
                e += self.lin.get((a[c], c), 0.0)
            for edge in self.inc[c]:
                if edge not in seen:
                    seen.add(edge)
                    e += self._edge(a, *edge)
        return e

    def delta_swap(self, a, c, d) -> float:
        """셀 c와 d의 방을 맞바꿀 때의 ΔE (면적·배타성은 그대로 유지된다)."""
        before = self.local(a, (c, d))
        a[c], a[d] = a[d], a[c]
        after = self.local(a, (c, d))
        a[c], a[d] = a[d], a[c]
        return after - before


def random_feasible(spec: BuildingSpec, rng: random.Random) -> list:
    pool = [r.key for r in spec.rooms for _ in range(r.area)]
    rng.shuffle(pool)
    return pool


# ══════════════════════════════════════════ E1 — 이동 장벽 측정
def e1_barriers(spec, w, n_states=60, n_moves=60, seed=0) -> dict:
    """세 가지 움직임의 ΔE 분포. 어닐러가 넘어야 하는 벽의 높이를 잰다."""
    rng = random.Random(seed)
    bqm = build_bqm(spec, w)
    qe = QualityEnergy(spec, w)
    flip1, move2, swap4, swap_q = [], [], [], []

    for _ in range(n_states):
        a = random_feasible(spec, rng)
        x = FloorPlan(spec.key, "", a).to_vector(spec)
        e0 = bqm.energy(x)

        for _ in range(n_moves):
            # (1) 비트 하나 뒤집기 — 어닐러가 실제로 하는 움직임
            c = rng.randrange(spec.n_cells)
            v = (a[c], c)
            x[v] = 0
            flip1.append(bqm.energy(x) - e0)
            x[v] = 1

            # (2) 셀 하나를 다른 방에 넘기기 (비트 2개) — 배타성은 유지, 면적은 깨짐
            s = rng.choice([k for k in spec.room_keys if k != a[c]])
            x[v] = 0
            x[(s, c)] = 1
            move2.append(bqm.energy(x) - e0)
            x[(s, c)] = 0
            x[v] = 1

            # (3) 두 셀의 방을 맞바꾸기 (비트 4개) — 모든 하드 제약 유지
            d = rng.randrange(spec.n_cells)
            if a[c] == a[d]:
                continue
            u, t = (a[c], c), (a[d], d)
            x[u] = x[t] = 0
            x[(a[d], c)] = x[(a[c], d)] = 1
            swap4.append(bqm.energy(x) - e0)
            x[(a[d], c)] = x[(a[c], d)] = 0
            x[u] = x[t] = 1
            swap_q.append(qe.delta_swap(a, c, d))

    def stat(v):
        v = sorted(v)
        return {"n": len(v), "min": v[0], "median": v[len(v) // 2], "max": v[-1],
                "mean": sum(v) / len(v),
                "improving_ratio": sum(1 for z in v if z < 0) / len(v)}

    return {
        "flip_1bit": stat(flip1),
        "reassign_2bit": stat(move2),
        "swap_4bit": stat(swap4),
        "swap_quality_only": stat(swap_q),
        "p_cell": w.p_cell, "p_area": w.p_area,
    }


# ══════════════════════════════════════════ E2 — 어닐링 예산 스윕
def e2_budget(spec, w, sweeps=(500, 1000, 2000, 5000, 10000, 25000, 50000),
              num_reads=200, seed=7) -> list[dict]:
    from dwave.samplers import SimulatedAnnealingSampler

    bqm = build_bqm(spec, w)
    smp = SimulatedAnnealingSampler()
    out = []
    for ns in sweeps:
        t0 = time.perf_counter()
        ss = smp.sample(bqm, num_reads=num_reads, num_sweeps=ns, seed=seed)
        el = time.perf_counter() - t0
        best = ss.first
        plan = FloorPlan.from_vector(spec, sample_to_x(best.sample), "", "")
        v = raw_values(spec, plan.assignment)
        viol = x_violations(spec, sample_to_x(best.sample))
        out.append({
            "num_sweeps": ns, "wall_time": el, "energy": float(best.energy),
            "energy_median": float(sorted(ss.record.energy)[len(ss) // 2]),
            "compactness": v["compactness"],
            "components": sum(1 for c in plan.coordinates(spec).values()
                              if c["components"] > 1),
            "feasible": viol["empty_cells"] == 0 and viol["overlapped_cells"] == 0
            and viol["total_area_sq_error"] == 0,
        })
        print(f"    E2 sweeps={ns:>6,}  E={best.energy:+8.3f}  응집={v['compactness']:.3f}  {el:.1f}s", flush=True)
    return out


# ══════════════════════════════════════════ E3 — 좋은 해에서 출발
def e3_seeded(spec, w, seed_assignment, num_reads=100, num_sweeps=5000, seed=7) -> dict:
    from dwave.samplers import SimulatedAnnealingSampler

    bqm = build_bqm(spec, w)
    start = FloorPlan(spec.key, "", list(seed_assignment)).to_vector(spec)
    e_start = bqm.energy(start)
    v_start = raw_values(spec, seed_assignment)

    ss = SimulatedAnnealingSampler().sample(
        bqm, num_reads=num_reads, num_sweeps=num_sweeps, seed=seed,
        initial_states=start, initial_states_generator="tile")
    best = ss.first
    plan = FloorPlan.from_vector(spec, sample_to_x(best.sample), "", "")
    v_end = raw_values(spec, plan.assignment)
    return {
        "seed_energy": e_start, "final_energy": float(best.energy),
        "delta": float(best.energy) - e_start,
        "seed_compactness": v_start["compactness"],
        "final_compactness": v_end["compactness"],
        "seed_components": sum(1 for c in FloorPlan(spec.key, "", list(seed_assignment))
                               .coordinates(spec).values() if c["components"] > 1),
        "final_components": sum(1 for c in plan.coordinates(spec).values()
                                if c["components"] > 1),
        "assignment": plan.assignment,
    }


# ══════════════════════════════════════════ E4 — 제약 보존 어닐러
def e4_swap_annealer(spec, w, n_iter=400_000, t0=0.35, t1=0.0015,
                     n_restarts=8, seed=11) -> dict:
    """어닐링은 그대로, 인코딩만 바꾼다.

    상태 공간을 '실현 가능한 도면'으로 제한하고, 움직임을 두 셀의 교환으로 둔다.
    하드 제약은 구조적으로 항상 만족되므로 페널티 장벽이 아예 존재하지 않는다.
    비교 대상은 동일한 품질 에너지 함수다.
    """
    rng = random.Random(seed)
    qe = QualityEnergy(spec, w)
    bqm = build_bqm(spec, w)
    best_a, best_e = None, math.inf
    t_start = time.perf_counter()

    for _ in range(n_restarts):
        a = random_feasible(spec, rng)
        e = qe.total(a)
        ratio = (t1 / t0) ** (1.0 / n_iter)
        T = t0
        for _ in range(n_iter):
            T *= ratio
            c = rng.randrange(spec.n_cells)
            d = rng.randrange(spec.n_cells)
            if a[c] == a[d]:
                continue
            de = qe.delta_swap(a, c, d)
            if de <= 0 or rng.random() < math.exp(-de / T):
                a[c], a[d] = a[d], a[c]
                e += de
        if e < best_e:
            best_e, best_a = e, list(a)

    elapsed = time.perf_counter() - t_start
    plan = FloorPlan(spec.key, "제약 보존 어닐링", best_a, "swap-anneal")
    return {
        "energy": bqm.energy(plan.to_vector(spec)),
        "quality_energy": best_e,
        "wall_time": elapsed,
        "n_iter": n_iter, "n_restarts": n_restarts,
        "terms": raw_values(spec, best_a),
        "components": sum(1 for c in plan.coordinates(spec).values()
                          if c["components"] > 1),
        "feasible": plan.is_feasible(spec),
        "assignment": best_a,
    }


# ══════════════════════════════════════════ E5 — 페널티 스케일 스윕
def e5_penalty(spec, w, factors=(0.1, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0),
               num_reads=400, num_sweeps=5000, seed=7) -> list[dict]:
    from dwave.samplers import SimulatedAnnealingSampler

    smp = SimulatedAnnealingSampler()
    out = []
    for f in factors:
        wf = w.scaled(p_cell=w.p_cell * f, p_area=w.p_area * f)
        bqm_f = build_bqm(spec, wf)
        ss = smp.sample(bqm_f, num_reads=num_reads, num_sweeps=num_sweeps, seed=seed)
        feas, qual, comp = 0, [], []
        for rec in ss.record:
            x = {v: int(val) for v, val in zip(ss.variables, rec.sample)}
            viol = x_violations(spec, x)
            ok = (viol["empty_cells"] == 0 and viol["overlapped_cells"] == 0
                  and viol["total_area_sq_error"] == 0)
            feas += ok
            if ok:
                pl = FloorPlan.from_vector(spec, x, "", "")
                qual.append(pl.score(spec, w))  # 원래 가중치로 채점
                comp.append(raw_values(spec, pl.assignment)["compactness"])
        out.append({
            "factor": f, "p_cell": wf.p_cell, "p_area": wf.p_area,
            "feasible_rate": feas / len(ss.record),
            "best_quality": min(qual) if qual else None,
            "median_quality": sorted(qual)[len(qual) // 2] if qual else None,
            "best_compactness": max(comp) if comp else None,
        })
        print(f"    E5 ×{f:<5g} 실현가능 {feas / len(ss.record):5.1%}  "
              f"최고품질 {out[-1]['best_quality'] if qual else float('nan'):+8.3f}", flush=True)
    return out
