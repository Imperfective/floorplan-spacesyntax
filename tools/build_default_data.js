// AI 허브 라벨에서 '결과물'만 뽑아 웹 프로그램의 기본 데이터로 만든다 — 원본 JSON은 담지 않는다.
//
//   node tools/build_default_data.js <APT_FP_SPA_*.json 폴더> [출력 폴더=docs/data]
//
// 만드는 파일
//   aihub-baseline.json        정답지 — 유형별 특징 분포(중앙값·척도). 웹 '정답지'의 기본값
//   aihub-default-stats.json   전체 데이터를 기본 평가 구조로 채점한 통계(보관 기록 형식, 점수표는 세대별 점수만)
//
// AI 허브 이용정책상 원본 데이터의 재배포는 금지, 2차 저작물(분석 결과)은 출처 표기 후 배포 가능하다.
// 그래서 폴리곤·좌표 같은 원본 내용은 넣지 않고, 엔진이 계산한 분포·점수만 넣는다.
const fs = require("fs");
const path = require("path");
const E = require(path.join(__dirname, "..", "docs", "aihub-engine.js"));

const src = process.argv[2];
const outDir = process.argv[3] || path.join(__dirname, "..", "docs", "data");
if (!src) { console.error("사용: node tools/build_default_data.js <라벨 폴더> [출력 폴더]"); process.exit(1); }

const SOURCE_NOTE = "출처: AI 허브 「건축 도면 데이터」(aihub.or.kr, 한국지능정보사회진흥원) — Training 라벨 TL_SPA 중 아파트 평면도";
const files = fs.readdirSync(src).filter(f => /^APT_FP_SPA_\d+\.json$/i.test(f)).sort();
const criteria = E.parseDSL(E.PRESETS["시공가능성 + 공간구문"]).criteria;
const params = E.defaultParams();

// 1차: 세대 나누기 · 지표 요약 (조건과 무관)
const sums = [];
let t = Date.now(), failed = 0;
files.forEach((f, i) => {
  try {
    const data = JSON.parse(fs.readFileSync(path.join(src, f), "utf8"));
    for (const u of E.loadUnits(data, f, params)) sums.push({ file: f, s: E.summarizeUnit(u, E.analyzeUnit(u, params)) });
  } catch (e) { failed++; console.error(f, e.message); }
  if (Date.now() - t > 5000) { console.error(`${i + 1}/${files.length} 파일 · 세대 ${sums.length}`); t = Date.now(); }
});

// 정답지 — 전체 세대의 특징 분포
const baseline = E.buildBaseline(sums.map(({ s }) => ({ unit: s.uid, type: s.type, ...s.features })));

// 2차: 정답지까지 넣어 기본 평가 구조로 채점 → 통계
const rows = sums.map(({ file, s }) => E.statRow(E.scoreCached(s, criteria, baseline), file, { source: "aihub" }));
const stats = E.aggregate(rows, { params, criteria },
  { name: `AI 허브 전체 — 아파트 평면도 ${files.length.toLocaleString("ko-KR")}장`, memo: SOURCE_NOTE,
    baseline: { source: "default", n_units: baseline.n_units, type_counts: baseline.type_counts } });
// 점수표는 세대별 점수만(지표·조건점수 열은 빼서 가볍게)
stats.units = stats.units.map(u => ({ unit: u.unit, type: u.type, total: +u.total.toFixed(2), base: +u.base.toFixed(2),
  penalty: +u.penalty.toFixed(2), gated: u.gated, grade: u.grade, pass: u.pass, source: "aihub" }));
stats.id = "builtin-aihub";
stats.builtin = true;

const meta = { source: SOURCE_NOTE, files: files.length, units: sums.length, failed, built: new Date().toISOString() };
fs.mkdirSync(outDir, { recursive: true });
fs.writeFileSync(path.join(outDir, "aihub-baseline.json"), JSON.stringify({ ...baseline, meta }));
fs.writeFileSync(path.join(outDir, "aihub-default-stats.json"), JSON.stringify(stats));
console.log(JSON.stringify({ ...meta, mean: stats.summary.score.mean, pass_rate: stats.summary.feasibility_pass_rate,
  top_types: Object.entries(baseline.type_counts).slice(0, 6) }));
