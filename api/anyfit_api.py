# 애니핏 건강위험분석 API 항목정의서(삼성요청사항/애니핏_건강위험분석_API항목정의서.xlsx) 형식 입출력 — deploy_api.Model 위에 얹는 층
# usage(모듈): from anyfit_api import predict_anyfit; predict_anyfit([{'AGE': 60, 'SEX': 2, 'BMI': 19.53, 'WAIST': 69, 'BP_HIGH': 108, ...}])
#        → [{'input': {...}, 'DM': {...}, 'Hypertension': {...}, 'Hyperlipidemia': {...}, 'Stomach': {...}}]
# usage(CLI): python3 anyfit_api.py 입력.json [출력.json]
# 정의서 시트 "검진기반-input"·"문진기반-input" 의 엔진 입력 코드를 받고, "output(문진검진 동일)" 의 질병별 항목을 낸다. 지금 개발된 모델만 낸다(비만은 정의서 출력에 없음).
# 정의서에 값 정의가 없는 항목은 아래 가정으로 계산한다(삼성·온택트와 확정 필요):
#   PROBABILITY = 10년 위험(0–1). PROBABILITY_BY_YEAR = 1~10년차(그래프). STATISTIC_DIFF = 위험 − 같은 성·5세 연령대 평균.
#   PROBABILITY_RANK = 같은 성·5세 연령대 안 백분위(0–100, 클수록 위험). RISK_INDEX = 백분위 5등분(1–5).
#   STATISTIC_RATIO = 위험 / 같은 성·5세 연령대 정상군 평균. DS_AGE = 정상군 평균 위험이 이 사람 위험과 같아지는 나이(19–90).
#   기준 인구 = 검진 자료(deploy/<질환>/reference.json, 집계만).
#   CONTROLLABLE_FACTOR.CHANGE_RISK_RATIO = 그 인자를 권장값으로 바꿀 때 10년 위험이 줄어드는 비율(%). 입력했고 권장값보다 나쁜 인자만, 큰 순서.
#   UNCONTROLLABLE_FACTOR.CHANGE_RISK_RATIO = 가족력·과거력이 없었다면 줄어드는 비율(%). 나이·성별은 넣지 않는다.
import sys, os, json, datetime
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from deploy_api import Model, DEPLOY, RANGE

DIS_OUT = {'cvd33': 'CVD', 'cbv33': 'Stroke', 'esr33': 'CRF', 'dm33': 'DM', 'htn33': 'Hypertension', 'dlp33': 'Hyperlipidemia', 'gca33': 'Stomach', 'lca33': 'Liver', 'luc33': 'Lung', 'crc33': 'Colorectal', 'pac33': 'Pancreas', 'pro33': 'Prostate', 'brc33': 'Breast', 'thy33': 'Thyroid', 'utc33': 'Uterus',
           'copd33': 'COPD', 'frac33': 'Fracture', 'dmn33': 'Dementia'}   # 정의서 출력 질병명. COPD·골절·치매는 정의서에 출력명이 없어 가칭(삼성 확인)
NUM = {'WAIST': 'waist', 'BP_HIGH': 'sbp', 'BP_LWST': 'dbp', 'BLDS': 'fpg', 'TOT_CHOLE': 'tchol', 'TRIGLYCERIDE': 'tg', 'HDL_CHOLE': 'hdl', 'LDL_CHOLE': 'ldl',
       'HMG': 'hb', 'CREATININE': 'creatinine', 'SGOT_AST': 'ast', 'SGPT_ALT': 'alt', 'GAMMA_GTP': 'ggt', 'BMI': 'bmi'}
HCHK = {'HCHK_APOP_PMH_YN': 'hx_cerebrovascular', 'HCHK_HDISE_PMH_YN': 'hx_cvd', 'HCHK_HPRTS_PMH_YN': 'hx_htn', 'HCHK_DIABML_PMH_YN': 'hx_dm',
        'HCHK_HPLPDM_PMH_YN': 'hx_dyslipidemia', 'HCHK_PHSS_PMH_YN': 'hx_tb', 'HCHK_ETCDSE_PMH_YN': 'hx_others',
        'HCHK_LIVER_PMH_YN': 'hx_liver'}   # 간장질환(바이러스 간염 B15–B19·간 질환 K70–K77 전체) — 정의서에는 화면 항목만 있고 엔진 코드가 없다. 간암 입력이라 제안 이름으로 받는다(빈칸 = 없음)
