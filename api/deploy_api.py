# 배포 예측 API — 입력 → 대상 여부 → 빈칸 채움 → 1·5·10년 위험 → TOP3 → 출력 행
# usage(모듈): from deploy_api import Model; m = Model('htn33'); m.predict({'age': 45, 'sex': 'M', 'sbp': 128, ...})
#        배치: Model('htn33').predict_df(DataFrame)  → 출력 DataFrame(행마다 하나)
# usage(CLI): python3 deploy_api.py htn33 입력.csv|입력.json [출력.csv]
# deploy/<질환>/ 의 묶음(make_deploy_bundle.py)과 빈칸 채움표 fill.json(make_fill.py)을 읽는다. 모델에는 NaN 이 들어가지 않는다.
# 필수 입력 확인을 없앴다 — 나이·성별 말고는 빈칸이어도 채워서 위험을 낸다. 나이·성별 빈칸은 스크래핑 이상으로 보고 "입력 오류"(위험 NULL).
#   채움 순서: 검사값(혈압·BMI·혈당·지질·혈색소·크레아티닌·AST·ALT) = fill.json(성·연령대 중앙값 → 항목별로 정한 방법이 회귀면 다른 검사값으로 예측)
#   → LDL Friedewald → 허리·LDL·GGT 회귀, 요단백 최빈값(meta impute) → 과거력 0 → 문진 = 문진 모듈 평균(이동 0).
#   채운 항목은 출력 imputed, 그 영향도(fill.json impact: 상·중·하) 중 가장 큰 값은 input_impact.
import sys, os, json, hashlib
import numpy as np, pandas as pd, xgboost as xgb
from scipy import stats

HERE = os.path.dirname(os.path.abspath(__file__))
DEPLOY = os.environ.get('DEPLOY_DIR', os.path.join(os.getcwd(), 'deploy'))
H = [1, 3, 5, 8, 10]; OUT_H = [1, 5, 10]
DIGITS = 4   # 위험 출력 소수 자릿수(0.0001 = 0.01%p). 드문 암의 작은 위험이 0 으로 뭉치지 않게
DIGITS_BY = {'lca33': 5, 'luc33': 5, 'pac33': 5, 'pro33': 6, 'crc33': 5, 'utc33': 6, 'esr33': 6, 'dmn33': 6}   # 간암은 4자리면 가상 입력의 8.9% 가 0.0001 로 뭉친다. 5자리 1.3%. 폐암 9.2% → 1.2%. 췌장암 8.4%. 전립선암 4자리 19.3%·5자리 7.4%(젊은 남성 위험 ≈ 0) → 6자리
GRID_X = np.round(np.arange(-14, 14.0001, 0.05), 4)
BANDS = ['19-29', '30-39', '40-49', '50-59', '60-69', '70+']
HX_OTHERS = ['hx_cancer', 'hx_gi', 'hx_liver', 'hx_gallbladder', 'hx_kidney', 'hx_bronchial', 'hx_thyroid', 'hx_bleeding',
             'hx_hypercalcemia', 'hx_hyperkalemia', 'hx_lactose_intol', 'hx_hyperestrogenism', 'hx_pregnant']
QF = ['fh_htn', 'fh_dm', 'smoke_former', 'smoke_current', 'alc_cur']
NONMOD = {'age_at_index', 'sex', 'fh_htn', 'fh_dm'}   # TOP3 에서 뺀다(조절 불가)
FORBIDDEN = {'psa', 'tsh', 'hba1c', 'afp', 'cea', 'ca19_9', 'ca125'}   # 검사율 편향 항목(F13) — 입력에 있으면 형식 점검 실패
# 질환별 "예측 대상 아님" 규칙(F11·F12): 이미 그 병이 있거나(진단·약) 임신, 19세 미만. 비만은 기준일 BMI≥25, 암은 그 암 과거력. 암 과거력(hx_cancer = 1)만으로는 대상에서 빼지 않는다(모든 암 예측)
INELIG = {'cvd33': [('hx_cvd', '심혈관질환 과거력')], 'cbv33': [('hx_cerebrovascular', '뇌혈관질환 과거력')],
          'htn33': [('hx_htn', '고혈압 진단력'), ('med_htn', '혈압약 복용')],
          'dm33': [('hx_dm', '당뇨 진단력'), ('med_dm', '당뇨약 복용')],
          'dlp33': [('hx_dyslipidemia', '이상지질혈증 진단력'), ('med_lipid', '지질강하제 복용')],
          'obe33': [],
          'gca33': [('hx_gastric_cancer', '위암 과거력')],
          'lca33': [('hx_liver_cancer', '간암 과거력')],
          'luc33': [('hx_lung_cancer', '폐암 과거력')],
          'crc33': [('hx_colorectal_cancer', '대장암 과거력')],
          'pac33': [('hx_pancreatic_cancer', '췌장암 과거력')],
          'pro33': [('hx_prostate_cancer', '전립선암 과거력')],
          'brc33': [('hx_breast_cancer', '유방암 과거력')],
          'thy33': [('hx_thyroid_cancer', '갑상선암 과거력')],
          'utc33': [('hx_uterine_cancer', '자궁암 과거력')]}
