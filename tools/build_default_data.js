// AI 허브 라벨에서 '결과물'만 뽑아 웹 프로그램의 기본 데이터로 만든다 — 원본 JSON은 담지 않는다.
//
//   node tools/build_default_data.js <APT_FP_SPA_*.json 폴더> [출력 폴더=docs/data]
//
// 만드는 파일
//   aihub-baseline.json        정답지 — 유형별 특징 분포(중앙값·척도). 웹 '정답지'의 기본값
//   aihub-default-stats.json   전체 데이터를 기본 평가 구조로 채점한 통계(보관 기록 형식, 점수표는 열 방식 압축)
//   aihub-genspec.json         생성 사양 — 유형·침실 수별 실 구성·면적비·깊이·외기·인접 확률과 제안 제약(생성기 입력)
//
// AI 허브 이용정책상 원본 데이터의 재배포는 금지, 2차 저작물(분석 결과)은 출처 표기 후 배포 가능하다.
// 그래서 폴리곤·좌표 같은 원본 내용은 넣지 않고, 엔진이 계산한 분포·점수만 넣는다.
const fs = require("fs");
const path = require("path");
const E = require(path.join(__dirname, "..", "docs", "aihub-engine.js"));
const S = require(path.join(__dirname, "..", "docs", "aihub-stats.js"));

const src = process.argv[2];
const outDir = process.argv[3] || path.join(__dirname, "..", "docs", "data");
if (!src) { console.error("사용: node tools/build_default_data.js <라벨 폴더> [출력 폴더]"); process.exit(1); }

const SOURCE_NOTE = "출처: AI 허브 「건축 도면 데이터」(aihub.or.kr, 한국지능정보사회진흥원) — Training 라벨 TL_SPA 중 아파트 평면도";
const files = fs.readdirSync(src).filter(f => /^APT_FP_SPA_\d+\.json$/i.test(f)).sort();
const criteria = E.parseDSL(E.PRESETS["시공가능성 + 공간구문"]).criteria;
const params = E.defaultParams();

// 1차: 세대 나누기 · 지표 요약 (조건과 무관)
const sums = [];
let t = Date.now(), failed = 0, empty = 0;
files.forEach((f, i) => {
  try {
    const data = JSON.parse(fs.readFileSync(path.join(src, f), "utf8"));
    const units = E.loadUnits(data, f, params);
    if (!units.length) empty++;   // 현관 라벨이 없어 세대를 나눌 수 없는 도면
    for (const u of units) sums.push({ file: f, s: E.summarizeUnit(u, E.analyzeUnit(u, params)) });
  } catch (e) { failed++; console.error(f, e.message); }
  if (Date.now() - t > 5000) { console.error(`${i + 1}/${files.length} 파일 · 세대 ${sums.length}`); t = Date.now(); }
});

// 정답지 — 전체 세대의 특징 분포
const baseline = E.buildBaseline(sums.map(({ s }) => ({ unit: s.uid, type: s.type, ...s.features })));

// 2차: 정답지까지 넣어 기본 평가 구조로 채점 → 통계
const scored = sums.map(({ file, s }) => { const r = E.scoreCached(s, criteria, baseline); return { r, row: E.statRow(r, file, { source: "aihub" }) }; });
const rows = scored.map((x) => x.row);
const stats = E.aggregate(rows, { params, criteria },
  { name: `AI 허브 전체 — 아파트 평면도 ${files.length.toLocaleString("ko-KR")}장`, memo: SOURCE_NOTE,
    baseline: { source: "default", n_units: baseline.n_units, type_counts: baseline.type_counts } });
// 점수표는 열 방식으로 압축(키 이름 반복을 없앰) — 웹이 불러올 때 풀어 쓴다(loadDefaults).
// 연구용 통계(분포·상관·기술통계)에 쓰도록 전역 지표 일부 · 정답지 영역 점수 · 근거 문서 지표 18개를 넣는다(유효숫자 4자리).
const G = ["typicality", "n_bed", "n_bath", "n_spaces", "mean_depth_system", "max_depth_from_carrier", "mean_integration", "intelligibility", "ringiness"];
const D = Object.keys(E.DOMAINS), F = E.SCORED;
const r4 = (v) => (Number.isFinite(v) ? +v.toPrecision(4) : null), r2 = (v) => (Number.isFinite(v) ? +v.toFixed(2) : null);
stats.units_packed = {
  cols: ["unit", "type", "total", "base", "penalty", "gated", "grade", "pass", "source", ...G.map((k) => "g." + k), ...D.map((d) => "d." + d), ...F.map((k) => "f." + k)],
  rows: scored.map(({ r, row }) => {
    const typ = r.typicality, fe = r.features || {};
    return [row.unit, row.type, r2(row.total), r2(row.base), r2(row.penalty), row.gated, row.grade, row.pass ? 1 : 0, "aihub",
      ...G.map((k) => r4(row.global[k])), ...D.map((d) => r4(typ && typ.domains[d] ? typ.domains[d].score : null)),
      ...F.map((k) => r4(Number.isFinite(fe[k]) ? fe[k] : typ && typ.features[k] ? typ.features[k].value : null))];
  }),
};
stats.units = [];
stats.summary.n_files_empty = empty;
stats.id = "builtin-aihub";
stats.builtin = true;

const meta = { source: SOURCE_NOTE, files: files.length, units: sums.length, failed, empty, built: new Date().toISOString() };
fs.mkdirSync(outDir, { recursive: true });
fs.writeFileSync(path.join(outDir, "aihub-baseline.json"), JSON.stringify({ ...baseline, meta }));
fs.writeFileSync(path.join(outDir, "aihub-default-stats.json"), JSON.stringify(stats));
const spec = Object.assign(S.genSpec(sums.map(({ s }) => s)), { meta });
fs.writeFileSync(path.join(outDir, "aihub-genspec.json"), JSON.stringify(spec));
console.log(JSON.stringify({ ...meta, mean: stats.summary.score.mean, pass_rate: stats.summary.feasibility_pass_rate,
  top_types: Object.entries(baseline.type_counts).slice(0, 6) }));