FMLY = {'FMLY_HPRTS_PATIEN_YN': 'fh_htn', 'FMLY_DIABML_PATIEN_YN': 'fh_dm'}   # 뇌혈관·심혈관·기타 가족력은 지금 모델에 없다
EXTRA = {'HCHK_CANCER_PMH_YN': 'hx_cancer'}   # 정의서에 없는 선택 항목. 암 과거력은 기타 과거력 채움용(암 예측 대상에서 빼지 않음, 정의서에서 "기타 질환(암포함)"에 묶여 있다). 임신(PREGNANT_YN)은 API 입력에 없어 받지 않는다
EXTRA['HCHK_THYROID_PMH_YN'] = 'hx_thyroid'   # 가칭: 갑상선질환 과거력(1 있음·0 없음, 갑상선암 1.92배). 정의서 사용자 입력 항목에 엔진 코드가 없다 — 삼성 확인. 빈칸 = 평균
PREG_LACT = 'PREG_LACT_HIST_YN'   # 가칭: 임신/수유 과거력(1 경험 있음·0 없음) → hx_nulliparous = 1 − 값(유방암 무출산 1.15배). 엔진 코드 없음 — 삼성 확인. 빈칸 = 경험 없음
# 엔진이 채운 항목(deploy_api imputed) → 정의서 입력 코드. 필수 입력 확인 없이 채워서 계산하고, 채운 항목·영향도를 출력에 남긴다
IMP_CODE = {**{v: k for k, v in NUM.items()}, 'urine_protein': 'OLIG_PROTE_CD', 'fh_htn': 'FMLY_HPRTS_PATIEN_YN', 'fh_dm': 'FMLY_DIABML_PATIEN_YN', 'smoke': 'SMOKING', 'alc_cur': 'DRINKING'}
UPRO = {'-': 1, '음성': 1, '음성(-)': 1, '약양성': 2, '±': 2, '+/-': 2, '+1': 3, '1+': 3, '양성(+1)': 3, '+2': 4, '2+': 4, '양성(+2)': 4, '+3': 5, '3+': 5, '양성(+3)': 5, '+4': 6, '4+': 6, '양성(+4)': 6}
SMOKING_SCALE = os.environ.get('ANYFIT_SMOKING_SCALE', '5')   # 정의서 검진기반: 1 비흡연·2/3 과거·4/5 현재. 문진기반 시트: 1 비흡연·2 과거·3 현재 → '3'
# 조절 가능 인자: (내부 변수, 정의서 이름, 권장값(여, 남), 방향). 권장값은 국내 검진 정상 기준
CTRL = [('sbp', 'BP_HIGH', (120, 120), 'down'), ('dbp', 'BP_LWST', (80, 80), 'down'), ('bmi', 'BMI', (23, 23), 'down'), ('waist', 'WAIST', (85, 90), 'down'),
        ('fpg', 'BLDS', (100, 100), 'down'), ('tchol', 'TOT_CHOLE', (200, 200), 'down'), ('tg', 'TRIGLYCERIDE', (150, 150), 'down'), ('ldl', 'LDL_CHOLE', (130, 130), 'down'),
        ('hdl', 'HDL_CHOLE', (50, 40), 'up'), ('ast', 'SGOT_AST', (40, 40), 'down'), ('alt', 'SGPT_ALT', (40, 40), 'down'), ('ggt', 'GAMMA_GTP', (35, 63), 'down'),
        ('smoke_current', 'SMOKING', None, 'quit'), ('alc_cur', 'DRINKING', None, 'stop')]
