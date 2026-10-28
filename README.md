# 건강검진 기반 질환 위험예측 모델 v3.3 — 배포판

건강검진 수치와 문진으로 **19개 질환의 1~10년 발생 위험**과 **건강나이·기대수명**을 계산하는 모델과 실행 코드입니다. 서울대학교병원 데이터로 학습하고, 국가 통계(국민건강영양조사·국가암등록 등)로 연령별 수준을 맞췄습니다.

- 입력·출력은 애니핏 건강위험분석 API 항목정의서 형식입니다(아래 "입력"·"출력").
- 모델 파일과 집계값만 있습니다. 환자 단위 자료는 들어 있지 않습니다.
- 브라우저만으로 돌려 보는 시험 페이지 `web/risk_test.html` 이 있습니다(모델 JSON 을 모두 담은 파일 1개).

## 모델

| 코드 | 질환 | 출력 이름 | 모형 | 10년 C | O/E | 배포 기준 예외 |
|---|---|---|---|---|---|---|
| htn33 | 고혈압 | Hypertension | XGBoost AFT | 0.847(8년)¹ | 1.00(5년)¹ | D-07 국가 목표 보정 미적용 |
| dm33 | 당뇨 | DM | XGBoost AFT | 0.889(8년)¹ | 0.93(5년)¹ | D-01 여성 70세 이상 구간 국가 목표 미달, D-21 LDL 빈칸 시 위험 변화 |
| dlp33 | 이상지질혈증 | Hyperlipidemia | XGBoost AFT | 0.799(8년)¹ | 0.97(5년)¹ | D-02 국가 목표 미적용 |
| obe33 | 비만 | Obesity² | XGBoost AFT | 0.908(8년)¹ | 1.02(5년)¹ | – |
| cvd33 | 심혈관질환 | CVD | XGBoost AFT | 0.775 | 1.13 | – |
| cbv33 | 뇌혈관질환 | Stroke | XGBoost AFT | 0.708 | 1.10 | – |
| esr33 | 말기콩팥병 | CRF | XGBoost AFT | 0.948 | 1.37 | D-14 O/E 기준 밖, 내부 시험 보정 판정 불가(사건 부족) |
| gca33 | 위암 | Stomach | XGBoost AFT | 0.702 | 1.09 | – |
| lca33 | 간암 | Liver | XGBoost AFT, 간장질환 입력 | 0.843 | 1.11 | D-03 내부 시험 5년 보정 |
| luc33 | 폐암 | Lung | XGBoost AFT + 흡연량(갑년) | 0.714 | 1.00 | D-04 내부 시험 5년 보정 기울기 |
| pac33 | 췌장암 | Pancreas | XGBoost AFT | 0.719 | 1.00 | D-05 내부 시험 10년 보정 |
| pro33 | 전립선암(남) | Prostate | XGBoost AFT | 0.793 | 0.99 | D-06 내부 시험 10년 보정 |
| crc33 | 대장암 | Colorectal | 나이·성 Cox + 문헌 상대위험 | 0.67 | 국가 목표 수준 | D-08 판별력·보정 기준 밖 |
| brc33 | 유방암(여) | Breast | 나이 Cox + 문헌 상대위험 | 0.573 | 1.00 | D-09 판별력 기준 밖 |
| thy33 | 갑상선암 | Thyroid | 나이·성·갑상선질환 Cox | 0.607 | – | D-11 판별력 기준 밖 |
| utc33 | 자궁암(여) | Uterus | 나이 Cox + 문헌 상대위험 | 0.527 | 1.02 | D-10 판별력·보정 기준 밖 |
| dmn33 | 치매 (데모) | Dementia³ | XGBoost AFT | 0.903 | 0.98 | D-15 내부 시험 1·5년 보정 기울기 |
| copd33 | COPD (데모) | COPD³ | XGBoost AFT | 0.750 | 1.07⁴ | D-17 내부 시험 1년 O/E, D-20 선택 입력 빈칸 변화 |
| frac33 | 골다공증성 골절 (데모) | Fracture³ | XGBoost AFT | 0.783 | 0.98 | D-19 내부 시험 5년 보정 기울기 |
| ha33 | 건강나이·기대수명 | HEALTH_AGE 등 | XGBoost 회귀 + 생명표 | – | – | – |