AGE_MIN = {'copd33': 40, 'frac33': 50}   # 보완 열 판정 나이(COPD 만 40세 이상, 골다공증성 골절 만 50세 이상) — 그보다 어리면 '예측 대상 아님'
SEX_ONLY = {'pro33': 1, 'brc33': 0, 'utc33': 0}   # 정의서 표 6-1: 전립선암 남성만, 유방암·자궁암 여성만 — 다른 성은 '예측 대상 아님'
MALE_ONLY = {k for k, v in SEX_ONLY.items() if v == 1}
# 측정값이 이미 그 질환 기준을 넘으면 "예측 대상 아님"(확진 검사 대상). 국가 목표 보정의 무병자 정의(국건영 HE_HP≠4, HE_DM_HbA1c≠3, 이상지질 수치 기준)와 맞춘다
MEASURED = {'htn33': [('sbp', '>=', 140, '수축기혈압 140 이상'), ('dbp', '>=', 90, '이완기혈압 90 이상')],
            'dm33': [('fpg', '>=', 126, '공복혈당 126 이상')],
            'dlp33': [('tchol', '>=', 240, '총콜레스테롤 240 이상'), ('ldl', '>=', 160, 'LDL 160 이상'), ('tg', '>=', 200, '중성지방 200 이상'), ('hdl', '<', 40, 'HDL 40 미만')],
            'obe33': [('bmi', '>=', 25, '이미 비만(BMI≥25)')]}
# 비우면 위험이 기준(상대 20%·2%p) 넘게 바뀌는 입력은 질환별 필수로 둔다(실제 검진자 표본으로 점검). 삼성 입력은 가족력 null→"0", LDL·GGT 빈칸→999999(범위 밖 → 빈칸)
EXTRA_REQ = {'cvd33': ['waist', 'ldl', 'ggt', 'urine_protein'], 'cbv33': ['ldl', 'urine_protein'], 'esr33': ['urine_protein'], 'htn33': ['waist', 'urine_protein', 'fh_htn'], 'dm33': ['waist', 'urine_protein', 'fh_dm'], 'dlp33': ['ldl', 'urine_protein'],
             'lca33': ['ldl', 'ggt', 'smoke_current'],   # 간암: LDL·GGT·현재 흡연이 기준 초과
             'luc33': ['smoke_current'],   # 폐암: 현재 흡연이 기준 초과
             'copd33': ['smoke_current', 'smoke_former']}   # COPD: 현재·과거 흡연이 기준 초과(영향도 상)
# 삼성 MCCC87TB(종합분석결과) 위험도 컬럼 — VARCHAR2(10), 10년 위험 %(소수 2자리). 대상 아님·필수 입력 누락은 NULL. 비만은 컬럼 없음
MCCC87TB_COL = {'cvd33': 'CAVAR_DS_RISKD', 'cbv33': 'BN_DS_RISKD', 'esr33': 'CHRN_RI_RISKD', 'htn33': 'HYT_RISKD', 'dlp33': 'HLM_RISKD', 'dm33': 'DIABT_RISKD', 'gca33': 'STC_RISKD', 'lca33': 'LVC_RISKD', 'luc33': 'LUC_RISKD', 'crc33': 'CRC_RISKD', 'pac33': 'PAC_RISKD', 'pro33': 'PROSTATE_CNCR_RISKD', 'brc33': 'BRC_RISKD', 'thy33': 'THC_RISKD', 'utc33': 'UTER_CNCR_RISKD',
                'dmn33': 'DMNT_RISKD', 'frac33': 'OSTE_RISKD'}   # 치매·골절 칸은 이름으로 맞춘 가정(골절 결과를 OSTE 칸에 — 삼성 확인). COPD 는 MCCC87TB 칸이 없다
