# 도면 평가 프로그램

아파트 평면도를 **공간구문(Space Syntax)과 시공 가능성**으로 평가하는 연구 도구입니다.
실제 지어진 아파트(AI 허브 「건축 도면 데이터」)를 **정답지**로 삼아, 생성 모델이 만든 도면이
① 지을 수 있는 구성인지 ② 한국 실거주 아파트 평면 유형에 얼마나 가까운지를 점수로 냅니다.

**사이트 → https://sapcesyntax.com** (구글 로그인 · 허용된 계정만)

| | |
|---|---|
| [1. 도면 평가 프로그램](#1-도면-평가-프로그램) | 도면 가져오기 · 채점 · 연구용 통계 · 공유 보관 기록 |
| [2. 평가 모델](#2-평가-모델) | 세대 나누기 · 시공 점검 · 정답지 근접도(근거 문헌) · 조건 문법 |
| [3. 데이터 저장과 공유](#3-데이터-저장과-공유) | 무엇이 브라우저에, 무엇이 서버에 남는가 |
| [4. 기본 데이터(AI 허브)](#4-기본-데이터ai-허브) | 결과물만 탑재 · 다시 만들기 · 재배포 제한 |
| [5. CLI](#5-cli) | 웹과 같은 값을 내는 파이썬 평가기 |
| [6. 연구 도구](#6-연구-도구) | Space Syntax CLI · OR-Tools vs D-Wave 벤치마크 |
| [7. 배포·운영](#7-배포운영) | 자동 배포 · 서버 구성 · 로그인 설정 |
| [8. 검증](#8-검증) | 테스트와 일치 검사 |

---

## 1. 도면 평가 프로그램

`docs/index.html` 한 파일이 프로그램입니다(평가 엔진 `docs/aihub-engine.js`, 통계 `docs/aihub-stats.js`, 외부 라이브러리 없음).

### 메뉴

| 메뉴 | 하는 일 |
|---|---|
| 분석 › **통계** | 요약 · 분포·집단 비교 · 등급 · 상관 · 기술통계 · 조건·점검 · 점수표 ([연구용 통계](#연구용-통계)) |
| 분석 › **도면** | 도면 그리기(실 색·이름·추정 문·연결 그래프·문제 표시, 확대·이동), 세대별 총점·시공 점검·조건별 점수·실별 지표·정답지 근접도 |
| 데이터 › **데이터 가져오기** | 아래 표의 여섯 가지 방법. 보유 데이터(출처별 파일·세대 수, 다시 계산, 삭제) |
| 평가 설정 › **평가 구조** | 조건 추가·삭제·켜고 끄기, 반영 방식(가중 평균·감점·필수), 세트 적용, 설정 가져오기·내보내기 |
| 평가 설정 › **판정 변수** | 세대 읽기·문 추정·판정 기준값과 정답지 채점 변수. 변수마다 근거 문헌·근거 등급 |
| 평가 설정 › **정답지** | 지표 18개의 정의·채점 방식·중앙값·Qn·근거, 침실 수 층화, 참고 문헌 |
| 기록 › **보관 기록** | 통계 기록 — **로그인한 모든 사람이 공유**. 열어 보기 · 조건·변수 적용 · JSON 내려받기 |
| 관리 › **허용 계정 · 활동 기록** | 관리자만. 로그인 허용 이메일 관리, 누가 언제 무엇을 했는지 검색·CSV |

### 도면 가져오기

| 방법 | 내용 |
|---|---|
| **AI 허브 라벨** | 받은 `download.tar`(안의 `TL_SPA.zip.part0` 조각 포함)나 라벨 zip을 그대로 놓으면 브라우저에서 열어 라벨 종류·주택 유형·도면 종류·개수·이름으로 골라 가져옴 |
| **파일 업로드** | tar · zip · JSON · 엑셀(.xlsx) · CSV, 여러 개·폴더째 — 확장자에 따라 알아서 나눔 |
| **엑셀 · CSV 표** | 한 행 = 실 하나(도면 · 용도 · x · y · 너비 · 깊이 또는 좌표 · 단위 · 이름). 도면별 COCO JSON으로 바꿔 미리 보고 추가하거나 내려받음. 양식 CSV 제공 |
| **이미지 변환** | 평면도 PNG·JPG의 벽·방을 인식해 방 윤곽 다각형과 용도를 추정 → 확인·수정 후 JSON으로. 벽이 굵고 단순한 평면도용 |
| **직접 입력** | COCO JSON 붙여넣기 — 생성 모델 출력을 같은 기준으로 채점 |
| **예시** | 합성 도면 3장 |

### 연구용 통계

| 탭 | 내용 |
|---|---|
| 요약 | 세대 수 · 평균 · 시공 가능 비율 · 필수 조건 탈락 · 총점 분포 · 유형별 점수. 세대가 나오지 않은 파일(현관 라벨 없음) 수를 따로 표시 |
| 분포·집단 비교 | 변수(총점 · 정답지 근접도 · 영역 점수 4 · 근거 문서 지표 18 · 전역 지표)의 히스토그램 · 누적분포 · 기술통계. 집단(침실 수 · 유형 · 등급 · 시공 가능 · 출처)별 상자그림과 **Kruskal–Wallis H(ε²)**, **일원 분산분석 F(η²)**, **Dunn 사후검정(Holm)** |
| 등급 | A+~F 세대 수 · 비율 · 누적 비율 · **Wilson 95% CI**, 집단 × 등급 교차표와 **χ² 독립성 검정 · Cramér's V** |
| 상관 | **Spearman ρ / Pearson r** 행렬(히트맵, 짝별 완전 사례)과 p · n |
| 기술통계 | 논문 표 1 형식(n · 평균 · SD · 95% CI · 중앙값 · Q1 · Q3 · 최저 · 최고 · 왜도 · 첨도), 집단별로 나눔, 통계 방법 서술 문단 |

모든 표는 **CSV · 표 복사(엑셀·한글·워드) · Markdown · LaTeX**로 내보냅니다. 필수 조건 탈락(0점) 세대를 빼고 볼 수 있습니다.
세대가 2만 개를 넘으면 작은 차이도 p < .05가 되므로, 검정마다 효과크기와 그 크기(작음·중간·큼)를 함께 보여 줍니다.

### 로그인 · 활동 기록

회원가입은 없습니다. **관리자가 허용한 구글 계정과 관리자만** 들어옵니다(관리자 `newofbest2@gmail.com`).
허용을 해제하면 그 계정은 바로 로그아웃됩니다. 서버가 남기는 기록: 로그인·로그아웃·거부, 데이터 가져오기(출처·파일 이름)·삭제·다시 계산,
판정 변수·평가 구조·정답지 변경, 보관 기록 저장·삭제, 표·파일 내려받기, 계정 허용·해제. 관리자만 봅니다.

---

## 2. 평가 모델

평가 지표와 판정 기준은 [평가 지표 근거 문서](https://github.com/hyeondata/drawing-library/tree/main/evidence)(평면 평가 랩 v0.3.0)를 따릅니다.
점수가 높다고 ‘살기 좋은 평면’이라는 뜻은 아닙니다 — **한국 실거주 아파트 평면 유형(거실 중심 유전형)에 얼마나 가까운가**와
**지을 수 있는 구성인가**를 잽니다. 공간구문 값이 거주 만족도를 예측한다는 SCI·SCIE 근거는 찾지 못했기 때문입니다.

### 세대 나누기

라벨(COCO JSON)에는 실 폴리곤만 있고 **세대를 묶는 정보가 없습니다**(7,275장 · 413,031개 라벨 확인 — 필드는 id · 용도 · 폴리곤 · 면적 · occluded뿐).
그래서 벽 하나 사이로 맞닿은 실을 그래프로 잇고 **현관 하나 = 세대 하나**로 나눕니다. 현관이 여러 조각으로 그려진 도면은 조각마다 따로 세대가 되고,
거실·주방이 없으면 필수 조건에서 탈락합니다(데이터가 한 세대로 묶지 않은 것은 합치지 않음). 현관 라벨이 없는 도면(59장)은 세대가 나오지 않습니다.

### 시공 점검과 평가 구조

문은 SPA 라벨에 없어 맞닿은 실과 용도별 출입 규칙으로 추정합니다(판정 변수에서 벽 인접 그래프로 바꿀 수 있음).
점검 항목: F1 필수실 · F2 실 겹침 · F3 출입 불가 실 · F4 침실 경유 · F5 주방-화장실 직결 · F6 채광(외기 접면) · F8 문·창 겹침(STR).
무엇을 어떻게 점수에 넣을지는 **평가 구조**(조건 문법)로 정합니다.

```
대상.지표  연산자  값  [.. 최악값 | ± 허용치]  [w=가중치]  [as=penalty:점수 | as=gate]  [agg=worst|mean]

@missing_required    <= 0          as=gate         # 못 맞추면 총점 0
@overlap_pairs       <= 0          as=penalty:25   # 못 맞춘 만큼 25점까지 감점
living.integration_rank <= 1 .. 4  w=2             # 가중 평균에 들어감
@typicality          >= 90 .. 40   w=3             # 정답지 근접도
#! bed.aspect <= 2.5 as=penalty:5                  # '#!' = 꺼 둔 조건

기본점 = Σ(가중치 × 조건점수) ÷ Σ가중치 × 100
총점   = 기본점 − Σ 감점 × (1 − 조건점수),   필수 조건을 하나라도 못 맞추면 0
```

대상: 전역 `@` · `living bed master(가장 큰 침실) kitchen entry bath balcony dress ac etc multi`. 지표 목록은 `python aihub_eval.py config --list`.
등급: A+ 95 · A 90 · B+ 85 · B 80 · C+ 70 · C 60 · D 45 이상, 그 아래 F.

### 정답지 근접도(`@typicality`)

AI 허브 21,383세대의 지표 분포와 비교해 0~100점. 같은 침실 수 세대가 15개 이상이면 그 층의 분포와 비교합니다.

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

- 점수 = 100 × max(0, 1 − |z| / 3), z는 중앙값과 **Qn 척도**(Rousseeuw & Croux 1993). 값이 몇 개뿐인 지표와 Qn이 0인 지표는 백분위로 채점합니다.
- 판정 변수: 축척 배율 s = 시트 침실 한 변 중앙값 ÷ 305px. 실 사이 간격 32px(외벽 쪽 50px), 최소 접촉 40px × max(1, s), 덕트 12,000px² × s²,
  채광 81px × s, 문·창 겹침 20%. 라벨에 축척이 없어 모든 지표는 축척과 무관한 비율입니다(㎡ 표시는 추정치).
- 근거 문서와 다른 점: 그래프는 기본으로 **문 추정(투과) 그래프**(근거 문서는 벽 인접 그래프 — 판정 변수 ‘그래프 규약’으로 같게 할 수 있음),
  기준 분포는 근거 문서의 35세대가 아니라 AI 허브 21,383세대. 도면 단위 leave-one-out은 하지 않습니다.
- 근거 등급: **A** 한국 아파트 SCIE·SSCI 실증 · **B** SCIE·SSCI가 같은 지표·방향 · **C** 이론서·비SCIE 방법론 · **D** AI 허브 표본 실측·실무 관행.
  전체 서지(DOI)는 프로그램의 **정답지** 화면에 있습니다.

---

## 3. 데이터 저장과 공유

| 무엇 | 어디에 | 누가 보나 |
|---|---|---|
| 가져온 도면 원본 · 세대 요약 · 통계 화면 | **각자의 브라우저**(IndexedDB) | 그 브라우저만. 다른 PC·팀원과는 공유되지 않음 |
| 평가 구조 · 판정 변수 설정 | 각자의 브라우저(localStorage) | 그 브라우저만 — 설정 파일로 내보내 공유 |
| **보관 기록**(통계 스냅숏) | **서버**(SQLite, gzip) | **로그인한 모든 사람**. 지우기는 만든 사람과 관리자만 |
| 기본 정답지 · ‘AI 허브 전체’ 기록 | 서버 정적 파일 `docs/data/` | 모든 사람 |
| 허용 계정 · 활동 기록 | 서버(SQLite) | 관리자만 |

도면 파일 자체는 브라우저 밖으로 나가지 않습니다. 함께 볼 결과는 **‘현재 통계 보관’** 으로 공유 기록에 올립니다
(점수·지표·조건·변수가 한 기록에 들어감). 예전에 브라우저에만 보관한 기록은 보관 기록 화면의 **공유로 올리기**로 옮깁니다.

---

## 4. 기본 데이터(AI 허브)

사이트에는 AI 허브 TL_SPA 아파트 평면도 **7,275장(21,383세대)** 에서 계산한 **결과물만** 들어 있습니다.

| 파일 | 내용 |
|---|---|
| `docs/data/aihub-baseline.json` | 기본 정답지 — 지표 18개의 분포(전체 + 침실 수별 층) |
| `docs/data/aihub-default-stats.json` | 보관 기록 맨 위 ‘AI 허브 전체’ — 세대별 점수 · 영역 점수 · 지표(열 방식 압축) |

전체 결과: 평균 75.7점 · 시공 가능 88.4% · 정답지 근접도 중앙값 75.5 · 최다 유형 3R2B(9,924세대).
다시 만들기: `node tools/build_default_data.js <APT_FP_SPA JSON 폴더>`(약 4분).

**AI 허브 원본(라벨·이미지)은 저장소·사이트에 올리지 않습니다.** 이용정책상 원본 재배포는 금지이고 분석 결과는 출처를 밝혀 배포할 수 있습니다
— 출처: AI 허브 「건축 도면 데이터」(aihub.or.kr, 한국지능정보사회진흥원). 라벨은 각자 AI 허브에서 받습니다(datasetkey 71465, 라벨 zip 약 173MB).

---

## 5. CLI

웹과 같은 엔진의 파이썬판입니다(표준 라이브러리만 사용, 값 일치는 [검증](#8-검증)).

```bash
python aihub_eval.py baseline <라벨 폴더> -o out/baseline.json                 # 정답지
python aihub_eval.py config -o my.json                                         # 평가 구조 파일(웹과 같은 형식)
python aihub_eval.py score <파일|폴더> --baseline out/baseline.json --config my.json -v \
       --csv out/score.csv --stats out/stats.json --name "3R2B 시공성 v1"      # 통계 JSON은 웹 보관 기록으로 불러옴
python aihub_eval.py render <파일|폴더> -o out/svg --baseline out/baseline.json   # SVG 도면
python aihub_eval.py struct <STR 파일|폴더> -v                                   # 문·창 겹침
```

윈도우 콘솔에서 한글 도움말이 깨지면 `PYTHONIOENCODING=utf-8`을 붙입니다.

---

## 6. 연구 도구

### Space Syntax CLI

격자 도면의 공간구문 분석(그래프 지표 · VGA · 아이소비스트). JSON · CSV · HTML 리포트(`docs/syntax-report.html`).

```bash
python syntax_cli.py --plan-file examples/example_plan.txt --rules standard
python syntax_cli.py --plan-file examples/example_plan.txt --compare-rules     # 규칙 프리셋 비교
```

### OR-Tools vs D-Wave 벤치마크

평면 배치를 조합 최적화로 두고 **같은 목적 함수**(`floorplan_bench/terms.py` 한 곳에서 생성)를 OR-Tools CP-SAT와 D-Wave Ocean(QUBO)에 주어 비교합니다.

```bash
pip install -r requirements.txt
python main.py --spec apartment_8x8 --env balanced --time-limit 60       # 생성 → 데이터화 → 환경 변수 → 비교
python run_study.py && python build_paper.py                             # 전체 연구 → docs/benchmark-report.html
```

이전 실행에서 격차는 하드웨어·알고리즘이 아니라 **문제를 옮겨 적는 방식**(페널티 인코딩)에서 생겼습니다 — 같은 어닐링에 제약 보존 인코딩을 쓰면 대부분 사라짐.
Leap 토큰(`DWAVE_API_TOKEN`)이 없으면 CPU 시뮬레이티드 어닐링으로 동작하므로 결과는 *양자 대 고전*이 아니라 **어닐링 대 분기한정**으로 읽어야 합니다.
`ANTHROPIC_API_KEY`가 있으면 도면 생성에 Claude를 쓰고(`--backend claude`), 없으면 절차적 생성기로 대체합니다.

---

## 7. 배포·운영

**`main`에 `docs/` · `server/` 변경을 푸시하면 GitHub Actions가 자동 배포하고 서버 파일을 확인합니다**(`.github/workflows/deploy.yml`).

| 구성 | 내용 |
|---|---|
| 정적 사이트 | Docker 컨테이너 `deepvoice-caddy`(다른 사이트와 공유)가 `/data/floorplan`을 서빙. 워크플로가 rsync, 엔진·통계 js는 내용 해시로 캐시 무효화 |
| API `server/floorplan-api` | Node 22 내장 모듈만 사용 — 구글 OAuth · 세션 · 허용 계정 · 활동 기록 · 공유 보관 기록(SQLite). 컨테이너 `floorplan-api`(deepvoice-net, 읽기 전용 · 권한 없음 · 256MB), `deploy/api-up.sh`가 코드·설정이 바뀔 때만 다시 띄움 |
| Caddy 블록 `deploy/caddy/` | 공유 Caddyfile의 **sapcesyntax.com 블록만** 바꿈(`apply.py`, 백업 → `caddy validate` → `reload`). `/api/*` → API, 나머지는 `forward_auth`로 로그인 확인(API가 멈추면 사이트도 닫힘) |
| 수동 배포 | `SSH_KEY=~/.ssh/<배포키> DEPLOY_HOST=minkyu@152.53.208.67 bash deploy/deploy.sh` (정적 파일만) |

| 저장소 설정(Settings → Secrets and variables → Actions) | 값 |
|---|---|
| Secret `SSH_HOST` · `SSH_USER` · `SSH_PRIVATE_KEY` | 서버 주소 · `minkyu` · 배포용 개인키(root 로그인은 막혀 있음) |
| Secret `GOOGLE_CLIENT_ID` · `GOOGLE_CLIENT_SECRET` | 구글 OAuth 클라이언트(웹 애플리케이션, 리디렉션 URI `https://sapcesyntax.com/api/auth/callback`). ID는 `…apps.googleusercontent.com` 형식이어야 하며, 아니면 로그인을 끈 채 배포 |
| Variable `ADMIN_EMAILS` · `API_DIR` · `DEPLOY_PATH` · `SITE_URL` | 선택 — 기본 `newofbest2@gmail.com` · `~/deepvoice/floorplan-api` · `~/deepvoice/caddy/data/floorplan` · `https://sapcesyntax.com` |

로컬 시험: `DEV_LOGIN=1 PUBLIC_ORIGIN=http://localhost:8765 ADMIN_EMAILS=… DB_PATH=./test.db node server/floorplan-api/server.mjs`
— `/api/auth/dev?email=`로 허용된 계정에 바로 로그인합니다(https 주소에서는 켜지지 않음).

---

## 8. 검증

```bash
python tests/test_aihub_eval.py          # 평가기(세대 나누기 · 점검 · 정답지 · 조건 · 통계)
python tests/test_engine_parity.py [라벨 폴더]   # 웹 엔진(JS) ↔ 파이썬 값 일치 — 실제 라벨 300장(948세대)에서 오차 0
node tests/test_stats.js                 # 연구용 통계를 기준값(t·χ²·F 분포표, R 예제, Wilson 등)과 대조
```

---

## 저장소 구조

```
docs/index.html            도면 평가 프로그램(사이트)
docs/aihub-engine.js       평가 엔진 — floorplan_bench와 같은 값
docs/aihub-stats.js        연구용 통계 · 분포 그림
docs/data/                 기본 데이터(결과물만)
docs/fonts/                Pretendard · Red Hat Display(자체 서빙)
docs/syntax-report.html    Space Syntax 리포트 · docs/benchmark-report.html  벤치마크 리포트
server/floorplan-api/      로그인 · 허용 계정 · 활동 기록 · 공유 보관 기록 API
deploy/                    api-up.sh · caddy/(블록 · apply.py) · deploy.sh
tools/build_default_data.js  AI 허브 라벨 → 기본 데이터
aihub_eval.py              평가 CLI
floorplan_bench/           aihub · evaluate · criteria · stats · render_aihub(평가) / spacesyntax · syntax_render(공간구문)
                           spec · env · terms · plan · qubo · generate · solve_ortools · solve_dwave · diagnose · report(벤치마크)
main.py · run_study.py · build_paper.py · syntax_cli.py · syntax_report.py · examples/
tests/                     test_aihub_eval.py · test_engine_parity.py · engine_dump.js · test_stats.js
```

화면은 Works Design System(Pretendard · deep teal 주색 · 흰 카드 1겹 · 화면당 주 액션 1개)을 따릅니다.