C·O/E 는 사람 단위 5겹 교차검증 10년 값입니다. ¹대사질환 4개는 내부 시험(20%)의 8년 C, 5년 O/E입니다.  시험셋에서 10년 이상 추적된 사람이 적어 10년 대신 8년 C를, 보정은 평균 추적 기간(4–5년)에 맞는 5년 O/E를 썼습니다. 10년 이상 추적이 가능한 자료는 혈압·허리 정형값이 없어 함께 쓰지 않았습니다. 혈압은 고혈압의 핵심 입력이자 결과 정의(측정 140/90 2회)여서, 대치값으로는 발병을 정확히 잡을 수 없었습니다. ² 비만은 항목정의서 출력에 없어 `anyfit_api.py` 출력에는 나오지 않고 엔진(`deploy_api.py`)과 시험 페이지에만 있습니다. ³ 항목정의서에 출력 이름이 없어 가칭입니다. COPD·골절은 국가 통계를 하한으로 맞췄습니다(COPD 국민건강영양조사 폐기능, 골절 건강보험 청구 고관절 골절). ⁴ 병원 관측 기준입니다. 배포 출력은 국가 하한(국건영 폐기능)에 맞춰 병원 관측의 약 2배입니다.

**배포 기준 예외**: 위 15개 모델은 배포 기준 일부가 기준 밖이라 예외 승인(서명)을 받아 배포합니다. 대장·유방·갑상선·자궁암은 나이·성별 이상의 개인 차이를 자료로 잡기 어렵습니다(판별력 0.53–0.67).

## 폴더

| 경로 | 내용 |
|---|---|
| `deploy/<코드>/` | 모델 묶음: `model.json`(XGBoost), `calibration.json`(보정표), `meta.json`(입력 변수·대치·국가 목표 이동·문진 모듈), `reference.json`(기준 인구 집계: 검진 코호트의 성·5세 연령대별 위험 분포, 30명 이상 칸만), `fill.json`(빈칸 채움표: 성·연령대 중앙값·회귀식, 항목별 채움 방법과 영향도), `MANIFEST.json`(sha256). Cox 모델은 `meta.json` 에 계수가 있다 |
| `deploy/ha33/` | 건강나이 `health_age.json`·`meta.json` |
| `api/` | Python 엔진 `deploy_api.py`, 항목정의서 형식 `anyfit_api.py`, 건강나이 `health_age_api.py` |
| `web/risk_test.html` | 시험 페이지(모델 JSON 전부 포함, 서버·인터넷 없이 열림) |
| `web/src/` | 시험 페이지 원본: `engine.js`(Python API 를 옮긴 계산 엔진), `template.html` |
| `web/build_html.py` | `deploy/` 로 `risk_test.html` 다시 만들기 |
| `tests/` | 가상 입력 104건 `cases.json`(빈칸·입력 오류 사례, 임신/수유·갑상선질환 가칭 필드 4건 포함), Python API 결과 `expected_python.json`, 점검 `test_python.py`·`test_engine.js` |
| `examples/` | 입력·출력 예시 1건 |
| `INPUT_API.md` | 분석엔진 입력 API: 정의서 입력 코드별 범위·빈칸 처리, 정의서에 없는 추가 입력(가칭)·추가 출력, 예측 대상 아님 |

## 실행

Python(3.12 에서 확인):
```bash
pip install -r requirements.txt
cd api && DEPLOY_DIR=../deploy python anyfit_api.py ../examples/input_example.json out.json
```
```python
import sys; sys.path.insert(0, 'api')
from anyfit_api import predict_anyfit
predict_anyfit([{'AGE': 52, 'SEX': 1, 'BMI': 24.1, 'BP_HIGH': 128, ...}], deploy_dir='deploy')
from deploy_api import Model
Model('htn33', 'deploy').predict({'age': 52, 'sex': 'M', 'sbp': 128, ...})   # 엔진(내부 변수명)
```

시험 페이지: `web/risk_test.html` 을 브라우저로 엽니다. 입력 양식이나 JSON(1건 또는 배열)을 넣고 "계산"을 누르면 질환별 카드와 항목정의서 형식 JSON 출력이 나옵니다. 모델을 바꾸면 `python web/build_html.py` 로 다시 만듭니다.

점검:
```bash
python tests/test_python.py     # Python API = 기대값
node tests/test_engine.js       # 시험 페이지 엔진 = Python API
```
`test_engine.js` 실패 0(일부 값은 마지막 자리 1 차이 — XGBoost float32 누적 순서).

## 입력(항목정의서 코드)