MCCC87TB = ['MBR_ID', 'QSTN_SNO', 'AGE', 'HLTH_AGE', 'ATCPT_LOL', 'AVR_ATCPT_LOL', 'FACEO_RISKD', 'HYT_RISKD', 'HLM_RISKD', 'DIABT_RISKD', 'CAVAR_DS_RISKD',
            'BN_DS_RISKD', 'DMNT_RISKD', 'CHRN_RI_RISKD', 'OSTE_RISKD', 'STC_RISKD', 'LVC_RISKD', 'LUC_RISKD', 'CRC_RISKD', 'THC_RISKD', 'PAC_RISKD', 'BRC_RISKD',
            'PROSTATE_CNCR_RISKD', 'UTER_CNCR_RISKD', 'HYT_HLM_DIABT_CARES_YN', 'BWGHT_LOSSW_CARES_YN', 'REG_DTM', 'REG_ID', 'MDFC_DTM', 'MDFC_ID', 'RC_NO']
def to_mccc87tb(outputs):
    """질환별 predict_df 출력(dict 질환 → DataFrame, 같은 행 순서) → MCCC87TB 행. 이 모델들이 채우는 위험도 컬럼만 값이 있고 나머지는 통합 단계에서 채운다"""
    n = len(next(iter(outputs.values()))); T = pd.DataFrame({c: [None] * n for c in MCCC87TB})
    for dis, o in outputs.items():
        if dis in MCCC87TB_COL:
            T[MCCC87TB_COL[dis]] = [None if pd.isna(r) else f'{100 * r:.2f}' for r in o['risk_10y'].values]
    return T
LABEL = {'sbp': '수축기혈압', 'dbp': '이완기혈압', 'bmi': '체질량지수', 'waist': '허리둘레', 'fpg': '공복혈당', 'tchol': '총콜레스테롤', 'tg': '중성지방',
         'hdl': 'HDL콜레스테롤', 'ldl': 'LDL콜레스테롤', 'hb': '혈색소', 'creatinine': '크레아티닌', 'ast': 'AST', 'alt': 'ALT', 'ggt': '감마GTP',
         'urine_protein': '요단백', 'smoke_former': '과거 흡연', 'smoke_current': '현재 흡연', 'alc_cur': '음주', 'smoke_pk': '흡연량(갑년)', 'alc_g': '음주량',
         'hx_dm': '당뇨 과거력', 'hx_htn': '고혈압 과거력', 'hx_dyslipidemia': '이상지질혈증 과거력', 'hx_cvd': '심혈관질환 과거력',
         'hx_cerebrovascular': '뇌혈관질환 과거력', 'hx_tb': '결핵 과거력', 'hx_liver': '간장질환 과거력', 'hx_others': '기타 과거력'}
ALIAS = {'age': 'age_at_index', 'SBP': 'sbp', 'DBP': 'dbp', 'BMI': 'bmi', 'FPG': 'fpg', 'TC': 'tchol', 'TG': 'tg', 'HDL': 'hdl', 'LDL': 'ldl', 'Hb': 'hb',
         'Cr': 'creatinine', 'AST': 'ast', 'ALT': 'alt', 'GGT': 'ggt'}
FILL_ITEMS = ['sbp', 'dbp', 'bmi', 'fpg', 'tchol', 'tg', 'hdl', 'hb', 'creatinine', 'ast', 'alt']   # fill.json 으로 채우는 검사값(옛 공통 필수 13개 − 나이·성별)
Q_KEY = {'fh_htn': 'fh_htn', 'fh_dm': 'fh_dm', 'smoke_current': 'smoke', 'smoke_former': 'smoke', 'alc_cur': 'alc_cur'}   # 문진 빈칸 표시 이름(흡연은 하나)
GRADE = {'하': 1, '중': 2, '상': 3}
RANGE = dict(age_at_index=(1, 110), sbp=(60, 250), dbp=(30, 150), bmi=(12, 70), waist=(30, 220), fpg=(30, 800), tchol=(50, 1000), tg=(10, 5000), hdl=(5, 200),
             ldl=(10, 500), hb=(3, 25), creatinine=(0.1, 20), ast=(1, 5000), alt=(1, 5000), ggt=(1, 5000), urine_protein=(1, 6), pack_years=(0, 200), alc_g_week=(0, 5000))

