# 건축 평면 최적화 · 공간구문 분석 도구모음

AI가 생성한 건물 도면을 **좌표로 데이터화**하고, **"좋은 도면"을 수치 함수로 정의**한 뒤,
서로 다른 방법으로 평가·최적화해 비교하는 실험 도구모음입니다.

**사이트 → https://sapcesyntax.com** — 도면 평가 프로그램(D)

세 갈래로 이루어져 있습니다.

| # | 갈래 | 무엇을 하는가 |
|---|---|---|
| **B** | [Space Syntax CLI](#b-space-syntax-cli) | 격자 도면의 Space Syntax 분석을 명령줄에서. JSON·CSV 내보내기와 규칙 비교 |
| **C** | [OR-Tools vs D-Wave 벤치마크](#c-or-tools-vs-d-wave-벤치마크) | 동일한 목적 함수를 고전 조합 최적화와 양자 어닐링 계열에 각각 주고 비교 |
| **D** | [도면 평가 프로그램 — AI 허브 라벨(JSON) 평가 모델](#d-ai-허브-라벨json-평가-모델) — **사이트** | **tar · zip · JSON · 엑셀 · CSV 파일, 도면 이미지, 직접 입력으로 도면을 가져오면** 도면을 그리고, 사용자가 정한 평가 구조(조건·반영방식·변수)로 채점해 통계로 모아 보관·JSON 내보내기 |

---

## 빠른 시작

```bash
# 파이썬 환경 (3.10+ 권장)
uv venv --python 3.12 .venv          # 또는 python3 -m venv .venv
uv pip install --python .venv/bin/python -r requirements.txt

# B. Space Syntax 분석
.venv/bin/python syntax_cli.py --plan-file examples/example_plan.txt --rules standard

# C. 4단계 파이프라인
.venv/bin/python main.py --spec apartment_8x8 --env balanced --time-limit 60

# D. AI 허브 라벨 평가 — 웹은 설치 없이 docs/index.html(사이트 첫 화면), CLI는 표준 라이브러리만 사용
open docs/index.html
python aihub_eval.py baseline <02.라벨링데이터> -o out/baseline.json
python aihub_eval.py score <02.라벨링데이터> --baseline out/baseline.json --stats out/stats.json
```

---

## B. Space Syntax CLI

웹 앱과 **같은 알고리즘**을 명령줄에서. JavaScript 포팅본과 Python 원본이 같은 값을 내는 것을
교차 검증했습니다(그래프 지표 전부 일치, VGA는 시선 샘플 간격 차이로 0.3% 이내).

```bash
# 규칙 템플릿 만들기 → 값을 고쳐서 쓴다
.venv/bin/python syntax_cli.py --dump-rules examples/rules.json

# 도면 분석
.venv/bin/python syntax_cli.py --plan-file examples/example_plan.txt --rules examples/rules.json
.venv/bin/python syntax_cli.py --plans out/plans.json --rules standard

# 규칙 프리셋별 비교
.venv/bin/python syntax_cli.py --plan-file examples/example_plan.txt --compare-rules
```

옵션: `--spec {small_6x6, apartment_8x8}` · `--rules {standard, strict_door, open_plan, multi_entry, no_carrier}` 또는 JSON 경로
· `--generate N` · `--no-vga` · `--out DIR` · `--html PATH`

### 산출물

```
out/syntax/syntax.json        그래프 구조 · 문 좌표 · 전체 지표
out/syntax/syntax_rooms.csv   실별 실측/위상/시각 좌표 + 지표
out/syntax/syntax_edges.csv   문 좌표와 공유 벽 길이
out/syntax/syntax_cells.csv   셀별 VGA · 아이소비스트
docs/syntax-report.html       시각화 리포트 (평면도 · j-graph · 히트맵)
```

---

## C. OR-Tools vs D-Wave 벤치마크

건물 평면 배치를 조합 최적화 문제로 두고, **완전히 동일한 목적 함수**를
OR-Tools CP-SAT(고전 분기한정)와 D-Wave Ocean(양자 어닐링 계열)에 각각 주어 비교합니다.

```bash
# 4단계 파이프라인 (생성 → 데이터화 → 환경변수 → 비교)
.venv/bin/python main.py --spec apartment_8x8 --env balanced --time-limit 60

# 전체 연구 (주 비교 + 환경변수 10종 스윕 + 진단 실험 5종, 약 30분)
.venv/bin/python run_study.py
.venv/bin/python build_paper.py        # → docs/benchmark-report.html
```

### 12개 환경 변수

```
E(도면) = Σᵢ signᵢ · wᵢ · termᵢ(도면)        sign = −1(보상) 또는 +1(벌점)
```

| 성격 | 항 | 정식화 |
|---|---|---|
| 하드 | 셀 배타성 위반 · 면적 오차 | 페널티(QUBO) / 네이티브 제약(CP-SAT) |
| 2차 | 인접 선호 · 방 응집도 · 동선 코어 접면 · 소음 인접 | 셀 쌍 위에서 계산 |
| 1차 | 채광 · 남향 · 프라이버시 · 공용 접근성 · 설비 코어 집중 · 외피 노출 | 셀 하나씩 계산 |

프리셋 10종: `balanced` `family` `daylight` `solar` `privacy` `acoustic` `passive` `plumbing` `buildable` `barrier_free`

### 공정성 담보

목적 함수는 **`floorplan_bench/terms.py` 한 곳에서만** 생성됩니다.
`quality_coeffs()`가 CP-SAT와 QUBO 양쪽에 같은 계수를 공급하고,
`raw_values()`가 도면을 직접 순회하는 **제3의 독립 평가기**로서 이를 교차 검증합니다.
세 경로의 값이 프리셋 10종 × 무작위 도면 전부에서 10⁻⁶ 이내로 일치함을 확인했습니다.

### 주요 결과

| 방법 | 조건 | 에너지 | 조각난 실 |
|---|---|---:|---:|
| AI 생성 최고안 | 기준선 | −10.134 | 0 |
| OR-Tools CP-SAT | D-Wave와 동일 조건 | **−13.016** | 3 |
| OR-Tools CP-SAT | + 연결성 제약 | −12.572 | **0** |
| D-Wave SA | QUBO 페널티 인코딩 | −7.890 | 7 |
| 교환 어닐링 | 같은 어닐링 · 인코딩만 교체 | **−12.915** | 2 |

**갈린 것은 하드웨어도 알고리즘도 아니라 문제를 옮겨 적는 방식이었습니다.**
어닐링을 그대로 두고 인코딩만 제약 보존 방식으로 바꾸자 격차의 대부분이 사라졌습니다.

원인 — 페널티 인코딩에서는 실현 가능한 해들이 ΔE ≈ **+32**의 장벽으로 격리됩니다.
단일 비트 뒤집기 표본 **1,600회 중 에너지를 개선한 것이 0회(0.0%)**였고,
어닐링 예산을 100배 늘려도(E2), 최적해에서 출발시켜도(E3),
벌점을 80배 범위로 조절해도(E5) 벗어나지 못했습니다.

> **유의** — 이 실행에 양자 하드웨어는 쓰이지 않았습니다. Leap 토큰이 없으면
> `SimulatedAnnealingSampler`(CPU에서 도는 고전 어닐링)로 동작합니다.
> QUBO 정식화와 Ocean 도구 체인은 실제 QPU와 동일하며 `--dwave qpu` / `hybrid`로 전환됩니다.
> 따라서 위 격차는 *양자 대 고전*이 아니라 **어닐링 대 분기한정 탐색**으로 읽어야 합니다.
>
> `docs/benchmark-report.html`은 환경 변수 5개였던 이전 판의 기록입니다.
> 12개로 확장한 뒤의 전체 재실행은 `run_study.py`로 다시 돌려야 합니다.

---

## D. AI 허브 라벨(JSON) 평가 모델

→ **https://sapcesyntax.com** — **도면 평가 프로그램** (예전 주소 `/aihub.html`·`/aihub`·`/image`는 첫 화면으로 넘어갑니다)

PNG 인식 없이 AI 허브 '건축 도면 데이터'의 라벨 JSON(COCO 폴리곤)을 바로 읽어 **도면을 그리고** 세대별로 채점합니다.
실제 지어진 아파트(AI 허브)를 **정답지**로 삼고, 생성 도면이 ① 시공 가능한지 ② 정답지 분포에 얼마나 가까운지 봅니다.
**무엇을 어떻게 점수에 넣을지는 사용자가 정합니다**(조건 추가·삭제, 반영방식, 판정 변수).

### 웹 — `docs/index.html` (도면 평가 프로그램)

도면을 여러 방식으로 가져옵니다 — **AI 허브 라벨**(받은 `download.tar` 그대로 또는 zip, 전부 또는 일부) · **JSON 파일·폴더 업로드** ·
**엑셀(.xlsx)·CSV 표 → JSON 변환** · **도면 이미지(PNG·JPG) → JSON 변환** · **JSON 직접 입력**(생성 모델이 만든 도면 등) · 예시.
가져온 도면은 **이 브라우저(IndexedDB)에 쌓여** 다시 열어도 통계·점수표가 그대로 남고, 출처별로 거르거나 지울 수 있습니다.
도면 파일은 브라우저 밖으로 나가지 않고, **누가 언제 무엇을 했는지(작업 종류·파일 이름 등)만 서버 활동 기록에 남습니다**(아래 ‘로그인 · 활동 기록’).

**기본 데이터(결과물만)** — 사이트에는 AI 허브 TL_SPA 아파트 평면도 **7,275장(21,383세대)** 에서 계산한 결과가 기본으로 들어 있습니다:
`docs/data/aihub-baseline.json`(침실 수로 층화한 지표 분포 = 기본 정답지)과 `docs/data/aihub-default-stats.json`(기본 평가 구조로 채점한 전체 통계 ·
세대별 점수, 보관 기록 맨 위 ‘AI 허브 전체’). 폴리곤·좌표 같은 원본 내용은 넣지 않습니다 — AI 허브 이용정책상 원본 재배포는 금지이고
2차 저작물(분석 결과)은 출처 표기 후 배포할 수 있기 때문입니다. 전체 결과: 평균 75.7점 · 시공 가능 88.4% · 정답지 근접도 중앙값 75.5 · 최다 유형 **3R2B(9,924세대)**.
다시 만들려면 `node tools/build_default_data.js <APT_FP_SPA JSON 폴더>`(원본은 각자 받은 것 사용, 약 4분).
정답지는 기본으로 이 전체 분포를 쓰고, ‘보유 세대로’ 또는 `baseline.json` 파일로 바꿀 수 있습니다.

저장 구조 — 원본 JSON은 그대로 두고, 세대마다 조건과 무관한 요약(지표·특징·점검 수)을 함께 저장합니다.
조건을 바꾸면 요약만으로 즉시 다시 채점하고(원본을 다시 읽지 않음), 판정 변수를 바꿀 때만 원본에서 다시 계산합니다.
도면을 열 때만 그 파일의 원본을 꺼내 그립니다. 두 경로의 점수가 같은지는 `tests/engine_dump.js`가 확인합니다.

화면은 사내 **Works Design System**(MS DX팀) 규칙을 따릅니다 — Pretendard Variable(숫자 tnum)·Red Hat Display 워드마크,
deep teal 주색, 캔버스 배경 위 흰 카드 1겹, 화면당 주 액션 1개, 색은 상태(통과·주의·오류)에만.
폰트 파일은 `docs/fonts/`에서 직접 서빙합니다(서버 CSP가 외부 폰트 CDN을 막기 때문).

**GNB(상단)** — 로고·이름(도면 평가 프로그램) · 보유 데이터 요약(도면 수·세대 수·평균 점수) · 로그인한 계정·로그아웃 · 사용 설명서(README).
**SNB(좌측)** — 기능별로 묶은 메뉴. 페이지마다 주소(`#/stats/summary` 등)가 있어 새로고침·뒤로가기·공유가 됩니다.

| 메뉴 | 헤더 탭 | 하는 일 |
|---|---|---|
| 분석 › **통계** | 요약 · 분포·집단 비교 · 등급 · 상관 · 기술통계 · 조건·점검 · 점수표 | **요약**: 점수 요약(세대 없는 파일 수 따로 표시), 총점 분포·등급, 유형별 점수·시공 가능 비율. **분포·집단 비교**: 변수(총점·기본점·감점·정답지 근접도·영역 점수 4개·근거 문서 지표 18개·전역 지표) 하나를 골라 히스토그램(구간 자동 Freedman–Diaconis/10/20/40, 평균·중앙값 선)·누적분포(ECDF, 십자선)·기술통계, 집단(침실 수·유형·등급·등급 묶음·시공 가능·출처)별 상자그림 + **Kruskal–Wallis H(ε²)·일원 분산분석 F(η²)·Dunn 사후검정(Holm)**. **등급**: A+~F 세대 수·비율·누적 비율·**Wilson 95% CI**, 집단 × 등급 교차표와 100% 누적 막대 + **χ² 독립성 검정·Cramér's V**. **상관**: Spearman ρ / Pearson r 행렬(히트맵, 짝별 완전 사례)과 p·n 표. **기술통계**: 논문 표 1 형식(n·평균·SD·95% CI·중앙값·Q1·Q3·최저·최고·왜도·첨도), 집단별로 나눔, 통계 방법 서술 문단 복사. 모든 표는 **CSV · 표 복사(엑셀·한글·워드) · Markdown · LaTeX**로 내보냄. 필수 조건 탈락(0점) 세대 제외 선택. **조건·점검**: 조건별 평균 조건점수·만점 비율, 시공 점검 위반 수. **점수표**: 세대별 출처·유형·총점·등급·감점·시공 가능(행을 누르면 그 도면으로). 툴바: 출처·유형 필터 · 점수표 CSV · 통계 JSON · **현재 통계 보관** |
| 데이터 › **데이터 가져오기** | AI 허브 · 파일 업로드 · 이미지 변환 · 직접 입력 · 보유 데이터 | **AI 허브**: 받은 `download.tar`(안에 `TL_SPA.zip.part0` 등 조각)나 zip을 그대로 놓으면 브라우저 안에서 열어 라벨 종류(SPA·STR·OBJ·OCR)·주택 유형·도면 종류·개수(전부/앞에서 N/무작위 N)·이름으로 골라 가져옴. **파일 업로드**: tar · zip · JSON · 엑셀 · CSV(여러 개·폴더째) — 확장자에 따라 알아서 나눔. **엑셀·CSV**는 한 행 = 실 하나(열: 도면 · 용도 · x · y · 너비 · 깊이 또는 좌표 `x1 y1, x2 y2, …` · 단위 m/px · 이름; 한글·영문 머리글 모두)인 표를 도면별 AI 허브 SPA 형식 JSON으로 바꿔 미리 보고(실·세대 수, 건너뛴 행과 이유) **파일 업로드 데이터에 추가**하거나 JSON 내려받기(여러 도면이면 zip 하나). m 단위는 1m = 100px로 바꾸고 실마다 벽 자리를 남김. .xlsx는 첫 시트, CSV는 UTF-8·CP949(엑셀 저장) 모두 읽음. 양식 CSV 내려받기. **이미지 변환**: 평면도 PNG·JPG의 벽·방을 인식(벽 색/어두운 선, 문 틈 막기 자동 보정)해 방 윤곽을 다각형으로 따고 용도를 자동 추정 → 확인·수정 후 AI 허브 SPA 형식 JSON으로 **파일 업로드 데이터에 추가**(또는 JSON 내려받기), 여러 장은 차례로 또는 일괄 자동 변환. 벽이 굵고 단순한 평면도용이며 치수선·글자가 많은 CAD 원본은 잘 나뉘지 않음. **직접 입력**: JSON 붙여넣기·형식 확인·예시. **보유 데이터**: 출처별 파일·세대 수, 다시 계산, 출처별·전체 삭제, 저장 공간 사용량 |
| 분석 › **도면** | — | 왼쪽 파일 목록(검색, 파일 아래 세대, 삭제) · 가운데 도면(실 색·실 이름·추정 문·연결 그래프·문제 표시·선택 세대 강조, 확대·이동) · 오른쪽 세대 결과(총점·등급, 시공 점검, 조건별, 실별 지표, 정답지 근접도). STR은 벽·문·창과 겹친 문·창 |
| 평가 설정 › **평가 구조** | 조건 · 문법 편집 | 조건을 **추가·삭제·켜고 끄기**. 대상(전역/실 용도)·지표·판정(범위/목표값/합격선)·**반영 방식**(가중 평균/감점/필수)·가중치·감점 크기, 근거 메모. 행마다 전체 세대 평균 조건점수·만점 비율. 세트 적용 · 설정 가져오기/내보내기 |
| 평가 설정 › **판정 변수** | — | 축척 배율 기준·실 사이 간격(내벽/외벽)·최소 접촉 길이·덕트 면적·그래프 규약(문 추정/벽 인접)·발코니 연결·겹침/채광/문·창 임계값, **정답지 채점**(z 절단값·층화 최소 세대·영역 가중치). 변수마다 **근거 문헌·근거 등급(A~D)** 표시. 읽기·판정 변수는 모든 도면을 다시 읽고, 정답지 채점 변수는 바로 다시 채점. 바뀐 변수는 ‘변경됨’ |
| 평가 설정 › **정답지** | — | 지표 18개의 정의·방향·채점 방식·가중치·중앙값·Qn·근거 등급·근거 문헌(DOI), 침실 수 층화, 영역 가중치, 참고 문헌. 기본 = AI 허브 전체(7,275장), 보유 세대로 만들기, CLI가 만든 `baseline.json` 불러오기 |
| 관리 › **허용 계정 · 활동 기록** (관리자만) | 허용 계정 · 활동 기록 | 로그인할 수 있는 구글 계정 이메일 허용·해제(해제하면 바로 로그아웃), 사용자별 마지막 로그인·기록 수. 활동 기록: 사용자·작업·내용 검색, 더 보기, CSV 내려받기 |
| 기록 › **보관 기록** | (상세) 요약 · 조건·점검 · 지표 · 점수표 | 보관한 통계 목록(검색). 기록을 열면 그때의 통계를 같은 화면으로 다시 보고, **그 조건·변수 적용**, **JSON 내려받기**, 삭제(확인 창). 통계 JSON 불러오기 · 전체 내려받기 |

통계 JSON(`kind: "aihub-stats"`)에는 요약·유형별·조건별·위반·지표 통계와 함께 세대별 점수·전역 지표·조건점수(`units`),
그 통계를 낸 조건·변수(`config`), 정답지 정보가 들어 있어 연구 기록으로 그대로 남길 수 있습니다.
보유 데이터와 보관 기록은 이 브라우저(IndexedDB)에만 저장되므로, 다른 PC·팀원과 나눌 때는 통계 JSON·점수표 CSV로 내려받아 공유합니다.

**AI 허브 데이터 받기** — '건축 도면 데이터'(datasetkey 71465)는 원천 이미지(PNG, 약 26GB)와 라벨(JSON) zip이 나뉘어 있어
라벨 zip만 받으면 됩니다(전부 약 173MB, 채점에 필요한 SPA는 TL_SPA 37.8MB · VL_SPA 4.9MB).
AI 허브 로그인 → 데이터셋 화면에서 다운로드 승인(내국인) → 파일 목록에서 받거나(웹으로 받으면 `download.tar` 안에 `…/TL_SPA.zip.part0` 조각으로 들어 있음 — 풀지 말고 그대로 프로그램에 놓으면 됩니다), `aihubshell`로 파일키를 지정해 받습니다
(`-filekey`를 빼면 26GB 전체를 받습니다). AI 허브 API는 브라우저에서 직접 부를 수 없고(다른 사이트 호출 차단) API 키가 노출되므로,
자동 가져오기는 서버가 키를 보관하고 팀원 전용 주소로 넘겨 주는 방식이어야 합니다(준비 중).
**AI 허브 원본은 공개 저장소·사이트에 올리지 않습니다**(재배포 제한).

평가 구조의 **설정 내보내기** JSON은 파이썬 CLI의 `--config`로 그대로 씁니다(같은 엔진을 JS로 옮겼고, `tests/test_engine_parity.py`가 두 쪽 값이 같은지 확인합니다).

### 정답지 · 판정 변수 — 근거 문서

정답지와 판정 변수는 [평가 지표 근거 문서](https://github.com/hyeondata/drawing-library/tree/main/evidence)(평면 평가 랩 v0.3.0)를 따릅니다.
점수가 높다고 ‘살기 좋은 평면’이라는 뜻이 아니라, **한국 실거주 아파트 평면 유형(거실 중심 유전형)에 얼마나 가까운가**를 잽니다
— 공간구문 값이 거주 만족도를 예측한다는 SCI·SCIE 근거는 찾지 못했기 때문입니다(근거 문서 1장).

| 영역(가중치) | 지표 | 채점 | 근거(등급) |
|---|---|---|---|
| 공간구문 (30) | 거실/침실 · 주방/침실 통합도 비 | Qn z, 양측 | Byun & Choi 2016, Choi et al. 2014 (A) |
| | 유전형 순위 부합도 τ (거실 > 주방 > 현관 > 침실 > 화장실) | 백분위, ↑ | Hillier et al. 1987, Choi et al. 2014 (A) |
| | 유전형 프로필 거리 | Qn z, ↓ | 같은 문헌 (A·C) |
| | 공·사 깊이 차 | 백분위, ↑ | Park et al. 2024, Ham & Lee 2017 (B) |
| | 기능실 평균 통합도(log K 회귀 잔차, ×0.5) · 거실 통제값(참고) | Qn z | Hillier & Hanson 1984, Ostwald 2011 (C) |
| 면적 구성 (20) | 거실·주방·침실·화장실·발코니 면적비 · 공용/개인 면적비 · 안방/다른 침실 면적비 | Qn z, 양측 | Sun et al. 2022 (D) · Park et al. 2024 · Zeng et al. 2025 (B) |
| 형태 (10) | 실 직사각형도(회전 MBR) ↑ · 실 종횡비 ↓ · 가장 좁은 침실의 상대 폭 ↑ | Qn z, 단측 | Rosin 1999, Rodrigues et al. 2013, Upasani et al. 2020 (B) |
| 외기 접면 (10) | 거주실 외기 접면비 ↑ | Qn z, 단측 | Ju & Oh 2020 (B) |

- 척도는 MAD 대신 **Qn**(Rousseeuw & Croux 1993), 점수 = 100 × max(0, 1 − |z| / 3). Qn이 0이거나 값이 몇 개뿐인 지표는 백분위로 채점합니다.
- 같은 침실 수 세대가 15개 이상이면 그 층의 분포와 비교합니다(층화). 지표 점수를 영역 안에서 가중 평균하고 영역 가중치로 합친 값이 `@typicality`입니다.
- 판정 변수: 축척 배율 s = 시트 침실 한 변 중앙값 ÷ 305px. 실 사이 간격 32px(외벽 쪽 50px, 보정 안 함), 최소 접촉 40px × max(1, s), 덕트 12,000px² × s², 채광 81px × s, 문·창 겹침 20% — 근거 문서 4장의 표본 실측(등급 D)과 Seo 2007 · Ju & Oh 2020.
- 근거 문서와 다른 점: 그래프는 기본으로 **문 추정(투과) 그래프**를 씁니다(근거 문서는 벽 인접 그래프 — 통과형 침실을 잡지 못하는 한계를 스스로 밝힘). 판정 변수의 ‘그래프 규약’을 `adjacency`로 바꾸면 근거 문서와 같은 규약입니다.
  기준 분포는 근거 문서의 35세대가 아니라 AI 허브 전체 21,383세대입니다. 도면 단위 leave-one-out은 하지 않습니다.
- 전체 분포에서 나온 값은 근거 문서 표본과 비슷합니다 — 거실/침실 통합도 비 중앙값 2.57(문서 2.62), τ 0.80(0.80), 공·사 깊이 차 0.75(0.75), 직사각형도 0.81(0.80).

### 로그인 · 활동 기록

사이트 전체가 **구글 로그인**을 거칩니다. 회원가입은 없고, **관리자가 허용한 이메일과 관리자만** 들어옵니다(관리자: `newofbest2@gmail.com`, 워크플로 변수 `ADMIN_EMAILS`).
누가 언제 무엇을 했는지 서버 SQLite에 남깁니다 — 로그인·로그아웃·거부, 데이터 가져오기(출처·파일 이름)·삭제·다시 계산, 판정 변수·평가 구조·정답지 변경,
통계 보관·삭제·불러오기, 내려받기, 계정 허용·해제. 활동 기록은 관리자만 **관리 › 허용 계정 · 활동 기록**에서 보고 CSV로 내려받습니다.

| 구성 | 내용 |
|---|---|
| `server/floorplan-api/server.mjs` | Node 22 내장 모듈만 쓰는 API(구글 OAuth 인가 코드 흐름 · 세션 쿠키 `__Host-fp_sid` · 허용 목록 · 활동 기록). 쓰기 요청은 같은 출처 JSON만 받음(CSRF 차단) |
| `deploy/api-up.sh` | 서버에서 컨테이너 `floorplan-api`(node:22-slim, deepvoice-net, 읽기 전용·권한 없음·256MB)를 띄움. 데이터 `~/deepvoice/floorplan-api/data` |
| `deploy/caddy/sapcesyntax.com.caddy` | 공유 Caddyfile의 sapcesyntax.com 블록 — `/api/*` → API, 나머지는 `forward_auth`로 로그인 확인. `apply.py`가 이 블록만 바꿈 |

**처음 켜는 순서**

1. Google Cloud Console → API 및 서비스 → OAuth 동의 화면(외부, 앱 이름 ‘도면 평가 프로그램’, 범위 openid·email·profile, 게시) →
   사용자 인증 정보 → OAuth 클라이언트 ID(웹 애플리케이션), 승인된 리디렉션 URI `https://sapcesyntax.com/api/auth/callback`.
2. 저장소 시크릿 `GOOGLE_CLIENT_ID` · `GOOGLE_CLIENT_SECRET` 등록(본인 터미널에서 `gh secret set GOOGLE_CLIENT_SECRET -R Imperfective/floorplan-spacesyntax` 후 붙여넣기).
3. 워크플로를 다시 돌리면(Actions → Deploy to VPS → Run workflow) API가 설정을 읽고, 화면이 로그인을 요구하기 시작합니다.
4. 서버 앞단 관문 켜기 — `python3 apply.py <Caddyfile> sapcesyntax.com.caddy --gate`(백업 · `caddy validate` 뒤 `caddy reload`). 관문은 API가 판정하므로 API가 멈추면 사이트도 닫힙니다.

구글 설정 전에는 API가 `login: false`를 알려 화면이 로그인 없이 동작합니다(기록도 남지 않음).
로컬 시험: `DEV_LOGIN=1 PUBLIC_ORIGIN=http://localhost:8765 ADMIN_EMAILS=… DB_PATH=./test.db node server/floorplan-api/server.mjs` — `/api/auth/dev?email=`로 허용된 계정에 바로 로그인(https 주소에서는 꺼짐).

### 조건 문법 (웹·CLI 공통)

```
대상.지표  연산자  값  [.. 최악값 | ± 허용치]  [w=가중치]  [as=penalty:점수 | as=gate]  [agg=worst|mean]

@missing_required    <= 0          as=gate         # 못 맞추면 총점 0
@overlap_pairs       <= 0          as=penalty:25   # 못 맞춘 만큼 25점까지 감점
living.integration_rank <= 1 .. 4  w=2             # 가중 평균에 들어감
master.step_depth    == 3 ± 1.5    w=1.5
@typicality          >= 90 .. 40   w=3             # 정답지 근접도
#! bed.aspect <= 2.5 as=penalty:5                  # '#!' = 꺼 둔 조건
```

```
기본점 = Σ(가중치 × 조건점수) ÷ Σ가중치 × 100
총점   = 기본점 − Σ 감점 × (1 − 조건점수),   필수 조건을 하나라도 못 맞추면 0
```

대상: 전역 `@` · `living bed master(가장 큰 침실) kitchen entry bath balcony dress ac etc multi`.
지표 목록은 `python aihub_eval.py config --list`.

### CLI

```bash
python aihub_eval.py baseline <02.라벨링데이터> -o out/baseline.json         # 정답지 분포
python aihub_eval.py config -o my.json                                         # 기본 설정 파일(웹과 같은 형식)
python aihub_eval.py score  <파일|폴더> --baseline out/baseline.json --config my.json -v --csv out/s.csv                            --stats out/stats.json --name "3R2B 시공성 v1" --memo "근거: …"   # 웹 통계와 같은 JSON
python aihub_eval.py render <파일|폴더> -o out/svg --baseline out/baseline.json --config my.json   # SVG 도면
python aihub_eval.py struct <STR 파일|폴더> -v                                 # 문·창 겹침
python tests/test_aihub_eval.py && python tests/test_engine_parity.py          # 검증
```

| 갈래 | 내용 |
|---|---|
| 세대 분리 | 한 시트의 실들을 벽 두께(≤32px) 인접 그래프로 묶고, 현관이 여럿이면 현관 기준으로 나눔 |
| 문 추정 | SPA엔 문이 없으므로 맞닿은 실 + 용도별 출입 규칙으로 투과성 그래프 추정 |
| ① 시공 가능성 | 필수실 · 겹침 · 출입 불가 실 · 침실 경유 · 주방-화장실 직결 · 채광 · 실 형태(장단변비·충전율) · 문·창 겹침(STR) |
| ② 공간구문 | 외부(carrier)를 현관에 붙인 그래프의 깊이·RRA·통합도·순위·선택도 (`spacesyntax.analyze_graph` 재사용) |
| ③ 근접도 | 면적비·깊이·거실 통합도 순위 등 특징의 강건 z-점수 → 0~100. 같은 유형(예: `3R2B`) 분포 우선 |

주의 — 라벨엔 축척이 없고 시트마다 다릅니다. 그래서 평형 대신 **침실-화장실 수 유형**(`3R2B` 등)으로 묶고,
면적은 세대 합계 대비 비율로만 비교합니다(㎡ 표기는 추정치). 각 기준의 근거는 `evaluate.CRITERIA`, 조건별 메모(`why`)에 적습니다.

---|---|
| 세대 분리 | 한 시트의 실들을 벽 두께(≤32px) 인접 그래프로 묶고, 현관이 여럿이면 현관 기준으로 나눔 |
| 문 추정 | SPA엔 문이 없으므로 맞닿은 실 + 용도별 출입 규칙(`PermeabilityRules`)으로 투과성 그래프 추정 |
| ① 시공 가능성 | F1 필수실 · F2 겹침 · F3 출입 불가 실 · F4 침실 경유 · F5 주방-화장실 직결 · F6 채광 · F7 형태비 · F8 문·창 겹침(STR) |
| ② 공간구문 | 외부(carrier)를 현관에 붙인 그래프의 깊이·RRA·통합도 순위 (`spacesyntax.analyze_graph` 재사용) |
| ③ 근접도 | 면적비·깊이·거실 통합도 순위 등 특징의 강건 z-점수 → 0~100. 같은 유형(예: `3R2B`) 분포 우선 |

주의 — 라벨엔 축척이 없고 시트마다 다릅니다. 그래서 평형 대신 **침실-화장실 수 유형**(`3R2B` 등)으로 묶고,
면적은 세대 합계 대비 비율로만 비교합니다(㎡ 표기는 추정치). 각 기준의 근거는 `evaluate.CRITERIA`에 모여 있습니다.

---

## 구조

```
floorplan_bench/
  spec.py            건물 프로그램(실·면적·속성) + 격자 정의
  env.py             환경 변수 12개 · 프리셋 10종
  terms.py           목적 함수의 단일 출처 — CP-SAT·QUBO·독립 평가기 공용
  plan.py            도면 표현 · 좌표 변환 · 면적 보정
  qubo.py            terms → dimod BQM
  generate.py        AI 도면 생성 (Claude 구조화 출력 / BSP 절차적)
  solve_ortools.py   CP-SAT (네이티브 제약 + 연결성 유량 정식화 + 워밍업 힌트)
  solve_dwave.py     Ocean (sa / tabu / qpu / hybrid)
  diagnose.py        진단 실험 E1~E5 + 제약 보존 교환 어닐러
  spacesyntax.py     공간구문 분석 엔진 (그래프 · VGA · 아이소비스트)
  syntax_render.py   j-graph · 히트맵 SVG
  report.py          평면도 SVG · 지표 분해
  aihub.py           AI 허브 라벨(COCO JSON) → 세대 분리 · 맞닿은 실 · 외기 접면
  evaluate.py        문 추정 · 시공 가능성 점검 · 실별/전역 지표 · 정답지 분포
  criteria.py        사용자 평가 구조 — 조건 문법 · 반영방식(가중/감점/필수) · 채점 · 설정 파일
  stats.py           채점 결과 → 통계 JSON (웹 통계 탭과 같은 형식)
  render_aihub.py    라벨 JSON → SVG 도면

main.py              4단계 파이프라인 CLI
run_study.py         전체 연구 (주 비교 + 스윕 + 진단)
build_paper.py       연구 결과 → 논문 형식 HTML
syntax_cli.py        Space Syntax CLI
syntax_report.py     Space Syntax 결과 → HTML
aihub_eval.py        AI 허브 라벨 평가 CLI (baseline · config · score · render · struct)

docs/index.html              도면 평가 프로그램 = 사이트 (AI 허브 zip·JSON 가져오기 · 통계 · Works Design System)
docs/aihub.html · aihub/ · image/   예전 주소를 첫 화면으로 넘기는 이동 페이지
docs/fonts/                  Pretendard Variable · Red Hat Display (자체 서빙)
docs/aihub-engine.js         평가 엔진 JS판 — floorplan_bench의 aihub·evaluate·criteria·stats와 같은 값
docs/aihub-stats.js          연구용 통계(기술통계·Kruskal–Wallis·Dunn·ANOVA·χ²·Spearman·Wilson, 분포 그림) — 외부 라이브러리 없음
docs/grid-editor.html        격자로 직접 그리는 이전 버전
docs/syntax-report.html      Space Syntax 분석 리포트
docs/benchmark-report.html   OR-Tools vs D-Wave 비교 리포트
examples/                    예제 도면 · 규칙 파일 · CP-SAT 입문 예제
docs/data/                   기본 데이터(결과물만) — AI 허브 전체 정답지·통계
tools/build_default_data.js  AI 허브 라벨 → 기본 데이터 만들기
server/floorplan-api/        구글 로그인 · 허용 계정 · 활동 기록 API (Node 22, 의존성 없음)
deploy/api-up.sh · deploy/caddy/   API 컨테이너 띄우기 · 공유 Caddyfile의 sapcesyntax.com 블록
tests/                       AI 허브 평가기 테스트 · 웹 엔진↔파이썬 일치 검사(node 필요)
```

## 선택적 자격 증명

| 환경 변수 | 없으면 | 있으면 |
|---|---|---|
| `ANTHROPIC_API_KEY` | BSP 절차적 생성기로 대체 | Claude가 구조화 출력으로 도면 생성 (`--backend claude`) |
| `DWAVE_API_TOKEN` | 로컬 시뮬레이티드 어닐링 | 실제 D-Wave QPU / Leap 하이브리드 (`--dwave qpu`) |

두 값이 없어도 모든 기능이 동작합니다.

## 참고 문헌

* Hillier, B. & Hanson, J. (1984). *The Social Logic of Space*. Cambridge University Press.
* Turner, A. et al. (2001). From isovists to visibility graphs. *Environment and Planning B*, 28(1).
* Benedikt, M. L. (1979). To take hold of space: isovists and isovist fields. *Environment and Planning B*, 6(1).
* Brandes, U. (2001). A faster algorithm for betweenness centrality. *Journal of Mathematical Sociology*, 25(2).


---

## 배포

주소는 **https://sapcesyntax.com** 하나입니다. 로그인 없이 같은 화면이 열리지 않도록 GitHub Pages 사본은 껐습니다(2026-10-22).

### sapcesyntax.com (netcup VPS) — 자동 배포

**`main`에 `docs/` · `server/` 변경을 푸시하면 GitHub Actions가 자동으로 배포합니다** (`.github/workflows/deploy.yml`).

지금 서버에서는 호스트 Caddy가 아니라 Docker 컨테이너 **`deepvoice-caddy`** 가 이 사이트를 서빙합니다.
컨테이너의 `/data/floorplan`이 호스트의 `/home/minkyu/deepvoice/caddy/data/floorplan`에 마운트돼 있어,
정적 파일은 그 폴더 하나만 rsync로 바꾸고 재시작 없이 바로 반영됩니다. 로그인·기록 API는 같은 네트워크의 컨테이너 `floorplan-api`로
배포합니다(`deploy/api-up.sh`, 코드·설정이 바뀔 때만 다시 띄움). 같은 Caddy가 다른 사이트도 서빙하므로 워크플로는 Caddy 설정을 건드리지 않습니다 —
sapcesyntax.com 블록은 `deploy/caddy/`로 한 번 바꿔 두었습니다(백업 `Caddyfile.bak.sapcesyntax-api.*`). root SSH 로그인은 막혀 있으므로 `minkyu` 계정으로 배포합니다.

| 저장소 설정 (Settings → Secrets and variables → Actions) | 값 |
|---|---|
| Secret `SSH_HOST` | `152.53.208.67` |
| Secret `SSH_USER` | `minkyu` |
| Secret `SSH_PRIVATE_KEY` | 배포용 개인키 전문 (공개키는 서버 `minkyu`의 `~/.ssh/authorized_keys`에 등록) |
| Secret `SSH_PORT` · Variable `DEPLOY_PATH` · `SITE_URL` | 선택 — 기본 22 · 위 폴더 · `https://sapcesyntax.com` |
| Secret `GOOGLE_CLIENT_ID` · `GOOGLE_CLIENT_SECRET` | 구글 OAuth 클라이언트(웹) — 없으면 로그인 없이 동작 |
| Variable `ADMIN_EMAILS` · `API_DIR` | 선택 — 기본 `newofbest2@gmail.com` · `/home/minkyu/deepvoice/floorplan-api` |

워크플로는 배포 전에 `index.html`의 엔진 주소(`aihub-engine.js?v=…`)를 엔진 파일 해시로 바꿉니다
(서버가 `.js`를 1년 캐시하므로 엔진이 바뀔 때만 새로 받게 하기 위함). 배포 후 사이트의 파일이 배포본과 같은지 확인합니다.

로컬에서 같은 일을 하려면 (rsync가 없는 윈도우 Git Bash에서도 됨):

```bash
SSH_KEY=~/.ssh/<배포키> DEPLOY_HOST=minkyu@152.53.208.67 bash deploy/deploy.sh
```

### 새 서버에 설치 (호스트 Caddy)

정적 파일 한 벌이라 어떤 서버에도 올라갑니다. `deploy/`에 필요한 것이 들어 있습니다.
아래는 Caddy를 호스트에 직접 설치하는 경우이며, 이때 웹 루트는 `/var/www/floorplan`입니다
(`deploy.sh`를 쓸 때는 `WEBROOT=/var/www/floorplan`).

**서버 콘솔에서 한 줄** — 설치와 업데이트가 같은 명령입니다.

```bash
curl -fsSL https://github.com/Imperfective/floorplan-spacesyntax/raw/main/deploy/install.sh \
  | SITE_DOMAIN=sapcesyntax.com bash
```

SSH 키를 등록해 두었다면 로컬에서 배포해도 됩니다.

```bash
ssh 사용자@서버 'SITE_DOMAIN=sapcesyntax.com bash -s' < deploy/install.sh   # 최초
WEBROOT=/var/www/floorplan DEPLOY_HOST=root@서버 bash deploy/deploy.sh       # 파일만 갱신
```

| 파일 | 하는 일 |
|---|---|
| `deploy/setup-vps.sh` | Caddy 설치(없을 때만) · 웹 루트 · 방화벽 · 사이트 블록 설치. **기존 Caddy 설정을 덮어쓰지 않습니다** — 백업 후 `conf.d/`에 이 사이트만 추가 |
| `deploy/site.caddy.tpl` | 자동 HTTPS · 압축 · 보안 헤더 · CSP · 캐시 정책 · `/grid` `/syntax` `/benchmark` `/aihub` 단축 경로 |
| `deploy/deploy.sh` | `docs/`를 올림(엔진 해시 적용). root로 호스트 Caddy에 올릴 때만 소유자·Caddy 재적용 |
| `deploy/nginx.conf` | Caddy 대신 nginx를 쓸 경우의 설정 (certbot 필요) |
| `deploy/install.sh` | 서버에서 한 줄로 클론·설정·배포·검증까지. 재실행하면 업데이트 |
| `.github/workflows/deploy.yml` | main에 푸시하면 자동 배포 — 정적 사이트 + 로그인·기록 API (시크릿·변수는 위 표) |

#### Cloudflare DNS 설정

```
A      @      <VPS IPv4>     프록시 끔(회색 구름)   ← 인증서 발급 때까지
AAAA   @      <VPS IPv6>     프록시 끔
CNAME  www    example.com    프록시 끔
```

**순서가 중요합니다.** Caddy가 Let's Encrypt 인증서를 받으려면 80/443이 서버까지
그대로 닿아야 하므로, 처음에는 **DNS only(회색 구름)** 로 두세요.
`https://도메인`이 열리는 것을 확인한 뒤 프록시(주황 구름)를 켜고,
SSL/TLS 모드를 반드시 **Full (strict)** 로 바꿉니다.
(Flexible로 두면 브라우저↔Cloudflare 구간만 암호화되고 뒷구간이 평문이 됩니다.)