| 코드 | 내용 | 비고 |
|---|---|---|
| AGE, SEX | 나이(1900 이상이면 출생연도로 보고 YEAR_MM_DD 연도로 환산), 성별 1 남·2 여 | 유일한 필수 — 빈칸이면 "입력 오류" |
| BMI(또는 resWeight·resHeight), WAIST, BP_HIGH, BP_LWST, BLDS, TOT_CHOLE, TRIGLYCERIDE, HDL_CHOLE, LDL_CHOLE, HMG, CREATININE, SGOT_AST, SGPT_ALT, GAMMA_GTP | 검진 수치 | 999999 등 범위 밖 값은 빈칸 |
| OLIG_PROTE_CD | 요단백 1–6 또는 "음성·약양성·양성(+1)…" | |
| HCHK_APOP·HDISE·HPRTS·DIABML·HPLPDM·PHSS·ETCDSE_PMH_YN | 과거력(뇌졸중·심장질환·고혈압·당뇨·이상지질혈증·폐결핵·기타) | 빈칸 = 없음 |
| FMLY_HPRTS·DIABML_PATIEN_YN | 고혈압·당뇨 가족력 | |
| SMOKING, DRINKING | 흡연 1–5(2·3 과거, 4·5 현재), 음주(≥2 = 음주) | |
| (추가) HCHK_LIVER_PMH_YN, HCHK_CANCER_PMH_YN | 간장질환(간암 입력 — 바이러스 간염·간 질환 진단 전체로 학습), 암 과거력 | 간암 입력(간장질환). 암 과거력은 받지만 계산에 쓰지 않음. 빈칸 = 없음 |
| (가칭) PREG_LACT_HIST_YN | 임신/수유 과거력: 1 = 경험 있음, 0 = 경험 없음 → 엔진 `hx_nulliparous` = 1 − 값(경험 없음이면 유방암 무출산 상대위험 1.15배) | 빈칸 = 경험 없음. 정의서에 엔진 코드가 없어 붙인 가칭 — 앱 항목 코드는 삼성 확인 |
| (가칭) HCHK_THYROID_PMH_YN | 갑상선질환 과거력(양성종양·결절·기능항진·저하 등): 1 = 있음(갑상선암 상대위험 1.92배), 0 = 없음 → 엔진 `hx_thyroid` | 빈칸 = 없음. 정의서 사용자 입력 항목에 엔진 코드가 없어 붙인 가칭 — 앱 항목 코드는 삼성 확인 |
| (추가) SMOKING_YEARS(_CD), SMOKING_PER_DAY(_CD), SMOKING_STATUS | 흡연 기간(년 또는 정의서 문진 5구간 코드 1–5), 하루 개비(개비 또는 4구간 코드 1–4) → 갑년. 흡연 상태는 SMOKING 에서(SMOKING_STATUS 1/2/3 이 있으면 그쪽 우선) | 선택 입력. 정의서의 흡연 기간·흡연량 화면 항목(엔진 코드 없음)에 붙인 이름. 폐암이 갑년을 쓰고, 없으면 흡연 상태만으로 계산 |
| (추가) DRINKING_DAYS_WEEK, DRINKING_AMOUNT + DRINKING_TYPE 또는 DRINK_SOJU·BEER·MAKGEOLLI·WINE·LIQUOR | 주 음주일, 1회 잔 → 주 알코올 g | 출력에만 남김 |

**빈칸 처리**: 필수 입력 확인은 없습니다. 나이·성별 말고는 빈칸이어도 채워서 위험을 냅니다.
- 나이·성별 빈칸(나이 범위 1–110 밖 포함) = `입력 오류`("나이·성별 없음(스크래핑 확인 필요)"), 위험 NULL.
- 검사값(혈압·BMI·공복혈당·총콜레스테롤·중성지방·HDL·혈색소·크레아티닌·AST·ALT): `fill.json` 의 성·연령대 중앙값 → 항목별로 정한 경우 다른 검사값으로 회귀 예측. 허리·LDL·GGT·요단백은 기존 회귀·최빈값, 과거력은 없음, 문진은 문진 모듈 평균.
- 채운 항목은 `IMPUTED_INPUTS`, 그 영향도(실제 검진자 표본에서 그 항목을 비웠을 때 10년 위험이 바뀐 정도) 중 가장 큰 값은 `INPUT_IMPACT`(상: 기준 초과 ≥5% 또는 상대 20% 초과 ≥20%, 중: ≥1% 또는 ≥5%, 하: 그 밖). 핵심 지표(고혈압의 혈압, 당뇨의 공복혈당, 비만의 BMI, 이상지질의 지질, 폐암·위암·COPD 의 흡연)가 빠지면 "상".

**예측 대상 아님**: 19세 미만(모든 질환·건강나이)과 성별 한정 암의 다른 성(전립선암은 여성, 유방암·자궁암은 남성)만 "예측 대상 아님"이고, 위험값은 NULL 입니다.

