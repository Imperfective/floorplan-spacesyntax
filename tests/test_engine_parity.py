"""웹 엔진(docs/aihub-engine.js)과 파이썬 평가기가 같은 값을 내는지 — node가 있을 때만.

    python tests/test_engine_parity.py [라벨 폴더]   (폴더를 안 주면 합성 도면으로)

세대별 문·위반·지표·특징·총점, 통계 JSON, 그리고 그 세대들로 만든 정답지(baseline)와
정답지 근접도(typicality)를 비교한다. 정답지는 같은 특징 행을 node에 넘겨 계산만 따로도 견준다.
"""
import glob
import json
import math
import os
import random
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from floorplan_bench.aihub import load_units  # noqa: E402
from floorplan_bench.criteria import Config  # noqa: E402
from floorplan_bench.evaluate import (SCORED, build_baseline, evaluate, scoring_params, split_params,  # noqa: E402
                                      typicality)
from floorplan_bench.stats import aggregate, stat_row  # noqa: E402
from tests.test_aihub_eval import GOOD, coco  # noqa: E402

DUMP = os.path.join(ROOT, "tests", "engine_dump.js")


def same(a, b, tol=1e-6) -> bool:
    if isinstance(a, float) and math.isnan(a):   # 파이썬 NaN ↔ JSON null
        return b is None or (isinstance(b, float) and math.isnan(b))
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) <= tol * max(1.0, abs(a), abs(b))
    return a == b


def _node(*args) -> dict | None:
    node = shutil.which("node")
    if not node:
        return None
    return json.loads(subprocess.run([node, DUMP, *args], capture_output=True, check=True,
                                     encoding="utf-8").stdout)


def _plain(o):
    """JSON으로 넘길 값 — NaN·무한대는 null (웹에서도 fin()이 아니라 같은 취급)."""
    if isinstance(o, float) and not math.isfinite(o):
        return None
    if isinstance(o, dict):
        return {k: _plain(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_plain(v) for v in o]
    return o


def _brief(t):
    """engine_dump.js의 brief와 같은 모양 — 정답지 근접도에서 비교할 숫자만."""
    if not t:
        return None
    return {"reference": t["reference"], "score": t["score"],
            "domains": {d: x["score"] for d, x in t["domains"].items()},
            "features": {k: x["score"] for k, x in t["features"].items()}}


def compare(files: list[str], params: dict | None = None) -> list[str]:
    params = params or {}
    dump = _node(*(["--params", json.dumps(params)] if params else []), *files)
    if dump is None:
        print("node 없음 — 건너뜀")
        return []
    lo, ep = split_params(params)
    js = dump["units"]
    py, rows, units = [], [], []
    for f in files:
        for u in load_units(f, lo):
            units.append(u)
            py.append(evaluate(u, rules=ep))
            rows.append(stat_row(py[-1], os.path.basename(f)))
    errs = _compare_tree(aggregate(rows, Config()), dump["stats"], "stats", 1e-6,
                         skip=("stats.created", "stats.config", "stats.baseline"))
    if len(js) != len(py):
        return [f"세대 수 다름: js {len(js)} / py {len(py)}"]
    for j, p in zip(js, py):
        tag = p["unit"]
        if j["unit"] != p["unit"] or j["type"] != p["type"]:
            errs.append(f"{tag}: 세대 {j['unit']}/{j['type']} vs {p['type']}")
            continue
        if [list(d) for d in p["doors_inferred"]] != j["doors"]:
            errs.append(f"{tag}: 추정 문 다름\n  js {j['doors']}\n  py {p['doors_inferred']}")
        pi = sorted((i["id"], i["level"]) for i in p["feasibility"]["issues"])
        if pi != sorted(tuple(x) for x in j["issues"]):
            errs.append(f"{tag}: 위반 다름 js {j['issues']} py {pi}")
        for k, v in p["measures"]["global"].items():
            if not same(v, j["global"].get(k)):
                errs.append(f"{tag}: @{k} py {v} js {j['global'].get(k)}")
        for rk, rv in p["measures"]["rooms"].items():
            for k, v in rv.items():
                if not same(v, j["rooms"].get(rk, {}).get(k), 1e-4):
                    errs.append(f"{tag}: {rk}.{k} py {v} js {j['rooms'].get(rk, {}).get(k)}")
        if set(p["features"]) != set(j["features"]):
            errs.append(f"{tag}: 특징 이름 다름 {sorted(set(p['features']) ^ set(j['features']))}")
        for k, v in p["features"].items():
            if not same(v, j["features"].get(k)):
                errs.append(f"{tag}: feature {k} py {v} js {j['features'].get(k)}")
        if not same(p["score"]["total"], j["total"], 1e-4):
            errs.append(f"{tag}: 총점 py {p['score']['total']} js {j['total']}")

    # 정답지 — 이 세대들의 특징으로 양쪽에서 만들고, 같은 세대를 다시 채점
    feat_rows = [_plain({"unit": p["unit"], "type": p["type"], **p["features"]}) for p in py]
    base = build_baseline(feat_rows)
    errs += _compare_tree(_plain(base), dump["baseline"], "baseline", 1e-6)
    for u, j in zip(units, js):
        r = evaluate(u, base, ep)
        errs += _compare_tree(_plain(_brief(r.get("typicality"))), j["typicality"], f"{u.uid}.typicality", 1e-6)
        if not same(r["score"]["total"], j["total_with_baseline"], 1e-4):
            errs.append(f"{u.uid}: 정답지 포함 총점 py {r['score']['total']} js {j['total_with_baseline']}")
    # 같은 특징 행을 node에 넘겨 — 정답지·근접도 계산만 따로(특징 값의 끝자리 차이 없이)
    errs += compare_rows(feat_rows, [params])
    return errs


def compare_rows(rows: list[dict], params: list[dict] = ({},), tol: float = 1e-9) -> list[str]:
    """특징 행 → 정답지·정답지 근접도를 파이썬과 웹이 같게 내는지."""
    rows = _plain(rows)
    params = [dict(p) for p in params]
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "rows.json")
        with open(p, "w", encoding="utf-8") as fh:
            json.dump({"rows": rows, "params": params}, fh, allow_nan=False)
        dump = _node("--rows", p)
    if dump is None:
        return []
    base = build_baseline(rows)
    errs = _compare_tree(_plain(base), dump["baseline"], "rows.baseline", tol)
    for pi, sp in enumerate(params):
        for i, (r, j) in enumerate(zip(rows, dump["typicality"][pi])):
            t = _brief(typicality(r, base, scoring_params(sp)))
            errs += _compare_tree(_plain(t), j, f"rows.typicality[{pi}][{i}]", tol)
    return errs