def _lg(p): p = np.clip(p, 1e-9, 1 - 1e-9); return np.log(p / (1 - p))
def _cll(p): p = np.clip(p, 1e-9, 1 - 1e-9); return np.log(-np.log(1 - p))
def _icll(x): return 1 - np.exp(-np.exp(x))
def _band(a): return pd.cut(pd.Series(a, dtype=float), [0, 30, 40, 50, 60, 70, 200], right=False, labels=BANDS).astype(str).values

def yearly(P):
    """1~10년차 위험: 보정된 기간(1·3·5·8·10년) 값 사이를 cloglog × log(년) 에서 선형 보간. 보정된 기간 값과 정확히 같고 단조 증가"""
    lh = np.log(np.array(H, float)); C = np.column_stack([_cll(P[h]) for h in H])
    Y = np.column_stack([_icll(np.array([np.interp(np.log(t), lh, c) for c in C])) for t in range(1, 11)])
    return np.maximum.accumulate(Y, axis=1)

def normalize(df):
    """입력 표준화: 별칭·성별 문자·키/몸무게 → BMI·흡연 3범주 → 2변수·숫자 변환·범위 밖 값은 빈칸"""
    X = df.rename(columns=ALIAS).copy()
    for k in ['age_at_index', 'sex']:
        if k not in X: X[k] = np.nan
    if 'sex' in X: X['sex'] = X['sex'].map(lambda s: 1.0 if s in ('M', 'm', '남', 1, 1.0, '1') else (0.0 if s in ('F', 'f', '여', 0, 0.0, '0', '2') else np.nan))   # 삼성 SEX: M→"1", F→"2"
    for k in ['height', 'weight']:
        if k in X: X[k] = pd.to_numeric(X[k], errors='coerce')
    if 'bmi' not in X: X['bmi'] = np.nan
    if 'height' in X and 'weight' in X: X['bmi'] = pd.to_numeric(X['bmi'], errors='coerce').fillna(X.weight / (X.height / 100) ** 2)
    if 'smoke' in X:
        s = X['smoke'].astype(str).str.lower()
        X['smoke_former'] = np.where(s.isin(['former', '과거', '1']), 1.0, np.where(s.isin(['never', 'current', '비흡연', '현재', '0', '2']), 0.0, np.nan))
        X['smoke_current'] = np.where(s.isin(['current', '현재', '2']), 1.0, np.where(s.isin(['never', 'former', '비흡연', '과거', '0', '1']), 0.0, np.nan))
    for k, (lo, hi) in RANGE.items():
        if k in X:
            X[k] = pd.to_numeric(X[k], errors='coerce'); X.loc[(X[k] < lo) | (X[k] > hi), k] = np.nan
    return X

