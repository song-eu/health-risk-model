# health_age_api.py — 건강나이·기대여명 배포 엔진(deploy/ha33 묶음 = ha_bundle.py). 입력 표준화는 질환 모델과 같은 deploy_api.normalize
# usage: from health_age_api import HealthAge; HealthAge().predict_df(DataFrame) / python3 health_age_api.py 입력.csv [출력.csv]
# 출력: health_age(건강나이), life_expectancy(남은 기대여명 = 2024 완전생명표 e_성(건강나이)), life_span(기대수명 = 건강나이 + 남은 기대여명 — 항목정의서 예시 101.095 = 99 + 2.095 에 맞춤),
#       avg_life_span(같은 성·나이 평균 기대수명 = 실제 나이 + e_성(실제 나이)), delta(건강나이 − 실제 나이), status·reason·imputed·input_impact
# 필수 입력 확인을 없앴다 — 검사값 빈칸은 fill.json(성·연령대 중앙값 → 항목별로 정한 경우 회귀, make_fill.py ha33)으로 채워 계산한다.
#   나이·성별 빈칸(범위 밖 포함) = "입력 오류"(스크래핑 이상), 결과 NULL. 채운 항목 중 가장 큰 영향도(impact_null_ha.py: 상·중·하) = input_impact
import os, sys, json, numpy as np, pandas as pd, xgboost as xgb
from deploy_api import normalize, DEPLOY
REQ = ['age_at_index', 'sex', 'sbp', 'dbp', 'bmi', 'fpg', 'tchol', 'tg', 'hdl', 'hb', 'creatinine', 'ast', 'alt']   # 옛 필수 입력(질환 모델과 같음). 지금은 나이·성별만 필수
GRADE = {'하': 1, '중': 2, '상': 3}
OPT = ['waist', 'ldl', 'ggt', 'urine_protein']   # 빈칸이면 학습 자료 성·연령대 중앙값(imputed 에 표시)
BANDS = ['19-29', '30-39', '40-49', '50-59', '60-69', '70+']
def band(a): return pd.cut(pd.Series(a, dtype=float), [0, 30, 40, 50, 60, 70, 200], right=False, labels=BANDS).astype(str).values