def _compare_tree(p, j, path, tol, skip=()) -> list[str]:
    """JSON 나무 비교 — skip 경로(만든 시각·설정 표기 같은 꾸밈 칸)는 빼고."""
    if path in skip:
        return []
    if isinstance(p, dict):
        if not isinstance(j, dict) or set(p) != set(j):
            return [f"{path}: 키 다름 {sorted(set(p) ^ set(j or {}))}"]
        return [e for k in p for e in _compare_tree(p[k], j[k], f"{path}.{k}", tol, skip)]
    if isinstance(p, list):
        if not isinstance(j, list) or len(p) != len(j):
            return [f"{path}: 길이 다름 py {len(p)} js {len(j) if isinstance(j, list) else j}"]
        return [e for i, (a, b) in enumerate(zip(p, j)) for e in _compare_tree(a, b, f"{path}[{i}]", tol, skip)]
    return [] if same(p, j, tol) else [f"{path}: py {p} js {j}"]


def test_parity_synthetic():
    with tempfile.TemporaryDirectory() as d:
        shifted = [(c, k, x + 30, y, w, h) for c, k, x, y, w, h in GOOD]
        broken = GOOD + [(14, "bed", 5, 9, 3, 3), (18, "bath", 2, 9.5, 2, 2)]
        files = []
        for name, rooms in (("APT_FP_SPA_a.json", GOOD + shifted), ("APT_FP_SPA_b.json", broken)):
            p = os.path.join(d, name)
            with open(p, "w", encoding="utf-8") as f:
                json.dump(coco(rooms), f)
            files.append(p)
        errs = compare(files)
    assert not errs, "\n".join(errs)