UNCTRL = [(v, k) for k, v in FMLY.items()] + [(v, k) for k, v in HCHK.items()]
# 질환별로 보여 줄 인자(문헌 근거가 있는 것만, 없으면 전부). 위험 계산은 그대로이고 인자 목록만 거른다
#   폐암: 조절 가능 = 흡연만(금연 시 위험 감소가 확립). 중성지방·GGT·BMI·혈당·혈압·지질·간수치는 인과 근거가 없거나(표지자) 방향이 반대·불일치
#         조절 불가 = 결핵 과거력만(메타분석 RR 1.5–2.2, 흡연과 독립)
#   췌장암: 조절 가능 = 흡연·BMI·허리·공복혈당(흡연 IARC 1군, 체지방 WCRF 확립, 고혈당·당뇨 RR 1.5–2). 음주(고음주만 위험, 입력은 여부)·지질·혈압·간수치는 제외
#         조절 불가 = 당뇨 과거력만. 흡연은 지금 모델(문진 모듈 β=0)에서 효과가 없어 목록에 나오지 않는다
#   전립선암: 입력에 있는 인자 중 전체 발생을 높인다고 확립된 것이 없다(비만은 진행성·사망 암만, 흡연·당뇨는 발생과 역연관 — 검출 편향)
#         → 조절 가능·불가능 모두 보이지 않는다(빈 목록). 나이·가족력(입력 없음)이 주 위험요인
CTRL_ALLOW = {'luc33': {'SMOKING'}, 'pac33': {'SMOKING', 'BMI', 'WAIST', 'BLDS'}, 'pro33': set(), 'crc33': {'SMOKING', 'DRINKING', 'BMI', 'BLDS'}}
UNCTRL_ALLOW = {'luc33': {'HCHK_PHSS_PMH_YN'}, 'pac33': {'HCHK_DIABML_PMH_YN'}, 'pro33': set(), 'crc33': {'HCHK_DIABML_PMH_YN'}}   # 대장암: 문헌 고정 상대위험을 넣은 인자만
# 흡연·음주 상세(자체 입력 API — 정의서 화면 항목, 엔진 코드가 없어 제안 이름). 있으면 SMOKING·DRINKING 코드보다 먼저 쓴다
#   SMOKING_STATUS 1 비흡연·2 과거·3 현재 | SMOKING_YEARS 년(숫자) 또는 SMOKING_YEARS_CD 1 <5·2 5–9·3 10–19·4 20–29·5 ≥30년
#   SMOKING_PER_DAY 개비(숫자) 또는 SMOKING_PER_DAY_CD 1 <반 갑·2 반~한 갑·3 한~두 갑·4 ≥두 갑
#   DRINKING_DAYS_WEEK 주 음주일(0–7) | DRINKING_AMOUNT 1회 잔 + DRINKING_TYPE 주종, 또는 주종별 잔 DRINK_SOJU·DRINK_BEER·DRINK_MAKGEOLLI·DRINK_WINE·DRINK_LIQUOR
#   → pack_years = 년 × 개비/20, alc_g_week = 주 음주일 × Σ(잔 × 주종 1잔 알코올 g). 갑년은 폐암(luc33)이 쓰고, 나머지는 smoke_former·smoke_current·alc_cur 만 쓴다.
#     정의서에는 흡연 기간(검진 ___년 / 문진 5구간)·흡연량(검진 ___개비 / 문진 4구간) 화면 항목이 있고 엔진 코드가 없다 — 위 이름은 제안, 선택 입력
YEARS_CD = {1: 2.5, 2: 7.0, 3: 15.0, 4: 25.0, 5: 35.0}; PERDAY_CD = {1: 5.0, 2: 15.0, 3: 30.0, 4: 45.0}   # 구간 가운데값(≥ 구간은 +5년·+5개비)
DRINK_G = {'소주': 6.6, '맥주': 7.1, '막걸리': 9.5, '와인': 14.2, '양주': 12.6}   # 1잔 알코올 g(소주 50ml·16.5%, 맥주 200ml·4.5%, 막걸리 200ml·6%, 와인 150ml·12%, 양주 40ml·40%, ×0.79)
DRINK_COL = {'DRINK_SOJU': '소주', 'DRINK_BEER': '맥주', 'DRINK_MAKGEOLLI': '막걸리', 'DRINK_WINE': '와인', 'DRINK_LIQUOR': '양주'}
DRINK_TYPE_CD = {1: '소주', 2: '맥주', 3: '막걸리', 4: '와인', 5: '양주', 'soju': '소주', 'beer': '맥주', 'makgeolli': '막걸리', 'wine': '와인', 'liquor': '양주'}

