"""웹 엔진(docs/aihub-engine.js)과 파이썬 평가기가 같은 값을 내는지 — node가 있을 때만.

    python tests/test_engine_parity.py [라벨 폴더]   (폴더를 안 주면 합성 도면으로)
"""
import glob
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from floorplan_bench.aihub import load_units  # noqa: E402
from floorplan_bench.criteria import Config  # noqa: E402
from floorplan_bench.evaluate import evaluate  # noqa: E402
from floorplan_bench.stats import aggregate, stat_row  # noqa: E402
from tests.test_aihub_eval import GOOD, coco  # noqa: E402


def same(a, b, tol=1e-6) -> bool:
    if isinstance(a, float) and math.isnan(a):   # 파이썬 NaN ↔ JSON null
        return b is None or (isinstance(b, float) and math.isnan(b))
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) <= tol * max(1.0, abs(a), abs(b))
    return a == b


def compare(files: list[str]) -> list[str]:
    node = shutil.which("node")
    if not node:
        print("node 없음 — 건너뜀")
        return []
    dump = json.loads(subprocess.run([node, os.path.join(ROOT, "tests", "engine_dump.js"), *files],
                                     capture_output=True, check=True, encoding="utf-8").stdout)
    js = dump["units"]
    py, rows = [], []
    for f in files:
        for u in load_units(f):
            py.append(evaluate(u))
            rows.append(stat_row(py[-1], os.path.basename(f)))
    errs = _compare_stats(aggregate(rows, Config()), dump["stats"])
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
        for k, v in p["features"].items():
            if not same(v, j["features"].get(k)):
                errs.append(f"{tag}: feature {k} py {v} js {j['features'].get(k)}")
        if not same(p["score"]["total"], j["total"], 1e-4):
            errs.append(f"{tag}: 총점 py {p['score']['total']} js {j['total']}")
    return errs


def _compare_stats(p, j, path="stats") -> list[str]:
    """통계 JSON 비교 — 만든 시각·설정 표기 같은 꾸밈 칸은 빼고."""
    if path in ("stats.created", "stats.config", "stats.baseline"):
        return []
    if isinstance(p, dict):
        if not isinstance(j, dict) or set(p) != set(j):
            return [f"{path}: 키 다름 {sorted(set(p) ^ set(j or {}))}"]
        return [e for k in p for e in _compare_stats(p[k], j[k], f"{path}.{k}")]
    if isinstance(p, list):
        if not isinstance(j, list) or len(p) != len(j):
            return [f"{path}: 길이 다름"]
        return [e for i, (a, b) in enumerate(zip(p, j)) for e in _compare_stats(a, b, f"{path}[{i}]")]
    return [] if same(p, j, 1e-6) else [f"{path}: py {p} js {j}"]


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


if __name__ == "__main__":
    if len(sys.argv) > 1:
        fs = sorted(glob.glob(os.path.join(sys.argv[1], "**", "*SPA*.json"), recursive=True))
        errs = compare(fs)
        print("\n".join(errs[:40]) or f"일치 — 파일 {len(fs)}개")
        sys.exit(1 if errs else 0)
    test_parity_synthetic()
    print("ok test_parity_synthetic")
