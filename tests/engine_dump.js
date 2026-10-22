// node tests/engine_dump.js [--params '{"graph":"adjacency",...}'] <라벨.json>... — 웹 엔진(docs/aihub-engine.js)의 채점 결과를 JSON으로.
// node tests/engine_dump.js --rows <rows.json> — 특징 행으로 정답지·정답지 근접도만.
//   rows.json = {rows: [{unit, type, ...features}], params: [{z_cut, strata_min, ...}, ...]}
// tests/test_engine_parity.py 가 파이썬 결과와 비교한다.
const fs = require("fs");
const path = require("path");
const E = require(path.join(__dirname, "..", "docs", "aihub-engine.js"));

// 정답지 근접도 요약 — 비교에 쓸 숫자만
const brief = (t) => t && { reference: t.reference, score: t.score,
  domains: Object.fromEntries(Object.entries(t.domains).map(([d, x]) => [d, x.score])),
  features: Object.fromEntries(Object.entries(t.features).map(([k, x]) => [k, x.score])) };

let args = process.argv.slice(2), params = {};
if (args[0] === "--params") { params = JSON.parse(args[1]); args = args.slice(2); }
if (args[0] === "--rows") {
  const inp = JSON.parse(fs.readFileSync(args[1], "utf8"));
  const baseline = E.buildBaseline(inp.rows);
  const typ = (inp.params || [{}]).map(p => inp.rows.map(r => brief(E.typicality(r, baseline, E.scoringParams(p)))));
  process.stdout.write(JSON.stringify({ baseline, typicality: typ }));
  process.exit(0);
}

const crit = E.parseDSL(E.PRESETS["시공가능성 + 공간구문"]).criteria;
const out = [], rows = [], kept = [];
for (const f of args) {
  const data = JSON.parse(fs.readFileSync(f, "utf8"));
  if (E.labelType(data, path.basename(f)) !== "SPA") continue;
  for (const u of E.loadUnits(data, path.basename(f), params)) {
    const A = E.analyzeUnit(u, params), r = E.scoreUnit(u, A, crit, null, E.scoringParams(params));
    // 웹이 저장해 두고 다시 채점하는 경로(요약 → scoreCached)도 같은 점수를 내야 한다
    const c = E.scoreCached(structuredClone(E.summarizeUnit(u, A)), crit);
    if (Math.abs(c.score.total - r.score.total) > 1e-9) throw new Error(`cached score differs: ${u.uid}`);
    rows.push(E.statRow(r, path.basename(f)));
    kept.push([u, A]);
    out.push({ unit: r.unit, type: r.type, doors: r.doors, issues: r.issues.map(i => [i.id, i.level]),
      global: r.measures.global, rooms: r.measures.rooms, features: r.features, total: r.score.total });
  }
}
const stats = E.aggregate(rows, { params, criteria: crit });

// 정답지: 이 세대들의 특징으로 만들고, 같은 세대를 다시 채점(@typicality 포함)
const baseline = E.buildBaseline(out.map(o => ({ unit: o.unit, type: o.type, ...o.features })));
const sp = E.scoringParams(params);
kept.forEach(([u, A], i) => {
  const r = E.scoreUnit(u, A, crit, baseline, sp);
  const c = E.scoreCached(structuredClone(E.summarizeUnit(u, A)), crit, baseline, sp);
  if (Math.abs(c.score.total - r.score.total) > 1e-9) throw new Error(`cached score (baseline) differs: ${u.uid}`);
  out[i].typicality = brief(r.typicality);
  out[i].total_with_baseline = r.score.total;
});
process.stdout.write(JSON.stringify({ units: out, stats, baseline }));