def lifestyle(A):
    """흡연·음주 상세 → 표준화(상태·갑년·주 알코올 g)와 입력 점검 표시(input_flags). 모순 입력은 상태를 따르고 표시만 남긴다"""
    n = len(A); num = lambda c: pd.to_numeric(A[c], errors='coerce') if c in A else pd.Series(np.nan, index=A.index)
    L = pd.DataFrame(index=A.index); flags = [[] for _ in range(n)]
    def flag(m, f):
        for i in np.where(np.asarray(m, bool))[0]: flags[i].append(f)
    st = num('SMOKING_STATUS'); flag(st.notna() & ~st.isin([1, 2, 3]), 'SMOKING_STATUS 범위 밖'); st = st.where(st.isin([1, 2, 3]))
    # 정의서 엔진 코드는 SMOKING 하나뿐이라 SMOKING_STATUS 없이 기간·양만 올 수 있다 → 상태는 SMOKING 에서(5단계 2·3 과거, 4·5 현재)
    s = num('SMOKING'); s_st = s.map({1: 1, 2: 2, 3: 2, 4: 3, 5: 3}) if SMOKING_SCALE == '5' else s.where(s.isin([1, 2, 3]))
    yrs = num('SMOKING_YEARS').fillna(num('SMOKING_YEARS_CD').map(YEARS_CD)); flag((yrs < 0) | (yrs > 80), 'SMOKING_YEARS 범위 밖(0–80)'); yrs = yrs.where(yrs.between(0, 80))
    cpd = num('SMOKING_PER_DAY').fillna(num('SMOKING_PER_DAY_CD').map(PERDAY_CD)); flag((cpd < 0) | (cpd > 100), 'SMOKING_PER_DAY 범위 밖(0–100)'); cpd = cpd.where(cpd.between(0, 100))
    flag(st.isin([2, 3]) & (yrs.isna() | cpd.isna()), '흡연자 기간·양 빈칸(갑년 없음)')   # 상세 상태를 준 경우만(SMOKING 만 온 흡연자는 기간·양이 선택 입력)
    flag(st.isna() & s_st.isin([2, 3]) & (yrs.isna() ^ cpd.isna()), '흡연 기간·양 중 하나만 입력(갑년 없음)')
    st = st.fillna(s_st)
    flag((st == 1) & ((yrs > 0) | (cpd > 0)), '비흡연인데 흡연 기간·양 입력(무시)')
    L['smoke_status'] = st
    L['pack_years'] = np.where(st == 1, 0.0, np.where(st.isin([2, 3]), yrs * cpd / 20, np.nan))
    dd = num('DRINKING_DAYS_WEEK'); flag((dd < 0) | (dd > 7), 'DRINKING_DAYS_WEEK 범위 밖(0–7)'); dd = dd.where(dd.between(0, 7))
    per = pd.Series(0.0, index=A.index); anyc = pd.Series(False, index=A.index)
    for c, t in DRINK_COL.items():
        v = num(c); per = per + v.fillna(0).clip(0, 50) * DRINK_G[t]; anyc = anyc | v.notna()
    if 'DRINKING_AMOUNT' in A:
        tp = A['DRINKING_TYPE'].map(lambda x: DRINK_TYPE_CD.get(x, DRINK_TYPE_CD.get(str(x).strip().lower(), str(x).strip()))) if 'DRINKING_TYPE' in A else pd.Series('소주', index=A.index)
        g1 = tp.map(DRINK_G); flag(num('DRINKING_AMOUNT').notna() & g1.isna(), '주종 모름(소주로 계산)')
        amt = num('DRINKING_AMOUNT'); m = amt.notna() & ~anyc
        per = per.where(~m, amt.clip(0, 50) * g1.fillna(DRINK_G['소주'])); anyc = anyc | amt.notna()
    per = per.where(anyc)
    flag((dd == 0) & (per > 0), '음주 0일인데 1회 음주량 입력(무시)')
    L['alc_days_week'] = dd
    L['alc_g_week'] = np.where(dd == 0, 0.0, dd * per)
    L['input_flags'] = flags
    return L

