// node tests/engine_dump.js <라벨.json>... — 웹 엔진(docs/aihub-engine.js)의 채점 결과를 JSON으로.
// tests/test_engine_parity.py 가 파이썬 결과와 비교한다.
const fs = require("fs");
const path = require("path");
const E = require(path.join(__dirname, "..", "docs", "aihub-engine.js"));

const crit = E.parseDSL(E.PRESETS["시공가능성 + 공간구문"]).criteria;
const out = [], rows = [];
for (const f of process.argv.slice(2)) {
  const data = JSON.parse(fs.readFileSync(f, "utf8"));
  if (E.labelType(data, path.basename(f)) !== "SPA") continue;
  for (const u of E.loadUnits(data, path.basename(f))) {
    const r = E.evaluate(u, crit);
    rows.push(E.statRow(r, path.basename(f)));
    out.push({ unit: r.unit, type: r.type, doors: r.doors, issues: r.issues.map(i => [i.id, i.level]),
      global: r.measures.global, rooms: r.measures.rooms, features: r.features, total: r.score.total });
  }
}
const stats = E.aggregate(rows, { params: {}, criteria: crit });
process.stdout.write(JSON.stringify({ units: out, stats }));