class HealthAge:
    def __init__(self, deploy_dir=None, fill_method=None):
        d = os.path.join(deploy_dir or DEPLOY, 'ha33')
        fp = os.path.join(d, 'fill.json'); self.fill = json.load(open(fp, encoding='utf-8')) if os.path.exists(fp) else None   # 없으면 예전처럼 필수 입력 누락
        self.fill_method = fill_method   # 점검용 덮어쓰기: 'median' | 'reg' | {항목: 방법}
        self.meta = json.load(open(os.path.join(d, 'meta.json'), encoding='utf-8'))
        self.bst = xgb.Booster(); self.bst.load_model(os.path.join(d, 'health_age.json'))
        self.version = self.meta['version']; self.feats = self.meta['features']; self.lt = {int(k): v for k, v in self.meta['life_table'].items()}
    def ex(self, age, sex):
        a = np.clip(np.asarray(age, float), 0, 100); s = np.asarray(sex, float)
        return np.where(s == 1, np.interp(a, np.arange(101), self.lt[1]), np.interp(a, np.arange(101), self.lt[0]))
    def expected(self, age, sex):
        b = self.meta['bias']; return np.where(np.asarray(sex) == 1, np.polyval(b['1'], age), np.polyval(b['0'], age))
    def predict_df(self, df):
        X = normalize(pd.DataFrame(df)).reset_index(drop=True)
        for c in REQ + OPT + list(self.meta['add']):
            if c not in X: X[c] = np.nan
            X[c] = pd.to_numeric(X[c], errors='coerce')
        age, sex = X.age_at_index.values.astype(float), X.sex.values.astype(float)
        idok = ~np.isnan(age) & ~np.isnan(sex); imputed = [[] for _ in range(len(X))]; bd = band(age)
        if self.fill:   # 검사값 빈칸 채움(질환 모델 deploy_api 와 같은 순서): 1) 성·연령대 중앙값 2) 방법이 회귀면 다른 검사값으로 예측
            its = self.fill['items']; fm = self.fill_method
            fmiss = {k: X[k].isna().values & idok for k in REQ[2:] if k in its}
            for k, m in fmiss.items():
                if m.any(): X.loc[m, k] = [its[k]['median'].get(f'{int(s_)}|{b}', its[k]['median']['default']) for s_, b in zip(sex[m], bd[m])]
            for k, m in fmiss.items():
                meth = (fm.get(k, its[k]['method']) if isinstance(fm, dict) else fm) if fm else its[k]['method']
                if meth != 'reg' or not m.any(): continue
                g = its[k]['reg']; Z = X.loc[m, g['predictors']].values.astype(float); y = g['intercept'] + Z @ np.array(g['coef'])
                X.loc[m, k] = np.clip(np.exp(y) if g['log'] else y, g['lo'], g['hi'])
            for k, m in fmiss.items():
                for i in np.where(m)[0]: imputed[i].append(k)
        X['ldl'] = X.ldl.fillna((X.tchol - X.hdl - X.tg / 5).where(X.tg < 400))   # 질환 모델과 같은 Friedewald
        miss = X[REQ].isna(); ok = ~miss.any(axis=1) & (X.age_at_index >= 19)   # fill 이 있으면 남는 빈칸은 나이·성별뿐
        for c in OPT:
            for i in np.where(X[c].isna())[0]:
                if np.isnan(sex[i]) or bd[i] == 'nan': continue
                X.at[i, c] = self.meta['impute'][str(int(sex[i]))][bd[i]][c]; imputed[i].append(c)
        Xf = X[self.feats].astype('float32').fillna(0)   # 필수 빈칸 행은 아래에서 결과를 버린다
        raw = self.bst.predict(xgb.DMatrix(Xf, feature_names=self.feats))
        exam = age + self.meta['shrink_lambda'] * (raw - self.expected(age, sex))
        add = sum(np.nan_to_num(X[c].values.astype(float)) * a for c, a in self.meta['add'].items())   # 과거력·흡연·음주 빈칸 = 가산 없음
        ha = np.maximum(exam + add, self.meta['min_health_age']); rem = self.ex(ha, sex)
        r1 = lambda v: [round(float(x), 1) if k else None for x, k in zip(v, ok)]
        reason = ['' if k else ('나이·성별 없음(스크래핑 확인 필요)' if (self.fill and not d) else ('대상 아님(만 19세 미만)' if a < 19 else '필수 입력 누락: ' + ','.join(miss.columns[miss.iloc[i]])))
                  for i, (k, a, d) in enumerate(zip(ok, np.nan_to_num(age, nan=99), idok))]
        imp = (self.fill or {}).get('impact', {})
        impact = [max((imp.get(c, {}).get('grade', '하') for c in v), key=lambda g: GRADE[g]) if (v and k) else '' for v, k in zip(imputed, ok)]
        return pd.DataFrame(dict(health_age=r1(ha), delta=r1(ha - age), life_expectancy=r1(rem), life_span=r1(ha + rem), avg_life_span=r1(age + self.ex(age, sex)),
                                 status=np.where(ok, '정상', np.where(~idok & bool(self.fill), '입력 오류', np.where(np.nan_to_num(age, nan=99) < 19, '대상 아님', '필수 입력 누락'))), reason=reason,
                                 imputed=[','.join(v) for v in imputed], input_impact=impact, model_version=self.version))
    def predict(self, rec): return self.predict_df(pd.DataFrame([rec])).iloc[0].to_dict()

def to_mccc87tb_cols(O):
    """MCCC87TB HLTH_AGE·ATCPT_LOL·AVR_ATCPT_LOL(VARCHAR2(10), 소수 1자리). 대상 아님·필수 누락은 NULL. 필드 정의는 삼성 확인 필요"""
    f = lambda v: [None if v_ is None or pd.isna(v_) else f'{v_:.1f}' for v_ in v]
    return dict(HLTH_AGE=f(O.health_age), ATCPT_LOL=f(O.life_span), AVR_ATCPT_LOL=f(O.avg_life_span))

if __name__ == '__main__':
    src = sys.argv[1]; df = pd.read_json(src) if src.endswith('.json') else pd.read_csv(src)
    out = HealthAge().predict_df(df)
    out.to_csv(sys.argv[2], index=False) if len(sys.argv) > 2 else print(out.to_string())