## 출력(질환별)

| 항목 | 값 |
|---|---|
| STATUS · REASON · MODEL_VERSION | 정상 / 예측 대상 아님 / 입력 오류, 사유, 모델 해시(sha256 앞 16자리) |
| IMPUTED_INPUTS · INPUT_IMPACT | 채워서 계산한 입력(정의서 코드 목록, 없으면 `[]`), 그 영향도 상·중·하(없으면 null). 입력 코드·빈칸 처리 전체는 `INPUT_API.md` |
| PROBABILITY · PROBABILITY_BY_YEAR | 10년 위험(0–1), 1~10년차 위험 |
| STATISTIC_DIFF · PROBABILITY_RANK · RISK_INDEX | 같은 성·5세 연령대 평균과의 차, 백분위(0–100), 백분위 5등분(1–5) |
| STATISTIC_RATIO · DS_AGE | 같은 성·연령대 정상군 평균 대비 배수, 정상군 평균 위험이 이 사람 위험과 같아지는 나이 |
| CONTROLLABLE_FACTOR · UNCONTROLLABLE_FACTOR | 권장값으로 바꾸거나(조절 가능) 가족력·과거력이 없었다면(조절 불가) 10년 위험이 줄어드는 비율(%) |

건강나이: HEALTH_AGE, LIFE_EXPECTANCY(건강나이의 남은 기대여명, 2024 완전생명표), LIFE_SPAN(기대수명 = 건강나이 + 건강나이의 남은 기대여명. 건강나이가 높을수록 길어집니다), HEALTH_AGE_INFO(상태·채운 항목 IMPUTED·영향도 INPUT_IMPACT·같은 성·나이 평균 기대수명). 건강나이도 나이·성별 말고는 빈칸을 채워 계산하고(`deploy/ha33/fill.json`), 나이·성별 빈칸은 "입력 오류"입니다. 영향도는 그 항목을 비웠을 때 건강나이가 2세 이상 바뀌는 사람 비율로 정합니다(상 ≥5%, 중 ≥1% 또는 1세 이상 ≥10%). 공복혈당·허리·수축기혈압·혈색소·AST 가 "상"입니다. 비교 항목(STATISTIC_*·PROBABILITY_RANK·RISK_INDEX·DS_AGE)은 19개 질환 모두 기준 인구 집계로 계산합니다. DS_AGE 는 19–90 으로 자르므로, 위험이 19세 정상군 평균보다 낮으면 19 입니다.

## 계산 방식(요약)
1. 입력 표준화: 범위 밖 값 빈칸, 흡연·음주 상세 → 갑년·주 알코올 g.
2. 나이·성별 확인(빈칸이면 입력 오류) → 대상 여부.
3. 빈칸 채움: 검사값 = `fill.json`(성·연령대 중앙값 → 회귀), 허리·LDL·GGT 는 선형 회귀(LDL 은 Friedewald 먼저), 요단백은 성·연령대 최빈값, 과거력 빈칸은 없음, 문진 빈칸은 평균.
4. 위험: XGBoost AFT(정규분포) → 보정표(I-spline) → 국가 목표 이동(성·연령별 cloglog 이동) → 기간 단조. 흡연·음주·가족력은 문진 모듈(로그 시간 이동, 위험 증가 방향만)로 더한다. Cox 모델은 기저 누적위험 × exp(선형 예측자).
5. 1~10년차는 1·3·5·8·10년 값 사이를 cloglog × log(년)에서 보간.

## 알려진 점
- `anyfit_api.py` 를 CLI 로 돌리면 건강나이 결과가 없는 사람(19세 미만·입력 오류)의 HEALTH_AGE·LIFE_EXPECTANCY·LIFE_SPAN·AVG_LIFE_SPAN 이 JSON 표준이 아닌 `NaN` 으로 나옵니다. 시험 페이지는 `null` 로 냅니다.
- LDL 이 빈칸이면 Friedewald(총콜레스테롤 − HDL − 중성지방/5)로 계산하는데, 이 값은 `IMPUTED_INPUTS` 에 나오지 않습니다(지질도 빈칸이면 총콜레스테롤·중성지방·HDL 이 표시됩니다).
- `anyfit_api.py` 에 여러 건을 한 번에 넣으면, DRINKING_AMOUNT 만 있고 DRINKING_TYPE 이 없는 건에 "주종 모름" 표시가 붙을 수 있습니다(다른 건에 DRINKING_TYPE 이 있을 때). 계산값은 같습니다.

## 라이선스
정하지 않음(공개 전 결정 필요).