def from_anyfit(df):
    """정의서 입력 코드 → deploy_api 입력. 999999(삼성 결측 기본값)는 deploy_api 범위 점검에서 빈칸이 된다"""
    A = pd.DataFrame(df).reset_index(drop=True); X = pd.DataFrame(index=A.index); num = lambda c: pd.to_numeric(A[c], errors='coerce') if c in A else pd.Series(np.nan, index=A.index)
    age = num('AGE'); yr = pd.to_numeric(A['YEAR_MM_DD'].astype(str).str[:4], errors='coerce') if 'YEAR_MM_DD' in A else pd.Series(np.nan, index=A.index)
    X['age_at_index'] = np.where(age >= 1900, yr.fillna(datetime.date.today().year) - age, age)   # 정의서 "연도로 전달" — 출생연도로 오면 나이로 바꾼다
    X['sex'] = num('SEX').map({1: 1.0, 2: 0.0})
    for k, v in NUM.items(): X[v] = num(k)
    if 'resWeight' in A and 'resHeight' in A: X['bmi'] = X['bmi'].fillna(num('resWeight') / (num('resHeight') / 100) ** 2)
    if 'OLIG_PROTE_CD' in A:
        u = A['OLIG_PROTE_CD']; X['urine_protein'] = pd.to_numeric(u, errors='coerce').fillna(u.astype(str).str.strip().map(UPRO))
    for src in [HCHK, FMLY, EXTRA]:
        for k, v in src.items(): X[v] = num(k)
    pl = num(PREG_LACT); X['hx_nulliparous'] = np.where(pl.isin([0, 1]), (pl == 0).astype(float), np.nan)
    s = num('SMOKING')
    former = s.isin([2, 3]) if SMOKING_SCALE == '5' else s.eq(2); current = s.isin([4, 5]) if SMOKING_SCALE == '5' else s.eq(3)
    X['smoke_former'] = np.where(s.isna(), np.nan, former.astype(float)); X['smoke_current'] = np.where(s.isna(), np.nan, current.astype(float))
    d = num('DRINKING'); X['alc_cur'] = np.where(d.isna(), np.nan, (d >= 2).astype(float))
    L = lifestyle(A)   # 상세 입력이 있으면 그쪽이 우선(SMOKING_STATUS → 흡연 상태, DRINKING_DAYS_WEEK → 음주 여부)
    st = L.smoke_status.values
    X['smoke_former'] = np.where(np.isnan(st), X.smoke_former, (st == 2).astype(float)); X['smoke_current'] = np.where(np.isnan(st), X.smoke_current, (st == 3).astype(float))
    X['alc_cur'] = np.where(L.alc_days_week.isna(), X.alc_cur, (L.alc_days_week > 0).astype(float))
    for k in ['pack_years', 'alc_g_week', 'alc_days_week', 'input_flags']: X[k] = L[k].values if k != 'input_flags' else L[k]
    for k, (lo, hi) in RANGE.items():   # 999999 등 범위 밖 = 빈칸(deploy_api 와 같은 기준). 그래야 인자 순위에 결측 기본값이 안 나온다
        if k in X and k != 'age_at_index': X.loc[(X[k] < lo) | (X[k] > hi), k] = np.nan
    return X