def test_parity_params():
    """기본값이 아닌 변수 — 인접 그래프, 발코니(외벽 쪽 간격)·작은 기타실(덕트)·채광 기준."""
    extra = [(17, "balcony", 2, 9.25, 6, 1.4), (22, "etc", 11, 3, 1, 1), (22, "etc", 11, 4, 1.2, 1.5),
             (19, "ac", -3, 6.3, 1.5, 1)]
    with tempfile.TemporaryDirectory() as d:
        files = []
        for name, rooms in (("APT_FP_SPA_p.json", GOOD + extra), ("APT_FP_SPA_q.json", GOOD + extra[:2])):
            p = os.path.join(d, name)
            with open(p, "w", encoding="utf-8") as f:
                json.dump(coco(rooms), f)
            files.append(p)
        errs = compare(files)
        for params in ({"graph": "adjacency", "duct_area_px": 30000, "daylight_min_px": 600, "z_cut": 2},
                       {"wall_tol_ext_px": 20, "min_contact_px": 120, "ref_bed_side_px": 200, "strata_min": 1,
                        "w_shape": 0, "balcony": "all"}):
            errs += [f"{params}: {e}" for e in compare(files, params)]
    assert not errs, "\n".join(errs[:40])


def synthetic_rows(n: int = 600, seed: int = 7) -> list[dict]:
    """정답지 계산을 두루 건드리는 가짜 특징 행 — 이산 τ(정확 누적분포), 값이 많은 깊이 차(분위수 누적분포),
    절반 넘게 0인 발코니 비(Qn = 0 → 누적분포), 빠진 값, 층(침실 수) 크기 여러 가지."""
    rnd = random.Random(seed)
    taus = [round(-1 + 0.2 * i, 10) for i in range(11)]
    rows = []
    beds = [1] * 40 + [2] * 150 + [3] * 300 + [4] * 90 + [5] * 3 + [6] * 7
    for i in range(n):
        nb = beds[i % len(beds)]
        k = rnd.randint(4, 12)
        r = {"unit": f"u{i}", "type": f"{nb}R{rnd.choice([1, 2])}B", "n_bed": nb, "n_bath": rnd.choice([1, 2]),
             "k_func": k, "ringiness": rnd.choice([0, 0, 0.1, 0.2])}
        for key in SCORED:
            r[key] = rnd.gauss(1.0 + 0.05 * nb, 0.3)
        r.pop("geno_dist")
        r["geno_tau"] = rnd.choice(taus) if rnd.random() > .1 else None
        r["pp_depth"] = round(rnd.gauss(1, .7), 3)
        r["r_balcony"] = 0 if rnd.random() < .6 else rnd.uniform(.02, .1)
        r["int_func"] = 1.2 + .3 * math.log(k) + rnd.gauss(0, .1) if rnd.random() > .05 else None
        r["master_ratio"] = None if nb == 1 else r["master_ratio"]
        r["rect_mbr"] = min(1.0, rnd.uniform(.8, 1.05))
        gz = [rnd.gauss(0, 1) for _ in range(5)] if rnd.random() > .15 else [None] * 5
        for g, v in zip(("living", "kitchen", "entry", "bed", "bath"), gz):
            r["gz_" + g] = v
        rows.append(r)
    return rows


def test_parity_baseline_rows():
    errs = compare_rows(synthetic_rows(),
                        params=[{}, {"strata_min": 5, "z_cut": 2, "w_area": 0}, {"strata_min": 1000, "w_ext": 25}])
    assert not errs, "\n".join(errs[:40])


if __name__ == "__main__":
    sys.stdout.reconfigure(errors="replace")   # cp949 콘솔에서도 '—' 등으로 멈추지 않게
    if len(sys.argv) > 1:
        fs = sorted(glob.glob(os.path.join(sys.argv[1], "**", "*SPA*.json"), recursive=True))
        errs = compare(fs)
        print("\n".join(errs[:40]) or f"일치 — 파일 {len(fs)}개")
        if len(errs) > 40:
            print(f"… 외 {len(errs) - 40}건")
        sys.exit(1 if errs else 0)
    test_parity_synthetic()
    print("ok test_parity_synthetic")
    test_parity_params()
    print("ok test_parity_params")
    test_parity_baseline_rows()
    print("ok test_parity_baseline_rows")
