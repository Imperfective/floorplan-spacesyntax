# 건축 평면 최적화 · 공간구문 분석 도구모음

AI가 생성한 건물 도면을 **좌표로 데이터화**하고, **"좋은 도면"을 수치 함수로 정의**한 뒤,
서로 다른 방법으로 평가·최적화해 비교하는 실험 도구모음입니다.

**사이트 → https://sapcesyntax.com** (첫 화면 = D 도면 평가 스튜디오 · `/image.html` = A 이미지 분석 스튜디오)

네 갈래로 이루어져 있습니다.

| # | 갈래 | 무엇을 하는가 |
|---|---|---|
| **A** | [이미지 분석 스튜디오 (웹)](#a-도면-공간구문-스튜디오-웹) | **도면 PNG를 올리면** 벽·방·문·좌표를 파싱해 데이터화하고, 입력한 Space Syntax 조건을 자동 적용해 채점 |
| **B** | [Space Syntax CLI](#b-space-syntax-cli) | 같은 분석을 명령줄에서. JSON·CSV 내보내기와 규칙 비교 |
| **C** | [OR-Tools vs D-Wave 벤치마크](#c-or-tools-vs-d-wave-벤치마크) | 동일한 목적 함수를 고전 조합 최적화와 양자 어닐링 계열에 각각 주고 비교 |
| **D** | [AI 허브 라벨(JSON) 평가 모델](#d-ai-허브-라벨json-평가-모델) — **사이트 첫 화면** | **AI 허브 도면 라벨 JSON을 여러 개 올리면** 도면을 그리고, 사용자가 정한 평가 구조(조건·반영방식·변수)로 채점해 통계로 모아 보관·JSON 내보내기 |

---

## 빠른 시작

```bash
# 파이썬 환경 (3.10+ 권장)
uv venv --python 3.12 .venv          # 또는 python3 -m venv .venv
uv pip install --python .venv/bin/python -r requirements.txt

# A. 이미지 분석 웹 앱 — 설치 없이 바로 (도면 PNG를 올리면 됩니다)
open docs/image.html

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

## A. 도면 공간구문 스튜디오 (웹)

**`docs/image.html`** — 의존성 없는 단일 HTML. 서버가 없고, 올린 이미지는 브라우저 밖으로 나가지 않습니다.
→ **https://sapcesyntax.com/image.html** (`/image`로도 들어갑니다)

### 하는 일

```
① 도면 PNG 업로드        끌어다 놓기 · 파일 선택 · 예시 도면
        ↓
② 벽 픽셀 검출           스포이드로 벽 색 지정 / 어두운 선 임계값
        ↓
③ 방·문·좌표 데이터화     벽을 부풀려 문 틈을 봉하고 방을 나눈 뒤 되자라기로 복원
        ↓
④ Space Syntax 조건 입력  문법으로 쓰면 조건 객체(JSON)로 데이터화
        ↓
⑤ 자동 채점              조건이 추출된 데이터에 자동 적용 → 100점 만점 + 등급
```

### 이미지에서 방을 뽑아내는 방법

평면도에서 방을 나누는 고전적 난점은 **문 틈**입니다. 문은 벽이 끊긴 자리이므로,
그대로 연결 요소를 구하면 온 집이 한 덩어리가 됩니다. 이 앱은 이렇게 풉니다.

1. **벽 마스크** — 지정한 벽 색과의 거리(또는 밝기)로 벽 픽셀을 고릅니다.
2. **거리 변환** — 모든 픽셀에서 가장 가까운 벽까지의 거리를 한 번만 계산합니다(Chamfer 3-4).
   덕분에 팽창 반경을 바꿔도 다시 계산하지 않습니다.
3. **문 틈 봉하기** — 벽에서 `r` 이내인 픽셀을 제외하면 문 틈이 막히고 방이 분리됩니다.
4. **되자라기** — 분리된 핵심부에서 열린 영역 전체로 다중 시작점 BFS를 돌려 방의 원래 넓이를 복원합니다.
5. **외부 인식** — 이미지 테두리에 닿는 가장 큰 영역을 **외부(carrier)** 로 봅니다.
   공간구문론이 요구하는 외부 노드가 자동으로 생깁니다.
6. **문 검출** — 두 방의 라벨이 *벽 없이* 맞닿은 구간이 곧 문입니다. 접촉 길이가 문 폭이 되고,
   외부와 맞닿은 문이 **현관문**입니다.
7. **자동 보정** — 문 틈 폭은 도면마다 다르므로, 방이 가장 잘 나뉘는 `r`을 자동으로 찾습니다.

### 입력하는 Space Syntax 조건

```
대상.지표  연산자  목표값  [.. 최악값]  [w=가중치]
```

* **대상** — 방 용도 키(`hall` `living` `kitchen` `master` `bed` `bath` `store` `balcony`) 또는 전역 `@`
* **연산자** — `<=` 작을수록 좋음 · `>=` 클수록 좋음 · `==` 목표값 ±허용치
* `#`으로 시작하면 주석

```
hall.step_depth          <= 1        w=2      # 현관은 외부에서 바로 닿아야
living.integration_rank  <= 1 .. 5   w=2      # 거실이 가장 통합적인 공간
master.integration       <= 0.7 .. 3 w=1.5    # 안방은 격리되어야
master.step_depth        == 3 ± 1    w=2      # 현관에서 세 단계쯤
@mean_depth_system       <= 1.4      w=1
@intelligibility         >= 0.9      w=1
@disconnected_rooms      <= 0        w=2.5    # 고립된 실 금지
```

**“데이터화 →”** 를 누르면 위 텍스트가 조건 배열로 변환되고 즉시 채점에 반영됩니다.

```
조건점수 = clamp((측정값 − 최악값) ÷ (목표값 − 최악값), 0, 1) × 100
최종점수 = Σ(가중치 × 조건점수) ÷ Σ(가중치)
```

같은 용도의 방이 여럿이면 **가장 낮은 점수**를 씁니다("그 용도의 방이 모두 만족해야").
등급: A+ ≥ 95 · A ≥ 90 · B+ ≥ 85 · B ≥ 80 · C+ ≥ 70 · C ≥ 60 · D ≥ 45 · F

내장 조건 세트: **주거 일반** · **프라이버시 우선** · **무장애 접근** · **가시성 중심(상업·전시)**

### 쓸 수 있는 지표

**실 단위** — 통합도(1/RRA) · 통합도 순위 · 평균깊이 · 연결도 · 제어값 ·
선택도(Brandes 매개 중심성) · 현관 깊이 · 시각 통합도 · 면적(㎡)

**전역** — 시스템 평균깊이 · 현관 최대깊이 · 명료성 r² · 차이계수 H* · 문 개수 ·
방 개수 · 고립된 실 수 · 평균 시각 통합도 · 시각 명료성

### 평수 — 도면이 몇 평인지 정하기

도면 이미지에는 치수가 없으므로, **평수를 사용자가 정해 주면** 그것을 기준으로
검출된 실내 전체를 환산합니다. 세 가지 방식 중 고를 수 있습니다.

| 방식 | 입력 | 쓰임 |
|---|---|---|
| **공급 평형** | 8~65평형 목록에서 선택 + 전용률(기본 75%) | 분양 평형만 아는 경우 |
| **전용 ㎡** | 전용면적을 ㎡로 직접 | 도면에 전용면적이 적혀 있는 경우 |
| **전용 평** | 전용면적을 평으로 직접 | 평 단위로 알고 있는 경우 |

한국 아파트의 "34평형"은 보통 **공급면적**이고 도면에 적히는 **전용면적**은 그 70~80%입니다.
전용률 75%를 쓰면 34평형 → 전용 84.3㎡(25.5평), 24평형 → 전용 59.5㎡(18.0평)로
실제 국민주택 규격과 맞아떨어집니다. 어느 방식으로 넣든 나머지 값이 역산되어 함께 표시됩니다.

정해진 면적은 **방마다의 ㎡·평·점유 비율**, **문 폭(m)**, 픽셀↔미터 환산에 모두 적용됩니다.
예컨대 같은 도면을 34평형으로 보면 거실 20.7㎡(6.3평), 24평형으로 보면 14.6㎡가 됩니다.

### 그 밖에

* 방을 클릭하면 이름과 용도를 바꿀 수 있고, 용도는 조건의 **대상**이 됩니다.
* “용도 자동 추정”이 크기와 외부 인접 관계로 현관·거실·안방 등을 먼저 찍어 줍니다.
* 결과는 JSON·CSV로 복사할 수 있습니다(방별 좌표·면적·전 지표, 문 좌표·폭).
* 격자에 직접 칠해 그리는 이전 버전은 **`docs/grid-editor.html`** 에 남겨 두었습니다.

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

→ **https://sapcesyntax.com** (사이트 첫 화면 · 예전 주소 `/aihub.html`·`/aihub`는 첫 화면으로 넘어갑니다)

PNG 인식 없이 AI 허브 '건축 도면 데이터'의 라벨 JSON(COCO 폴리곤)을 바로 읽어 **도면을 그리고** 세대별로 채점합니다.
실제 지어진 아파트(AI 허브)를 **정답지**로 삼고, 생성 도면이 ① 시공 가능한지 ② 정답지 분포에 얼마나 가까운지 봅니다.
**무엇을 어떻게 점수에 넣을지는 사용자가 정합니다**(조건 추가·삭제, 반영방식, 판정 변수).

### 웹 — `docs/index.html` (도면 평가 스튜디오)

라벨 JSON(SPA·STR·OBJ·OCR)을 **여러 개 또는 폴더째** 불러오면(파일 선택·폴더 선택·화면 어디에나 끌어다 놓기)
나눠서 처리하며 진행률을 보여 줍니다. 파일은 브라우저 밖으로 나가지 않습니다.

화면은 사내 **Works Design System**(MS DX팀) 규칙을 따릅니다 — Pretendard Variable(숫자 tnum)·Red Hat Display 워드마크,
deep teal 주색, 캔버스 배경 위 흰 카드 1겹, 화면당 주 액션 1개, 색은 상태(통과·주의·오류)에만.
폰트 파일은 `docs/fonts/`에서 직접 서빙합니다(서버 CSP가 외부 폰트 CDN을 막기 때문).

**GNB(상단)** — 워드마크 · 불러온 데이터 요약(도면 수·세대 수·평균 점수) · 사용 설명서(README).
**SNB(좌측)** — 기능별로 묶은 메뉴. 페이지마다 주소(`#/stats/summary` 등)가 있어 새로고침·뒤로가기·공유가 됩니다.

| 메뉴 | 헤더 탭 | 하는 일 |
|---|---|---|
| 분석 › **통계** | 요약 · 조건·점검 · 지표 · 세대 목록 | 불러온 모든 세대의 점수 요약, 총점 분포·등급, 유형별(`3R2B` 등) 점수·시공 가능 비율, 조건별 평균 조건점수·만점 비율, 시공 점검 위반 수, 전역 지표 요약, 세대 표(행을 누르면 그 도면으로). 툴바: 유형 필터 · CSV · 통계 JSON · **현재 통계 보관** |
| 분석 › **도면** | — | 왼쪽 파일 목록(검색, 파일 아래 세대) · 가운데 도면(실 색·실 이름·추정 문·연결 그래프·문제 표시·선택 세대 강조, 확대·이동) · 오른쪽 세대 결과(총점·등급, 시공 점검, 조건별, 실별 지표, 정답지 근접도). STR은 벽·문·창과 겹친 문·창 |
| 평가 설정 › **평가 구조** | 조건 · 문법 편집 | 조건을 **추가·삭제·켜고 끄기**. 대상(전역/실 용도)·지표·판정(범위/목표값/합격선)·**반영 방식**(가중 평균/감점/필수)·가중치·감점 크기, 근거 메모. 행마다 전체 세대 평균 조건점수·만점 비율. 세트 적용 · 설정 가져오기/내보내기 |
| 평가 설정 › **판정 변수** | — | 벽 두께 허용치·최소 접면·샤프트 기준·발코니 연결·겹침/채광 임계값 등. 바꾸면 모든 도면을 다시 읽고 재채점, 바뀐 변수는 ‘변경됨’ 표시 |
| 평가 설정 › **정답지** | — | 정답지 출처·유형별 세대 수. 불러온 세대로 만들기 또는 CLI가 만든 `baseline.json` 불러오기 |
| 기록 › **보관 기록** | (상세) 요약 · 조건·점검 · 지표 · 세대 목록 | 보관한 통계 목록(검색). 기록을 열면 그때의 통계를 같은 화면으로 다시 보고, **그 조건·변수 적용**, **JSON 내려받기**, 삭제(확인 창). 통계 JSON 불러오기 · 전체 내려받기 |

통계 JSON(`kind: "aihub-stats"`)에는 요약·유형별·조건별·위반·지표 통계와 함께 세대별 점수·전역 지표·조건점수(`units`),
그 통계를 낸 조건·변수(`config`), 정답지 정보가 들어 있어 연구 기록으로 그대로 남길 수 있습니다.
보관 기록은 이 브라우저(IndexedDB)에만 저장되므로, 다른 PC·팀원과 나눌 때는 JSON으로 내려받아 공유합니다.

평가 구조의 **설정 내보내기** JSON은 파이썬 CLI의 `--config`로 그대로 씁니다(같은 엔진을 JS로 옮겼고, `tests/test_engine_parity.py`가 두 쪽 값이 같은지 확인합니다).

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

docs/index.html              도면 평가 스튜디오 = 사이트 첫 화면 (AI 허브 라벨 JSON · Works Design System)
docs/image.html              이미지 분석 스튜디오 (도면 PNG 파싱 웹 앱)
docs/aihub.html · aihub/ · image/   예전 주소를 새 위치로 넘기는 이동 페이지
docs/fonts/                  Pretendard Variable · Red Hat Display (자체 서빙)
docs/aihub-engine.js         평가 엔진 JS판 — floorplan_bench의 aihub·evaluate·criteria·stats와 같은 값
docs/grid-editor.html        격자로 직접 그리는 이전 버전
docs/syntax-report.html      Space Syntax 분석 리포트
docs/benchmark-report.html   OR-Tools vs D-Wave 비교 리포트
examples/                    예제 도면 · 규칙 파일 · CP-SAT 입문 예제
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

메인 주소는 **https://sapcesyntax.com** 입니다. GitHub Pages는 같은 `docs/`를 그대로 서빙하는 보조 사본입니다
→ https://imperfective.github.io/floorplan-spacesyntax/

### sapcesyntax.com (netcup VPS) — 자동 배포

**`main`에 `docs/` 변경을 푸시하면 GitHub Actions가 자동으로 배포합니다** (`.github/workflows/deploy.yml`).

지금 서버에서는 호스트 Caddy가 아니라 Docker 컨테이너 **`deepvoice-caddy`** 가 이 사이트를 서빙합니다.
컨테이너의 `/data/floorplan`이 호스트의 `/home/minkyu/deepvoice/caddy/data/floorplan`에 마운트돼 있어,
배포는 그 폴더 하나만 rsync로 바꿉니다. 같은 컨테이너가 다른 사이트도 서빙하므로 Caddy 설정은 건드리지 않고,
정적 파일이라 재시작 없이 바로 반영됩니다. root SSH 로그인은 막혀 있으므로 `minkyu` 계정으로 배포합니다.

| 저장소 설정 (Settings → Secrets and variables → Actions) | 값 |
|---|---|
| Secret `SSH_HOST` | `152.53.208.67` |
| Secret `SSH_USER` | `minkyu` |
| Secret `SSH_PRIVATE_KEY` | 배포용 개인키 전문 (공개키는 서버 `minkyu`의 `~/.ssh/authorized_keys`에 등록) |
| Secret `SSH_PORT` · Variable `DEPLOY_PATH` · `SITE_URL` | 선택 — 기본 22 · 위 폴더 · `https://sapcesyntax.com` |

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
| `.github/workflows/deploy.yml` | main에 푸시하면 자동 배포 (시크릿 3개 + 선택 1개, 위 표) |

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