class Reference:
    """기준 인구 집계(reference.json): 성·5세 연령대별 평균·백분위·정상군 평균"""
    def __init__(self, path):
        self.R = json.load(open(path, encoding='utf-8')) if os.path.exists(path) else None
    def _cell(self, s, a):
        b = 80 if a >= 80 else (19 if a < 25 else int(a // 5 * 5))
        return self.R['cells'].get(f'{int(s)}|{b}') or self.R['by_sex'][str(int(s))]
    def stats(self, r, s, a):
        if self.R is None or pd.isna(r): return dict(STATISTIC_DIFF=None, PROBABILITY_RANK=None, STATISTIC_RATIO=None, DS_AGE=None, RISK_INDEX=None)
        c = self._cell(s, a); q = np.array(c['pct']); rank = float(np.interp(r, q, np.arange(1, 100))) if r > q[0] else 0.0
        rank = 100.0 if r > q[-1] else rank
        nm = c['normal_mean'] if c.get('normal_n', 0) >= 30 else c['mean']
        na = self.R['normal_by_age'].get(str(int(s)), [])   # 정상군 30명 이상인 연령대가 2개 미만이면 질병나이를 내지 않는다
        ds = None
        if len(na) >= 2:
            ages = np.array([x[0] for x in na], float); m = np.maximum.accumulate(np.array([x[1] for x in na], float)) + np.arange(len(na)) * 1e-9
            ds = round(float(np.clip(np.interp(r, m, ages, left=19, right=90), 19, 90)), 1)
        return dict(STATISTIC_DIFF=round(float(r - c['mean']), 4), PROBABILITY_RANK=round(rank, 2), STATISTIC_RATIO=round(float(r / nm), 3) if nm and nm > 0 else None,
                    DS_AGE=ds, RISK_INDEX=int(min(5, rank // 20 + 1)))

def _factors(M, X, base):
    """조절 가능·불가능 인자별 10년 위험 변화(%) — 그 인자만 바꿔 다시 예측"""
    feats = set(M.feats) | set(M.qm['features'] if M.qm else [])
    ctrl = [[] for _ in range(len(X))]; unc = [[] for _ in range(len(X))]
    ok = pd.notna(base)
    for var, name, rec, how in CTRL:
        if var not in feats or var not in X: continue
        if M.dis in CTRL_ALLOW and name not in CTRL_ALLOW[M.dis]: continue
        v = X[var].values.astype(float); X2 = X.copy()
        if how in ('down', 'up'):
            tgt = np.where(X.sex.values == 1, rec[1], rec[0]); bad = (v > tgt) if how == 'down' else (v < tgt)
            X2[var] = np.where(bad, tgt, v)
        elif how == 'quit': bad = v == 1; X2['smoke_current'] = np.where(bad, 0.0, v); X2['smoke_former'] = np.where(bad, 1.0, X['smoke_former'].values)
        else: bad = v == 1; X2[var] = np.where(bad, 0.0, v)
        bad = bad & ok & ~np.isnan(v)
        if not bad.any(): continue
        r2 = M.predict_df(X2)['risk_10y'].values
        for i in np.where(bad)[0]:
            ch = (base[i] - r2[i]) / base[i] * 100
            if ch > 0: ctrl[i].append(dict(FACTOR_NAME=name, CHANGE_RISK_RATIO=round(float(ch), 2), VALUE_CURRENT=None, VALUE_RECOMMENDED=None if rec is None else float(tgt[i]), _var=var))
    for var, name in UNCTRL:
        if var not in feats or var not in X: continue
        if M.dis in UNCTRL_ALLOW and name not in UNCTRL_ALLOW[M.dis]: continue
        v = X[var].values.astype(float); bad = (v == 1) & ok
        if not bad.any(): continue
        r2 = M.predict_df(X.assign(**{var: np.where(bad, 0.0, v)}))['risk_10y'].values
        for i in np.where(bad)[0]:
            ch = (base[i] - r2[i]) / base[i] * 100
            if ch > 0: unc[i].append(dict(FACTOR_NAME=name, CHANGE_RISK_RATIO=round(float(ch), 2), VALUE_CURRENT=1, _var=var))
    for L in ctrl + unc: L.sort(key=lambda d: -d['CHANGE_RISK_RATIO'])
    return ctrl, unc

def predict_anyfit(records, diseases=None, deploy_dir=None):
    A = pd.DataFrame(records).reset_index(drop=True); X = from_anyfit(A)
    dises = diseases or [d for d in DIS_OUT if os.path.exists(os.path.join(deploy_dir or DEPLOY, d, 'meta.json'))]
    nz = lambda v: None if v is None or pd.isna(v) else round(float(v), 1)
    out = [dict(input=dict(age=nz(a), sex=None if pd.isna(s) else int(s), smoke_former=nz(sf), smoke_current=nz(sc), pack_years=nz(py), alc_cur=nz(ac), alc_days_week=nz(ad), alc_g_week=nz(ag), input_flags=fl))
           for a, s, sf, sc, py, ac, ad, ag, fl in zip(X.age_at_index, X.sex, X.smoke_former, X.smoke_current, X.pack_years, X.alc_cur, X.alc_days_week, X.alc_g_week, X.input_flags)]
    X = X.drop(columns=['input_flags', 'alc_days_week'])   # 갑년·주 알코올 g 는 모델 입력으로 넘긴다(쓰는 모델은 q_module derived 가 있는 질환만 — 폐암 갑년)
    for dis in dises:
        M = Model(dis, deploy_dir); ref = Reference(os.path.join(deploy_dir or DEPLOY, dis, 'reference.json'))
        O = M.predict_df(X); base = O['risk_10y'].values
        Xn = X.copy(); Xn = Xn.where(pd.notna(Xn), np.nan)
        ctrl, unc = _factors(M, Xn, base)
        for i in range(len(X)):
            r = base[i]; st = ref.stats(r, X.sex.iat[i], X.age_at_index.iat[i]) if pd.notna(r) else ref.stats(np.nan, 0, 0)
            def fmt(L):
                res = []
                for k, d in enumerate(L, 1):
                    src = next((c for c in list(NUM) + list(HCHK) + list(FMLY) + ['SMOKING', 'DRINKING'] if c == d['FACTOR_NAME']), None)
                    if src in NUM: val = None if pd.isna(X.at[i, NUM[src]]) else round(float(X.at[i, NUM[src]]), 2)   # 범위 점검 뒤 값(키·몸무게로 계산한 BMI 포함)
                    else: val = A.at[i, src] if src in A else None
                    res.append(dict(RANK=k, FACTOR_NAME=d['FACTOR_NAME'], CHANGE_RISK_RATIO=d['CHANGE_RISK_RATIO'],
                                    VALUE_CURRENT=None if val is None or pd.isna(val) else (float(val) if isinstance(val, (int, float, np.number)) else val),
                                    **({'VALUE_RECOMMENDED': d['VALUE_RECOMMENDED']} if 'VALUE_RECOMMENDED' in d else {})))
                return res
            out[i][DIS_OUT[dis]] = dict(STATUS=O.status.iat[i], REASON=O.reason.iat[i] or None, MODEL_VERSION=M.version,
                                        PROBABILITY=None if pd.isna(r) else float(r), PROBABILITY_BY_YEAR=O.risk_by_year.iat[i], **st,
                                        CONTROLLABLE_FACTOR=fmt(ctrl[i]), UNCONTROLLABLE_FACTOR=fmt(unc[i]),
                                        IMPUTED_INPUTS=[IMP_CODE.get(k, k) for k in O.imputed.iat[i]], INPUT_IMPACT=O.input_impact.iat[i] or None)
    if os.path.exists(os.path.join(deploy_dir or DEPLOY, 'ha33', 'meta.json')):   # 건강나이·기대여명 — 필드 정의는 삼성 확인 필요
        from health_age_api import HealthAge
        HA = HealthAge(deploy_dir); O = HA.predict_df(X)
        for i in range(len(X)):
            out[i].update(HEALTH_AGE=O.health_age.iat[i], LIFE_EXPECTANCY=O.life_expectancy.iat[i], LIFE_SPAN=O.life_span.iat[i],
                          HEALTH_AGE_INFO=dict(STATUS=O.status.iat[i], REASON=O.reason.iat[i] or None, IMPUTED=O.imputed.iat[i] or None, INPUT_IMPACT=O.input_impact.iat[i] or None,
                                               AVG_LIFE_SPAN=O.avg_life_span.iat[i], MODEL_VERSION=HA.version))
    return out

if __name__ == '__main__':
    recs = json.load(open(sys.argv[1], encoding='utf-8')); recs = recs if isinstance(recs, list) else [recs]
    res = predict_anyfit(recs)
    s = json.dumps(res, ensure_ascii=False, indent=1, default=lambda o: o.item() if hasattr(o, 'item') else str(o))
    if len(sys.argv) > 2: open(sys.argv[2], 'w', encoding='utf-8').write(s)
    else: print(s)