class Model:
    def __init__(self, dis, deploy_dir=None, fill_method=None):
        d = os.path.join(deploy_dir or DEPLOY, dis); self.dis = dis
        self.meta = json.load(open(f'{d}/meta.json', encoding='utf-8'))
        self.feats, self.sig = self.meta['features'], self.meta.get('sigma'); self.kind = self.meta.get('kind', 'aft')
        if self.kind == 'cox':   # 나이·성 Cox + 문헌 상대위험 고정값(대장암). model.json·보정표 없음 — 계수·기저 누적위험은 meta['cox']
            self.bst, self.cal, self.cox = None, {}, self.meta['cox']
            self.version = hashlib.sha256(open(f'{d}/meta.json', 'rb').read()).hexdigest()[:16]
        else:
            self.bst = xgb.Booster(); self.bst.load_model(f'{d}/model.json')
            self.cal = {int(h): np.array(v['p']) for h, v in json.load(open(f'{d}/calibration.json')).items()}
            self.version = hashlib.sha256(open(f'{d}/model.json', 'rb').read() + open(f'{d}/meta.json', 'rb').read()).hexdigest()[:16]
        self.qm, self.gp = self.meta.get('q_module'), self.meta.get('gpop') if self.meta.get('gpop_applied') else None
        self.req = [k for k in self.meta['required'] if k in self.feats or k in ('age_at_index', 'sex')]
        self.req += [k for k in EXTRA_REQ.get(dis, []) if k in self.feats or (self.qm and k in self.qm['features'])]
        self.nan_reached = 0   # 모델에 NaN 이 들어간 행 수(빈칸 점검용, 항상 0 이어야 한다)
        fp = f'{d}/fill.json'   # 빈칸 채움표(성·연령대 중앙값·회귀, 항목별 방법·영향도). 없으면 예전처럼 필수 입력 누락으로 막는다
        self.fill = json.load(open(fp, encoding='utf-8')) if os.path.exists(fp) else None
        self.fill_method = fill_method   # 점검용 덮어쓰기: 'median' | 'reg' | {항목: 방법}

    # ---------- 대상 여부 ----------
    def eligibility(self, X):
        ok = np.ones(len(X), bool); why = np.array([''] * len(X), dtype=object)
        def flag(m, r):
            nonlocal ok
            m = np.asarray(m, bool) & ok; why[m] = r; ok = ok & ~m
        # "예측 대상 아님"은 19세 미만과 성별 한정 암(전립선 남성, 유방·자궁 여성)만. 진단력·측정값 기준·COPD/골절 연령 하한·그 암 과거력이어도 위험을 낸다
        #   (INELIG·MEASURED·AGE_MIN 은 학습 대상 정의 기록으로만 남긴다. 임신은 API 입력에 없어 쓰지 않는다)
        flag((X.age_at_index < 19).values, '19세 미만')
        if self.dis in SEX_ONLY: flag((pd.to_numeric(X.sex, errors='coerce') == 1 - SEX_ONLY[self.dis]).values, '여성' if SEX_ONLY[self.dis] == 1 else '남성')
        return ok, why

    # ---------- 입력 정리·대치 ----------
    def prepare(self, X):
        X = X.copy(); ent = {}
        for k in self.feats + QF:
            if k not in X: X[k] = np.nan
            X[k] = pd.to_numeric(X[k], errors='coerce'); ent[k] = X[k].notna().values
        # 과거력 빈칸 = 없음. 기타 과거력(hx_others)이 빈칸이어도 다른 항목(암·간장질환·갑상선질환 등, HX_OTHERS)으로 채우지 않는다
        for f, spec in ((self.qm or {}).get('derived') or {}).items():   # 문진 상세(갑년·주 알코올 g) → 모듈 항목. 값이 없거나 해당 집단이 아니면 0(상태만 쓰는 것과 같다)
            src = pd.to_numeric(X[spec['source']], errors='coerce') if spec['source'] in X else pd.Series(np.nan, index=X.index)
            grp = ((X.smoke_former == 1) | (X.smoke_current == 1)) if spec['group'] == 'smoker' else (X.alc_cur == 1)
            has = (grp & src.notna()).values
            X[f] = np.where(has, np.maximum(np.log1p(src.clip(0, spec['cap'])) - spec['center'], spec.get('floor', -np.inf)), 0.0); ent[f] = has
        idok = X[['age_at_index', 'sex']].notna().all(axis=1).values   # 나이·성별 빈칸 = 입력 오류(채우지 않는다)
        imputed = {k: np.zeros(len(X), bool) for k in self.feats}
        if self.fill is None: reqok = X[self.req].notna().all(axis=1).values
        else:
            reqok = idok; bd = _band(X.age_at_index); its = self.fill['items']
            for k in FILL_ITEMS:
                if k not in X: X[k] = np.nan
                X[k] = pd.to_numeric(X[k], errors='coerce')
            miss = {k: X[k].isna().values & idok for k in FILL_ITEMS if k in its}
            for k, m in miss.items():   # 1) 성·연령대 중앙값
                if m.any(): X.loc[m, k] = [its[k]['median'].get(f'{int(s)}|{b}', its[k]['median']['default']) for s, b in zip(X.sex[m], bd[m])]
            for k, m in miss.items():   # 2) 방법이 회귀인 항목은 다른 검사값(1)에서 채운 값 포함)으로 예측
                fm = self.fill_method
                meth = (fm.get(k, its[k]['method']) if isinstance(fm, dict) else fm) if fm else its[k]['method']
                if meth != 'reg' or not m.any(): continue
                g = its[k]['reg']; Z = X.loc[m, g['predictors']].values.astype(float); y = g['intercept'] + Z @ np.array(g['coef'])
                X.loc[m, k] = np.clip(np.exp(y) if g['log'] else y, g['lo'], g['hi'])
            for k, m in miss.items():
                if k in imputed: imputed[k] = m
        if 'ldl' in self.feats:   # LDL 빈칸 → Friedewald(TG<400) 먼저
            fw = (X.tchol - X.hdl - X.tg / 5).where(X.tg < 400)
            X['ldl'] = X['ldl'].fillna(fw)
        for k, spec in self.meta['impute'].items():
            if k not in self.feats: continue
            m = X[k].isna().values & reqok
            if not m.any(): continue
            if spec['kind'] == 'linear':
                Z = X.loc[m, spec['predictors']].values.astype(float)
                y = spec['intercept'] + Z @ np.array(spec['coef'])
                X.loc[m, k] = np.clip(np.exp(y) if spec['log'] else y, spec['lo'], spec['hi'])
            else:
                bd = _band(X.loc[m, 'age_at_index'])
                X.loc[m, k] = [spec['by_sex_band'].get(f'{int(s)}|{b}', spec['default']) for s, b in zip(X.loc[m, 'sex'], bd)]
            imputed[k] = m
        for k in self.feats:   # 과거력 빈칸 = 없음(0). 남은 빈칸은 입력 오류(나이·성별) 행에만 있다
            if k.startswith('hx_'):
                imputed[k] = imputed[k] | X[k].isna().values; X[k] = X[k].fillna((self.meta.get('blank_fill') or {}).get(k, 0.0))   # 빈칸 = 없음(0), blank_fill 이 있으면 그 값(갑상선암 Q-05: 평균 위험)
        return X, ent, imputed, reqok

    # ---------- 위험 ----------
    def _m(self, X):
        A = X[self.feats].values.astype(float)
        self.nan_reached += int(np.isnan(A).any(axis=1).sum())
        m = np.log(np.clip(self.bst.predict(xgb.DMatrix(A, feature_names=self.feats)), 1e-6, None))
        if self.qm is not None:
            Q = np.column_stack([X[k].values if k in X else np.full(len(X), np.nan) for k in self.qm['features']]).astype(float)
            Q = np.where(np.isnan(Q), np.array(self.qm['mean']), Q)   # 문진 빈칸 = 이동 0
            m = m + (Q - np.array(self.qm['mean'])) @ np.array(self.qm['beta'])
        return m
    def _shift(self, sex, age):
        p = self.gp['params']; a = np.asarray(age, float)
        return np.where(np.asarray(sex) == 1, np.interp(a, p['1']['age_mid'], p['1']['shift']), np.interp(a, p['0']['age_mid'], p['0']['shift']))
    def _cox_z(self, X):
        a = X.age_at_index.values.astype(float); u = (a - 50) / 10   # age3·bmi25_post: 유방암(나이 비단조, 폐경 후 BMI 만)
        g = lambda k: X[k].values.astype(float) if k in X else np.zeros(len(a))   # 나이만 쓰는 묶음(자궁암)은 BMI·당뇨 열을 받지 않는다
        bmi, hxd, fpg = g('bmi'), g('hx_dm'), g('fpg')
        return {'age': a, 'age2': u ** 2, 'age3': u ** 3, 'male': X.sex.values.astype(float), 'bmi25': (bmi >= 25).astype(float),
                'bmi25_post': ((bmi >= 25) & (a >= 50)).astype(float),
                'dm': ((hxd == 1) | (fpg >= 126)).astype(float),
                'hx_dm': (hxd == 1).astype(float), 'hx_htn': (g('hx_htn') == 1).astype(float)   # 자궁암: 정의서 ICD 진단력만(혈당 안 씀)
               , 'hx_thyroid': np.clip(g('hx_thyroid'), 0, 1), 'hx_nulliparous': (g('hx_nulliparous') == 1).astype(float)}   # hx_thyroid: 갑상선암(자료로 맞춘 위험비)
    def _tz(self, t, z):
        """Cox 항 기여(위험 척도). w_age 가 있으면 나이별 희석 상대위험 RR_eff = 1 + w(나이)·(RR − 1)(자궁암)"""
        if 'w_age' not in t: return t['beta'] * (z[t['name']] - t['mean'])
        return np.log1p(np.interp(z['age'], t['w_age']['age'], t['w_age']['w']) * (t['rr'] - 1)) * z[t['name']] - t['mean']
    def _lp(self, X):
        """Cox 선형 예측자(위험 척도): Σ β(z − 평균). BMI≥25·당뇨는 문헌 고정 ln RR, 흡연·음주는 q_module(β = −ln RR, AFT 의 ln T 척도와 부호를 맞춤)"""
        A = X[self.feats].values.astype(float); self.nan_reached += int(np.isnan(A).any(axis=1).sum())
        z = self._cox_z(X); lp = sum(self._tz(t, z) for t in self.cox['terms'])
        if self.qm is not None:
            Q = np.column_stack([X[k].values if k in X else np.full(len(X), np.nan) for k in self.qm['features']]).astype(float)
            Q = np.where(np.isnan(Q), np.array(self.qm['mean']), Q)   # 문진 빈칸 = 평균(이동 0)
            lp = lp - (Q - np.array(self.qm['mean'])) @ np.array(self.qm['beta'])
        return lp
    def _cox_contrib(self, X):
        """TOP3 용 기여(ln T 척도 = −선형 예측자 항). 당뇨 항은 당뇨 과거력이 있으면 hx_dm, 아니면 공복혈당에 둔다"""
        z = self._cox_z(X); C = pd.DataFrame(0.0, index=X.index, columns=self.feats)
        for t in self.cox['terms']:
            v = -self._tz(t, z)
            if t['name'] == 'dm':
                h = X.hx_dm.values == 1; C['hx_dm'] += np.where(h, v, 0.0); C['fpg'] += np.where(h, 0.0, v)
            else: C[{'age': 'age_at_index', 'age2': 'age_at_index', 'age3': 'age_at_index', 'male': 'sex', 'bmi25': 'bmi', 'bmi25_post': 'bmi', 'hx_dm': 'hx_dm', 'hx_htn': 'hx_htn', 'hx_thyroid': 'hx_thyroid', 'hx_nulliparous': 'hx_nulliparous'}[t['name']]] += v
        return C
    def risk(self, X, hospital_scale=False):
        if self.kind == 'cox':
            lp = self._lp(X); out, prev = {}, None
            d = self._shift(X.sex.values, X.age_at_index.values) if (self.gp and not hospital_scale) else 0.0
            for h in H:
                p = 1 - np.exp(-self.cox['H0'][str(h)] * np.exp(lp))
                if self.gp and not hospital_scale: p = _icll(_cll(p) + d)
                if prev is not None: p = np.maximum(p, prev)
                out[h] = p; prev = p
            return out
        m = self._m(X); out, prev = {}, None
        d = self._shift(X.sex.values, X.age_at_index.values) if (self.gp and not hospital_scale) else 0.0
        for h in H:
            f = stats.norm.cdf((np.log(h) - m) / self.sig)
            p = np.interp(_lg(f), GRID_X, self.cal[h]) if h in self.cal else f
            if self.gp and not hospital_scale: p = _icll(_cll(p) + d)
            if prev is not None: p = np.maximum(p, prev)
            out[h] = p; prev = p
        return out

    # ---------- TOP3 ----------
    def top3(self, X, ent, imputed):
        if self.kind == 'cox': C = self._cox_contrib(X)
        else:
            c = self.bst.predict(xgb.DMatrix(X[self.feats].values.astype(float), feature_names=self.feats), pred_contribs=True)[:, :-1]
            C = pd.DataFrame(c, columns=self.feats, index=X.index)
        if self.qm is not None:
            for f, b, mu in zip(self.qm['features'], self.qm['beta'], self.qm['mean']):
                q = X[f].values.astype(float) if f in X else np.full(len(X), np.nan); C[f] = b * (np.where(np.isnan(q), mu, q) - mu)
        cand = C.drop(columns=[f for f in C if f in NONMOD])
        show = pd.DataFrame({f: (ent.get(f, np.zeros(len(X), bool)) & ~imputed.get(f, np.zeros(len(X), bool))) for f in cand.columns}, index=X.index)
        for f in ['smoke_former', 'smoke_current', 'alc_cur']:   # 0값 생활습관은 뺀다
            if f in show: show[f] = show[f] & (X[f].fillna(0).values == 1)
        neg = (-cand).clip(lower=0).where(show.values, 0.0)   # ln T 가 줄어드는(위험 증가) 기여만
        tot = neg.sum(axis=1).replace(0, np.nan); res = []
        for i in range(len(X)):
            r = neg.iloc[i]; r = r[r > 0].sort_values(ascending=False, kind='stable')[:3]
            res.append([(f, LABEL.get(f, f), round(float(v / tot.iloc[i]), 3)) for f, v in r.items()])
        return res, C

    # ---------- 전체 ----------
    def predict_df(self, df, hospital_scale=False):
        X = normalize(pd.DataFrame(df).reset_index(drop=True))
        qblank = {q: (pd.to_numeric(X[q], errors='coerce').isna().values if q in X else np.ones(len(X), bool))
                  for q in QF if self.qm and q in self.qm['features']}   # 문진 빈칸(모듈 평균으로 계산) — imputed 에 표시
        fcols = [c for c in X.columns if str(c).lower() in FORBIDDEN]   # 금지 항목은 받아도 쓰지 않는다. 값이 들어온 행만 표시
        bad_in = [sorted(str(c).lower() for c in fcols if pd.notna(X.at[i, c])) for i in X.index]
        elig, why = self.eligibility(X)
        Xp, ent, imputed, reqok = self.prepare(X)
        idok = X[['age_at_index', 'sex']].notna().all(axis=1).values
        run = elig & reqok & idok
        out = pd.DataFrame(index=X.index)
        out['disease'] = self.dis; out['model_version'] = self.version
        out['eligible'] = elig & idok
        out['status'] = np.where(~idok, '입력 오류', np.where(~elig, '예측 대상 아님', np.where(~reqok, '필수 입력 누락', '정상')))
        out['reason'] = np.where(~idok, '나이·성별 없음(스크래핑 확인 필요)', np.where(~elig, why, np.where(~reqok, '필수 입력: ' + ','.join(self.req), '')))
        for h in OUT_H: out[f'risk_{h}y'] = np.nan
        t3all = [[] for _ in range(len(X))]; yrs = [None] * len(X)
        out['imputed'] = [list(dict.fromkeys([k for k in self.feats if imputed[k][i] and not k.startswith('hx_')] + [Q_KEY[q] for q, b in qblank.items() if b[i]]))
                          if run[i] else [] for i in range(len(X))]
        imp = (self.fill or {}).get('impact', {})   # 채운 항목 중 영향도가 가장 큰 것(상·중·하), 채운 것 없으면 빈칸
        out['input_impact'] = [max((imp.get(k, {}).get('grade', '하') for k in L), key=lambda g: GRADE[g]) if L else '' for L in out['imputed']]
        out['forbidden_inputs'] = bad_in
        if run.any():
            R = Xp[run]; P = self.risk(R, hospital_scale)
            dg = DIGITS_BY.get(self.dis, DIGITS)
            for h in OUT_H: out.loc[run, f'risk_{h}y'] = np.round(P[h], dg)
            t3, _ = self.top3(R, {k: v[run] for k, v in ent.items()}, {k: v[run] for k, v in imputed.items()})
            for i, t in zip(np.where(run)[0], t3): t3all[i] = t
            Y = yearly(P)
            for j, i in enumerate(np.where(run)[0]): yrs[i] = [round(float(v), dg) for v in Y[j]]
        out['top3'] = t3all; out['risk_by_year'] = yrs   # 1~10년차 위험(앱 그래프용)
        return out
    def predict(self, rec):
        return self.predict_df(pd.DataFrame([rec])).iloc[0].to_dict()

if __name__ == '__main__':
    dis, src = sys.argv[1], sys.argv[2]
    df = pd.read_csv(src) if src.endswith('.csv') else pd.DataFrame(json.load(open(src, encoding='utf-8')))
    o = Model(dis).predict_df(df)
    if len(sys.argv) > 3: o.to_csv(sys.argv[3], index=False, encoding='utf-8-sig')
    else: print(o.to_string())
