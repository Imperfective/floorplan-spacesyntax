"""4단계-B — D-Wave Ocean으로 같은 QUBO를 푼다 (양자 어닐링 계열).

샘플러 네 가지:
  sa     : SimulatedAnnealingSampler — 고전 시뮬레이티드 어닐링. **양자가 아니다.**
           양자 어닐러와 같은 QUBO/Ising 모델을 쓰지만 CPU에서 돈다. 토큰 없이 동작.
  tabu   : TabuSampler — 고전 타부 서치. 비교용 고전 기준선.
  qpu    : DWaveSampler + EmbeddingComposite — 실제 양자 어닐링 하드웨어.
  hybrid : LeapHybridSampler — 양자·고전 하이브리드. 큰 문제는 이쪽이 현실적.

qpu/hybrid는 DWAVE_API_TOKEN(또는 `dwave config create`)이 있어야 한다.
"""

from __future__ import annotations

import os
import time

import dimod

from .env import EnvWeights
from .plan import FloorPlan
from .qubo import build_bqm, bqm_stats, sample_to_x, x_violations
from .spec import BuildingSpec


def has_dwave_token() -> bool:
    if os.environ.get("DWAVE_API_TOKEN"):
        return True
    try:
        from dwave.cloud import Client

        Client.from_config()  # ~/.config/dwave/dwave.conf
        return True
    except Exception:
        return False


def available_samplers() -> dict[str, str]:
    out = {"sa": "시뮬레이티드 어닐링 (고전, 로컬)", "tabu": "타부 서치 (고전, 로컬)"}
    if has_dwave_token():
        out["qpu"] = "D-Wave QPU (실제 양자 어닐러)"
        out["hybrid"] = "Leap 하이브리드 (양자+고전)"
    return out


def _make_sampler(kind: str, bqm):
    if kind == "sa":
        from dwave.samplers import SimulatedAnnealingSampler

        return SimulatedAnnealingSampler(), {}
    if kind == "tabu":
        from dwave.samplers import TabuSampler

        return TabuSampler(), {}
    if kind == "qpu":
        from dwave.system import DWaveSampler, EmbeddingComposite

        return EmbeddingComposite(DWaveSampler()), {"return_embedding": True}
    if kind == "hybrid":
        from dwave.system import LeapHybridSampler

        return LeapHybridSampler(), {}
    raise ValueError(f"알 수 없는 샘플러: {kind}")


def solve(
    spec: BuildingSpec,
    w: EnvWeights,
    sampler: str = "auto",
    num_reads: int = 500,
    num_sweeps: int = 2000,
    seed: int | None = 7,
) -> dict:
    bqm = build_bqm(spec, w)
    stats = bqm_stats(bqm)

    if sampler == "auto":
        sampler = "hybrid" if has_dwave_token() else "sa"

    smp, extra = _make_sampler(sampler, bqm)
    kwargs = dict(extra)
    if sampler == "sa":
        kwargs.update(num_reads=num_reads, num_sweeps=num_sweeps, seed=seed)
    elif sampler == "tabu":
        kwargs.update(num_reads=max(10, num_reads // 10), seed=seed)
    elif sampler == "qpu":
        kwargs.update(num_reads=num_reads)

    t0 = time.perf_counter()
    sampleset = smp.sample(bqm, **kwargs)
    sampleset.resolve()
    elapsed = time.perf_counter() - t0

    best = sampleset.first
    x = sample_to_x(best.sample)
    viol = x_violations(spec, x)

    raw_plan = FloorPlan.from_vector(spec, x, f"D-Wave({sampler}) 원시해", f"dwave-{sampler}")
    fixed_plan = raw_plan.repair(spec)
    fixed_plan.name = f"D-Wave({sampler}) 보정안"

    energies = sorted(float(e) for e in sampleset.record.energy)
    result = {
        "engine": f"D-Wave Ocean · {sampler}",
        "sampler": sampler,
        "is_quantum": sampler in ("qpu", "hybrid"),
        "plan": fixed_plan,
        "raw_plan": raw_plan,
        "raw_x": x,
        "energy": float(best.energy),  # QUBO 원시해의 에너지 (제약 위반 페널티 포함)
        "repaired_energy": bqm.energy(fixed_plan.to_vector(spec)),
        "feasible_raw": viol["empty_cells"] == 0
        and viol["overlapped_cells"] == 0
        and viol["total_area_sq_error"] == 0,
        "violations": viol,
        "wall_time": elapsed,
        "num_samples": len(sampleset),
        "energy_best": energies[0],
        "energy_median": energies[len(energies) // 2],
        "energy_worst": energies[-1],
        "bqm": stats,
    }

    info = sampleset.info or {}
    if "timing" in info:
        result["qpu_timing"] = info["timing"]
    if "embedding_context" in info:
        emb = info["embedding_context"].get("embedding") or {}
        if emb:
            chains = [len(v) for v in emb.values()]
            result["embedding"] = {
                "logical_vars": len(chains),
                "physical_qubits": sum(chains),
                "max_chain_length": max(chains),
            }
    return result
