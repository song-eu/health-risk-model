// 위험예측 엔진(브라우저·Node 공용) — api/anyfit_api.py · deploy_api.py · health_age_api.py 를 그대로 옮긴 것.
// 빈칸 처리: 나이·성별 말고는 빈칸을 채워서 계산한다(fill.json — 성·연령대 중앙값 → 항목별로 정한 경우 회귀). 나이·성별 빈칸은 "입력 오류".
// 출력에 채운 항목(IMPUTED_INPUTS)과 영향도(INPUT_IMPACT: 상·중·하)를 남긴다.
// 입력: 애니핏 API 항목정의서 코드(AGE, SEX, BMI, …). 출력: anyfit_api.predict_anyfit 과 같은 구조.
// 사용: const E = RiskEngine(BUNDLES); E.predictAnyfit(record)  (BUNDLES = {질환: {meta, model, calibration, reference, version}, ha33: {meta, model}})
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.RiskEngine = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';
  const H = [1, 3, 5, 8, 10], OUT_H = [1, 5, 10], DIGITS = 4;
  const DIGITS_BY = { lca33: 5, luc33: 5, pac33: 5, pro33: 6, crc33: 5, utc33: 6, esr33: 6, dmn33: 6 };
  const GRID_X = Array.from({ length: 561 }, (_, i) => Math.round((-14 + 0.05 * i) * 1e4) / 1e4);
  const BANDS = ['19-29', '30-39', '40-49', '50-59', '60-69', '70+'];
  const HX_OTHERS = ['hx_cancer', 'hx_gi', 'hx_liver', 'hx_gallbladder', 'hx_kidney', 'hx_bronchial', 'hx_thyroid', 'hx_bleeding',
    'hx_hypercalcemia', 'hx_hyperkalemia', 'hx_lactose_intol', 'hx_hyperestrogenism', 'hx_pregnant'];
  const QF = ['fh_htn', 'fh_dm', 'smoke_former', 'smoke_current', 'alc_cur'];
  const INELIG = {
    cvd33: [['hx_cvd', '심혈관질환 과거력']], cbv33: [['hx_cerebrovascular', '뇌혈관질환 과거력']],
    htn33: [['hx_htn', '고혈압 진단력'], ['med_htn', '혈압약 복용']], dm33: [['hx_dm', '당뇨 진단력'], ['med_dm', '당뇨약 복용']],
    dlp33: [['hx_dyslipidemia', '이상지질혈증 진단력'], ['med_lipid', '지질강하제 복용']], obe33: [],
    gca33: [['hx_gastric_cancer', '위암 과거력']], lca33: [['hx_liver_cancer', '간암 과거력']],
    luc33: [['hx_lung_cancer', '폐암 과거력']], crc33: [['hx_colorectal_cancer', '대장암 과거력']],
    pac33: [['hx_pancreatic_cancer', '췌장암 과거력']], pro33: [['hx_prostate_cancer', '전립선암 과거력']],
    brc33: [['hx_breast_cancer', '유방암 과거력']], thy33: [['hx_thyroid_cancer', '갑상선암 과거력']],
    utc33: [['hx_uterine_cancer', '자궁암 과거력']]
  };
  const AGE_MIN = { copd33: 40, frac33: 50 };   // COPD 만 40세 이상, 골다공증성 골절 만 50세 이상만 예측(그보다 어리면 '예측 대상 아님')
  const SEX_ONLY = { pro33: 1, brc33: 0, utc33: 0 };
  const MEASURED = {
    htn33: [['sbp', '>=', 140, '수축기혈압 140 이상'], ['dbp', '>=', 90, '이완기혈압 90 이상']],
    dm33: [['fpg', '>=', 126, '공복혈당 126 이상']],
    dlp33: [['tchol', '>=', 240, '총콜레스테롤 240 이상'], ['ldl', '>=', 160, 'LDL 160 이상'], ['tg', '>=', 200, '중성지방 200 이상'], ['hdl', '<', 40, 'HDL 40 미만']],
    obe33: [['bmi', '>=', 25, '이미 비만(BMI≥25)']]
  };
  const EXTRA_REQ = {
    cvd33: ['waist', 'ldl', 'ggt', 'urine_protein'], cbv33: ['ldl', 'urine_protein'], esr33: ['urine_protein'], htn33: ['waist', 'urine_protein', 'fh_htn'],
    dm33: ['waist', 'urine_protein', 'fh_dm'], dlp33: ['ldl', 'urine_protein'], lca33: ['ldl', 'ggt', 'smoke_current'], luc33: ['smoke_current'],
    copd33: ['smoke_current', 'smoke_former']
  };
  const RANGE = {
    age_at_index: [1, 110], sbp: [60, 250], dbp: [30, 150], bmi: [12, 70], waist: [30, 220], fpg: [30, 800], tchol: [50, 1000], tg: [10, 5000], hdl: [5, 200],
    ldl: [10, 500], hb: [3, 25], creatinine: [0.1, 20], ast: [1, 5000], alt: [1, 5000], ggt: [1, 5000], urine_protein: [1, 6], pack_years: [0, 200], alc_g_week: [0, 5000]
  };
  // ---- 애니핏 정의서 대응(anyfit_api.py) ----
  const DIS_OUT = [['cvd33', 'CVD'], ['cbv33', 'Stroke'], ['esr33', 'CRF'], ['dm33', 'DM'], ['htn33', 'Hypertension'], ['dlp33', 'Hyperlipidemia'], ['gca33', 'Stomach'],
    ['lca33', 'Liver'], ['luc33', 'Lung'], ['crc33', 'Colorectal'], ['pac33', 'Pancreas'], ['pro33', 'Prostate'], ['brc33', 'Breast'], ['thy33', 'Thyroid'], ['utc33', 'Uterus'],
    ['copd33', 'COPD'], ['frac33', 'Fracture'], ['dmn33', 'Dementia'],   // 출력명은 가칭(정의서에 없음)
    ['obe33', 'Obesity']];   // 비만은 정의서 출력에 없다(엔진에만 있음) — 시험 화면에서는 함께 보인다
  const NUM = { WAIST: 'waist', BP_HIGH: 'sbp', BP_LWST: 'dbp', BLDS: 'fpg', TOT_CHOLE: 'tchol', TRIGLYCERIDE: 'tg', HDL_CHOLE: 'hdl', LDL_CHOLE: 'ldl',
    HMG: 'hb', CREATININE: 'creatinine', SGOT_AST: 'ast', SGPT_ALT: 'alt', GAMMA_GTP: 'ggt', BMI: 'bmi' };
  const HCHK = { HCHK_APOP_PMH_YN: 'hx_cerebrovascular', HCHK_HDISE_PMH_YN: 'hx_cvd', HCHK_HPRTS_PMH_YN: 'hx_htn', HCHK_DIABML_PMH_YN: 'hx_dm',
    HCHK_HPLPDM_PMH_YN: 'hx_dyslipidemia', HCHK_PHSS_PMH_YN: 'hx_tb', HCHK_ETCDSE_PMH_YN: 'hx_others', HCHK_LIVER_PMH_YN: 'hx_liver' };
  const FMLY = { FMLY_HPRTS_PATIEN_YN: 'fh_htn', FMLY_DIABML_PATIEN_YN: 'fh_dm' };
  const EXTRA = { HCHK_CANCER_PMH_YN: 'hx_cancer', HCHK_THYROID_PMH_YN: 'hx_thyroid' };   // 갑상선질환 가칭 필드(anyfit_api.py 와 같음). 임신은 API 입력에 없어 받지 않음
  const PREG_LACT = 'PREG_LACT_HIST_YN';   // 가칭: 임신/수유 과거력 1 있음·0 없음 → hx_nulliparous = 1 − 값
  const UPRO = { '-': 1, '음성': 1, '음성(-)': 1, '약양성': 2, '±': 2, '+/-': 2, '+1': 3, '1+': 3, '양성(+1)': 3, '+2': 4, '2+': 4, '양성(+2)': 4, '+3': 5, '3+': 5, '양성(+3)': 5, '+4': 6, '4+': 6, '양성(+4)': 6 };
  const CTRL = [['sbp', 'BP_HIGH', [120, 120], 'down'], ['dbp', 'BP_LWST', [80, 80], 'down'], ['bmi', 'BMI', [23, 23], 'down'], ['waist', 'WAIST', [85, 90], 'down'],
    ['fpg', 'BLDS', [100, 100], 'down'], ['tchol', 'TOT_CHOLE', [200, 200], 'down'], ['tg', 'TRIGLYCERIDE', [150, 150], 'down'], ['ldl', 'LDL_CHOLE', [130, 130], 'down'],
    ['hdl', 'HDL_CHOLE', [50, 40], 'up'], ['ast', 'SGOT_AST', [40, 40], 'down'], ['alt', 'SGPT_ALT', [40, 40], 'down'], ['ggt', 'GAMMA_GTP', [35, 63], 'down'],
    ['smoke_current', 'SMOKING', null, 'quit'], ['alc_cur', 'DRINKING', null, 'stop']];
  const UNCTRL = Object.entries(FMLY).map(([k, v]) => [v, k]).concat(Object.entries(HCHK).map(([k, v]) => [v, k]));
  const CTRL_ALLOW = { luc33: ['SMOKING'], pac33: ['SMOKING', 'BMI', 'WAIST', 'BLDS'], pro33: [], crc33: ['SMOKING', 'DRINKING', 'BMI', 'BLDS'] };
  const UNCTRL_ALLOW = { luc33: ['HCHK_PHSS_PMH_YN'], pac33: ['HCHK_DIABML_PMH_YN'], pro33: [], crc33: ['HCHK_DIABML_PMH_YN'] };
  const YEARS_CD = { 1: 2.5, 2: 7.0, 3: 15.0, 4: 25.0, 5: 35.0 }, PERDAY_CD = { 1: 5.0, 2: 15.0, 3: 30.0, 4: 45.0 };
  const DRINK_G = { '소주': 6.6, '맥주': 7.1, '막걸리': 9.5, '와인': 14.2, '양주': 12.6 };
  const DRINK_COL = { DRINK_SOJU: '소주', DRINK_BEER: '맥주', DRINK_MAKGEOLLI: '막걸리', DRINK_WINE: '와인', DRINK_LIQUOR: '양주' };
  const DRINK_TYPE_CD = { 1: '소주', 2: '맥주', 3: '막걸리', 4: '와인', 5: '양주', soju: '소주', beer: '맥주', makgeolli: '막걸리', wine: '와인', liquor: '양주' };
  // ---- 건강나이(health_age_api.py) ----
  const FILL_ITEMS = ['sbp', 'dbp', 'bmi', 'fpg', 'tchol', 'tg', 'hdl', 'hb', 'creatinine', 'ast', 'alt'];
  const Q_KEY = { fh_htn: 'fh_htn', fh_dm: 'fh_dm', smoke_current: 'smoke', smoke_former: 'smoke', alc_cur: 'alc_cur' };
  const GRADE = { '하': 1, '중': 2, '상': 3 };
  const IMP_CODE = { waist: 'WAIST', sbp: 'BP_HIGH', dbp: 'BP_LWST', fpg: 'BLDS', tchol: 'TOT_CHOLE', tg: 'TRIGLYCERIDE', hdl: 'HDL_CHOLE', ldl: 'LDL_CHOLE', hb: 'HMG',
    creatinine: 'CREATININE', ast: 'SGOT_AST', alt: 'SGPT_ALT', ggt: 'GAMMA_GTP', bmi: 'BMI', urine_protein: 'OLIG_PROTE_CD', fh_htn: 'FMLY_HPRTS_PATIEN_YN', fh_dm: 'FMLY_DIABML_PATIEN_YN',
    smoke: 'SMOKING', alc_cur: 'DRINKING' };   // anyfit_api.IMP_CODE
  const HA_REQ = ['age_at_index', 'sex', 'sbp', 'dbp', 'bmi', 'fpg', 'tchol', 'tg', 'hdl', 'hb', 'creatinine', 'ast', 'alt'];
  const HA_OPT = ['waist', 'ldl', 'ggt', 'urine_protein'];

  // ---------- 수치 도구(numpy·scipy 와 같은 결과) ----------
  const isn = v => v === null || v === undefined || (typeof v === 'number' && isNaN(v));
  function num(v) {   // pandas.to_numeric(errors='coerce')
    if (v === null || v === undefined || typeof v === 'boolean') return NaN;
    if (typeof v === 'number') return v;
    const s = String(v).trim(); if (s === '') return NaN;
    const x = Number(s); return isNaN(x) ? NaN : x;
  }
  function interp(x, xp, fp, left, right) {   // numpy.interp
    if (isNaN(x)) return NaN;
    const n = xp.length;
    if (x <= xp[0]) return x === xp[0] ? fp[0] : (left === undefined ? fp[0] : left);
    if (x >= xp[n - 1]) return x === xp[n - 1] ? fp[n - 1] : (right === undefined ? fp[n - 1] : right);
    let lo = 0, hi = n - 1;
    while (hi - lo > 1) { const m = (lo + hi) >> 1; if (xp[m] <= x) lo = m; else hi = m; }
    if (x === xp[lo]) return fp[lo];
    const slope = (fp[lo + 1] - fp[lo]) / (xp[lo + 1] - xp[lo]);
    return slope * (x - xp[lo]) + fp[lo];
  }
  function rint(x) { const f = Math.floor(x), d = x - f; return d > 0.5 ? f + 1 : d < 0.5 ? f : (f % 2 === 0 ? f : f + 1); }
  function npRound(x, d) { if (isNaN(x)) return NaN; const s = Math.pow(10, d); return rint(x * s) / s; }   // numpy.round
  function pyRound(x, d) { return isNaN(x) ? NaN : Number(x.toFixed(d)); }   // Python round(정확한 이진값 기준)
  const clip = (x, a, b) => Math.min(Math.max(x, a), b);
  const lg = p => { p = clip(p, 1e-9, 1 - 1e-9); return Math.log(p / (1 - p)); };
  const cll = p => { p = clip(p, 1e-9, 1 - 1e-9); return Math.log(-Math.log(1 - p)); };
  const icll = x => 1 - Math.exp(-Math.exp(x));
  // scipy.stats.norm.cdf = cephes ndtr
  const P_ = [2.46196981473530512524E-10, 5.64189564831068821977E-1, 7.46321056442269912687E0, 4.86371970985681366614E1, 1.96520832956077098242E2,
    5.26445194995477358631E2, 9.34528527171957607540E2, 1.02755188689515710272E3, 5.57535335369399327526E2];
  const Q_ = [1.32281951154744992508E1, 8.67072140885989742329E1, 3.54937778887819891062E2, 9.75708501743205489753E2, 1.82390916687909736289E3,
    2.24633760818710981792E3, 1.65666309194161350182E3, 5.57535340817727675546E2];
  const R_ = [5.64189583547755073984E-1, 1.27536670759978104416E0, 5.01905042251180477414E0, 6.16021097993053585195E0, 7.40974269950448939160E0, 2.97886665372100240670E0];
  const S_ = [2.26052863220117276590E0, 9.39603524938001434673E0, 1.20489539808096656605E1, 1.70814450747565897222E1, 9.60896809063285878198E0, 3.36907645100081516050E0];
  const T_ = [9.60497373987051638749E0, 9.00260197203842689217E1, 2.23200534594684319226E3, 7.00332514112805075473E3, 5.55923013010394962768E4];
  const U_ = [3.35617141647503099647E1, 5.21357949780152679795E2, 4.59432382970980127987E3, 2.26290000613890934246E4, 4.92673942608635921086E4];
  const polevl = (x, c) => c.reduce((a, b) => a * x + b, 0);
  const p1evl = (x, c) => c.reduce((a, b) => a * x + b, 1);
  function erf(x) { if (Math.abs(x) > 1) return 1 - erfc(x); const z = x * x; return x * polevl(z, T_) / p1evl(z, U_); }
  function erfc(a) {
    const x = Math.abs(a); if (x < 1) return 1 - erf(a);
    let z = -a * a; if (z < -709.782712893384) return a < 0 ? 2 : 0;
    z = Math.exp(z);
    const p = x < 8 ? polevl(x, P_) : polevl(x, R_), q = x < 8 ? p1evl(x, Q_) : p1evl(x, S_);
    let y = (z * p) / q; if (a < 0) y = 2 - y; return y;
  }
  function ndtr(a) {
    const x = a * Math.SQRT1_2, z = Math.abs(x);
    if (z < Math.SQRT1_2) return 0.5 + 0.5 * erf(x);
    let y = 0.5 * erfc(z); if (x > 0) y = 1 - y; return y;
  }
  function band(a) { if (isNaN(a)) return 'nan'; return a < 30 ? (a >= 0 ? '19-29' : 'nan') : a < 40 ? '30-39' : a < 50 ? '40-49' : a < 60 ? '50-59' : a < 70 ? '60-69' : a < 200 ? '70+' : 'nan'; }

  // ---------- XGBoost 트리(JSON) 예측: float32 비교·누적(xgboost CPU 예측과 같게) ----------
  function compileBooster(model) {
    const L = model.learner, trees = L.gradient_booster.model.trees;
    const base = parseFloat(String(L.learner_model_param.base_score).replace(/[\[\]]/g, ''));
    const obj = L.objective.name;
    const T = trees.map(t => ({
      left: Int32Array.from(t.left_children), right: Int32Array.from(t.right_children), idx: Int32Array.from(t.split_indices),
      cond: Float32Array.from(t.split_conditions), dleft: Uint8Array.from(t.default_left)
    }));
    const baseMargin = obj === 'survival:aft' ? Math.fround(Math.log(base)) : Math.fround(base);
    return {
      features: L.feature_names, obj,
      margin(row) {   // row: float 배열(NaN = 결측)
        const f = row.map(v => isNaN(v) ? NaN : Math.fround(v));
        let s = baseMargin;
        for (const t of T) {
          let n = 0;
          while (t.left[n] !== -1) { const v = f[t.idx[n]]; n = isNaN(v) ? (t.dleft[n] ? t.left[n] : t.right[n]) : (v < t.cond[n] ? t.left[n] : t.right[n]); }
          s = Math.fround(s + t.cond[n]);
        }
        return s;
      },
      predict(row) { const m = this.margin(row); return obj === 'survival:aft' ? Math.fround(Math.exp(m)) : m; }
    };
  }

  // ---------- 입력 표준화(deploy_api.normalize) ----------
  function normalize(rec) {
    const X = Object.assign({}, rec);
    if (!('age_at_index' in X)) X.age_at_index = NaN;
    const s = X.sex; X.sex = [1, '1', 'M', 'm', '남'].includes(s) ? 1 : ([0, '0', '2', 'F', 'f', '여'].includes(s) ? 0 : NaN);
    for (const [k, [lo, hi]] of Object.entries(RANGE)) if (k in X) { let v = num(X[k]); if (v < lo || v > hi) v = NaN; X[k] = v; }
    return X;
  }

  // ---------- 질환 모델(deploy_api.Model) ----------
  function makeModel(dis, B) {
    const meta = B.meta, feats = meta.features, kind = meta.kind || 'aft';
    const bst = kind === 'cox' ? null : compileBooster(B.model);
    const cal = {}; if (B.calibration) for (const [h, v] of Object.entries(B.calibration)) cal[+h] = v.p;
    const qm = meta.q_module || null, gp = meta.gpop_applied ? meta.gpop : null;
    const req = meta.required.filter(k => feats.includes(k) || k === 'age_at_index' || k === 'sex')
      .concat((EXTRA_REQ[dis] || []).filter(k => feats.includes(k) || (qm && qm.features.includes(k))));
    const featSet = new Set(feats.concat(qm ? qm.features : []));
    const FILL = B.fill || null;   // 없으면 예전처럼 필수 입력 누락으로 막는다

    function eligibility(X) {
      // "예측 대상 아님"은 19세 미만과 성별 한정 암만(deploy_api.py 와 같음)
      if (X.age_at_index < 19) return [false, '19세 미만'];
      if (dis in SEX_ONLY && X.sex === 1 - SEX_ONLY[dis]) return [false, SEX_ONLY[dis] === 1 ? '여성' : '남성'];
      return [true, ''];
    }
    function prepare(X0) {
      const X = Object.assign({}, X0), ent = {};
      for (const k of feats.concat(QF)) { X[k] = num(X[k]); ent[k] = !isNaN(X[k]); }
      // 과거력 빈칸 = 없음. 기타 과거력 빈칸을 다른 항목으로 채우지 않는다(deploy_api.py 와 같음)
      for (const [f, spec] of Object.entries((qm && qm.derived) || {})) {
        const src = spec.source in X ? num(X[spec.source]) : NaN;
        const grp = spec.group === 'smoker' ? (X.smoke_former === 1 || X.smoke_current === 1) : X.alc_cur === 1;
        const has = grp && !isNaN(src);
        X[f] = has ? Math.max(Math.log1p(clip(src, 0, spec.cap)) - spec.center, spec.floor === undefined ? -Infinity : spec.floor) : 0; ent[f] = has;
      }
      const idok = !isNaN(num(X.age_at_index)) && !isNaN(num(X.sex));   // 나이·성별 빈칸 = 입력 오류(채우지 않는다)
      const imputed = {}; let reqok;
      if (!FILL) reqok = req.every(k => !isNaN(num(X[k])));
      else {
        reqok = idok; const its = FILL.items, bd = band(X.age_at_index), miss = {};
        for (const k of FILL_ITEMS) X[k] = num(X[k]);
        for (const k of FILL_ITEMS) if (k in its) miss[k] = isNaN(X[k]) && idok;
        for (const [k, m] of Object.entries(miss)) if (m) {   // 1) 성·연령대 중앙값
          const key = `${Math.trunc(X.sex)}|${bd}`; X[k] = key in its[k].median ? its[k].median[key] : its[k].median['default'];
        }
        for (const [k, m] of Object.entries(miss)) {   // 2) 방법이 회귀면 다른 검사값(1)에서 채운 값 포함)으로 예측 — 항목 순서대로
          if (!m || its[k].method !== 'reg') continue;
          const g = its[k].reg; let y = g.intercept; g.predictors.forEach((p, j) => { y += X[p] * g.coef[j]; });
          X[k] = clip(g.log ? Math.exp(y) : y, g.lo, g.hi);
        }
        for (const [k, m] of Object.entries(miss)) if (m && feats.includes(k)) imputed[k] = true;
      }
      if (feats.includes('ldl') && isNaN(X.ldl) && X.tg < 400) X.ldl = X.tchol - X.hdl - X.tg / 5;
      for (const [k, spec] of Object.entries(meta.impute)) {
        if (!feats.includes(k) || !isNaN(X[k]) || !reqok) continue;
        if (spec.kind === 'linear') {
          let y = spec.intercept; spec.predictors.forEach((p, j) => { y += num(X[p]) * spec.coef[j]; });
          X[k] = clip(spec.log ? Math.exp(y) : y, spec.lo, spec.hi);
        } else {
          const key = `${Math.trunc(X.sex)}|${band(X.age_at_index)}`;
          X[k] = key in spec.by_sex_band ? spec.by_sex_band[key] : spec.default;
        }
        imputed[k] = true;
      }
      for (const k of feats) if (k.startsWith('hx_') && isNaN(X[k])) { imputed[k] = true; X[k] = ((meta.blank_fill || {})[k] !== undefined) ? meta.blank_fill[k] : 0; }
      return { X, ent, imputed, reqok, idok };
    }
    const qShift = (X, sign) => {   // 문진 모듈: 빈칸 = 평균(이동 0)
      let s = 0; qm.features.forEach((k, j) => { const v = k in X ? num(X[k]) : NaN; s += ((isNaN(v) ? qm.mean[j] : v) - qm.mean[j]) * qm.beta[j]; }); return sign * s;
    };
    const shift = X => {
      const p = gp.params[X.sex === 1 ? '1' : '0']; return interp(X.age_at_index, p.age_mid, p.shift);
    };
    function coxZ(X) {
      const a = X.age_at_index, u = (a - 50) / 10, g = k => (k in X ? num(X[k]) : 0);
      const bmi = g('bmi'), hxd = g('hx_dm'), fpg = g('fpg');
      return { age: a, age2: u * u, age3: u * u * u, male: X.sex, bmi25: +(bmi >= 25), bmi25_post: +(bmi >= 25 && a >= 50), dm: +(hxd === 1 || fpg >= 126),
        hx_dm: +(hxd === 1), hx_htn: +(g('hx_htn') === 1), hx_thyroid: clip(g('hx_thyroid'), 0, 1), hx_nulliparous: +(g('hx_nulliparous') === 1) };
    }
    const tz = (t, z) => ('w_age' in t) ? Math.log1p(interp(z.age, t.w_age.age, t.w_age.w) * (t.rr - 1)) * z[t.name] - t.mean : t.beta * (z[t.name] - t.mean);
    function risk(X) {
      const out = {}; let prev = null;
      const d = gp ? shift(X) : 0;
      if (kind === 'cox') {
        const z = coxZ(X); let lp = meta.cox.terms.reduce((s, t) => s + tz(t, z), 0);
        if (qm) lp += qShift(X, -1);
        for (const h of H) {
          let p = 1 - Math.exp(-meta.cox.H0[String(h)] * Math.exp(lp));
          if (gp) p = icll(cll(p) + d);
          if (prev !== null) p = Math.max(p, prev); out[h] = p; prev = p;
        }
        return out;
      }
      let m = Math.log(Math.max(bst.predict(feats.map(k => X[k])), 1e-6));
      if (qm) m += qShift(X, 1);
      for (const h of H) {
        const f = ndtr((Math.log(h) - m) / meta.sigma);
        let p = h in cal ? interp(lg(f), GRID_X, cal[h]) : f;
        if (gp) p = icll(cll(p) + d);
        if (prev !== null) p = Math.max(p, prev); out[h] = p; prev = p;
      }
      return out;
    }
    function yearly(P) {
      const lh = H.map(Math.log), c = H.map(h => cll(P[h])); let mx = -Infinity;
      return Array.from({ length: 10 }, (_, i) => { const v = icll(interp(Math.log(i + 1), lh, c)); mx = Math.max(mx, v); return mx; });
    }
    function predict(rec) {   // deploy_api.Model.predict(1행)
      const X = normalize(rec);
      const qblank = (qm ? QF.filter(q => qm.features.includes(q)) : []).filter(q => !(q in X) || isNaN(num(X[q])));   // 문진 빈칸(모듈 평균) — imputed 에 표시
      const [elig, why] = eligibility(X);
      const { X: Xp, reqok, imputed, idok } = prepare(X);
      const run = elig && reqok && idok;
      const o = { disease: dis, model_version: B.version, eligible: elig && idok,
        status: !idok ? '입력 오류' : (!elig ? '예측 대상 아님' : (!reqok ? '필수 입력 누락' : '정상')),
        reason: !idok ? '나이·성별 없음(스크래핑 확인 필요)' : (!elig ? why : (!reqok ? '필수 입력: ' + req.join(',') : '')),
        risk_1y: NaN, risk_5y: NaN, risk_10y: NaN, risk_by_year: null, imputed: [], input_impact: '' };
      if (run) {
        o.imputed = [...new Set(feats.filter(k => imputed[k] && !k.startsWith('hx_')).concat(qblank.map(q => Q_KEY[q])))];
        const imp = (FILL || {}).impact || {};
        if (o.imputed.length) o.input_impact = o.imputed.map(k => (imp[k] || {}).grade || '하').reduce((a, b) => (GRADE[b] > GRADE[a] ? b : a));
        const P = risk(Xp), dg = DIGITS_BY[dis] || DIGITS;
        for (const h of OUT_H) o[`risk_${h}y`] = npRound(P[h], dg);
        o.risk_by_year = yearly(P).map(v => pyRound(v, dg));
      }
      return o;
    }
    return { dis, meta, version: B.version, feats, featSet, req, predict };
  }

  // ---------- 기준 인구(anyfit_api.Reference) ----------
  function refStats(R, r, s, a) {
    const none = { STATISTIC_DIFF: null, PROBABILITY_RANK: null, STATISTIC_RATIO: null, DS_AGE: null, RISK_INDEX: null };
    if (!R || isNaN(r)) return none;
    const b = a >= 80 ? 80 : (a < 25 ? 19 : Math.trunc(Math.floor(a / 5) * 5));
    const c = R.cells[`${Math.trunc(s)}|${b}`] || R.by_sex[String(Math.trunc(s))];
    const q = c.pct; let rank = r > q[0] ? interp(r, q, q.map((_, i) => i + 1)) : 0; if (r > q[q.length - 1]) rank = 100;
    const nm = (c.normal_n || 0) >= 30 ? c.normal_mean : c.mean;
    const na = R.normal_by_age[String(Math.trunc(s))] || []; let ds = null;
    if (na.length >= 2) {
      const ages = na.map(x => x[0]); let mx = -Infinity; const m = na.map((x, i) => { mx = Math.max(mx, x[1]); return mx + i * 1e-9; });
      ds = pyRound(clip(interp(r, m, ages, 19, 90), 19, 90), 1);
    }
    return { STATISTIC_DIFF: pyRound(r - c.mean, 4), PROBABILITY_RANK: pyRound(rank, 2), STATISTIC_RATIO: (nm && nm > 0) ? pyRound(r / nm, 3) : null,
      DS_AGE: ds, RISK_INDEX: Math.trunc(Math.min(5, Math.floor(rank / 20) + 1)) };
  }

  // ---------- 애니핏 입력 → 엔진 입력(anyfit_api.from_anyfit + lifestyle) ----------
  function fromAnyfit(A, today) {
    const X = {}, flags = [], has = k => k in A && !isn(A[k]), g = k => (k in A ? num(A[k]) : NaN);
    const age = g('AGE'), yr = 'YEAR_MM_DD' in A ? num(String(A.YEAR_MM_DD).slice(0, 4)) : NaN;
    X.age_at_index = age >= 1900 ? (isNaN(yr) ? (today || new Date()).getFullYear() : yr) - age : age;
    const sx = g('SEX'); X.sex = sx === 1 ? 1 : (sx === 2 ? 0 : NaN);
    for (const [k, v] of Object.entries(NUM)) X[v] = g(k);
    if ('resWeight' in A && 'resHeight' in A && isNaN(X.bmi)) X.bmi = g('resWeight') / Math.pow(g('resHeight') / 100, 2);
    if ('OLIG_PROTE_CD' in A) { const u = A.OLIG_PROTE_CD, n = num(u); X.urine_protein = !isNaN(n) ? n : (isn(u) ? NaN : (UPRO[String(u).trim()] ?? NaN)); }
    for (const src of [HCHK, FMLY, EXTRA]) for (const [k, v] of Object.entries(src)) X[v] = g(k);
    const pl = g(PREG_LACT); X.hx_nulliparous = (pl === 0 || pl === 1) ? +(pl === 0) : NaN;
    const s = g('SMOKING');
    X.smoke_former = isNaN(s) ? NaN : +(s === 2 || s === 3); X.smoke_current = isNaN(s) ? NaN : +(s === 4 || s === 5);
    const d = g('DRINKING'); X.alc_cur = isNaN(d) ? NaN : +(d >= 2);
    // lifestyle()
    let st = g('SMOKING_STATUS'); if (!isNaN(st) && ![1, 2, 3].includes(st)) { flags.push('SMOKING_STATUS 범위 밖'); st = NaN; }
    let yrs = g('SMOKING_YEARS'); if (isNaN(yrs)) yrs = YEARS_CD[g('SMOKING_YEARS_CD')] ?? NaN;
    if (yrs < 0 || yrs > 80) { flags.push('SMOKING_YEARS 범위 밖(0–80)'); yrs = NaN; }
    let cpd = g('SMOKING_PER_DAY'); if (isNaN(cpd)) cpd = PERDAY_CD[g('SMOKING_PER_DAY_CD')] ?? NaN;
    if (cpd < 0 || cpd > 100) { flags.push('SMOKING_PER_DAY 범위 밖(0–100)'); cpd = NaN; }
    if ((st === 2 || st === 3) && (isNaN(yrs) || isNaN(cpd))) flags.push('흡연자 기간·양 빈칸(갑년 없음)');   // 상세 상태를 준 경우만
    // 정의서 엔진 코드는 SMOKING 하나뿐 — SMOKING_STATUS 가 없으면 상태는 SMOKING 에서(2·3 과거, 4·5 현재)
    const sst = s === 1 ? 1 : ((s === 2 || s === 3) ? 2 : ((s === 4 || s === 5) ? 3 : NaN));
    if (isNaN(st) && (sst === 2 || sst === 3) && (isNaN(yrs) !== isNaN(cpd))) flags.push('흡연 기간·양 중 하나만 입력(갑년 없음)');
    if (isNaN(st)) st = sst;
    if (st === 1 && (yrs > 0 || cpd > 0)) flags.push('비흡연인데 흡연 기간·양 입력(무시)');
    const pack = st === 1 ? 0 : ((st === 2 || st === 3) ? yrs * cpd / 20 : NaN);
    let dd = g('DRINKING_DAYS_WEEK'); if (dd < 0 || dd > 7) { flags.push('DRINKING_DAYS_WEEK 범위 밖(0–7)'); dd = NaN; }
    let per = 0, anyc = false;
    for (const [c, t] of Object.entries(DRINK_COL)) { const v = g(c); per += (isNaN(v) ? 0 : clip(v, 0, 50)) * DRINK_G[t]; anyc = anyc || !isNaN(v); }
    if ('DRINKING_AMOUNT' in A) {
      let tp = '소주';
      if ('DRINKING_TYPE' in A) { const x = A.DRINKING_TYPE; tp = DRINK_TYPE_CD[x] ?? DRINK_TYPE_CD[String(x).trim().toLowerCase()] ?? String(x).trim(); }
      const g1 = DRINK_G[tp], amt = g('DRINKING_AMOUNT');
      if (!isNaN(amt) && g1 === undefined) flags.push('주종 모름(소주로 계산)');
      if (!isNaN(amt) && !anyc) per = clip(amt, 0, 50) * (g1 === undefined ? DRINK_G['소주'] : g1);
      anyc = anyc || !isNaN(amt);
    }
    if (!anyc) per = NaN;
    if (dd === 0 && per > 0) flags.push('음주 0일인데 1회 음주량 입력(무시)');
    const alcg = dd === 0 ? 0 : dd * per;
    if (!isNaN(st)) { X.smoke_former = +(st === 2); X.smoke_current = +(st === 3); }
    if (!isNaN(dd)) X.alc_cur = +(dd > 0);
    X.pack_years = pack; X.alc_g_week = alcg;
    for (const [k, [lo, hi]] of Object.entries(RANGE)) if (k in X && k !== 'age_at_index' && (X[k] < lo || X[k] > hi)) X[k] = NaN;
    return { X, alc_days_week: dd, flags };
  }

  // ---------- 건강나이(health_age_api.HealthAge) ----------
  function makeHealthAge(B) {
    const meta = B.meta, bst = compileBooster(B.model), lt = { 1: meta.life_table['1'], 0: meta.life_table['0'] }, FILL = B.fill || null;
    const ages = Array.from({ length: 101 }, (_, i) => i);
    const ex = (a, s) => interp(clip(a, 0, 100), ages, s === 1 ? lt[1] : lt[0]);
    const polyval = (c, x) => c.reduce((acc, v) => acc * x + v, 0);
    function predict(rec) {
      const X = normalize(rec);
      for (const c of HA_REQ.concat(HA_OPT, Object.keys(meta.add))) X[c] = num(X[c]);
      const age = X.age_at_index, sex = X.sex, idok = !isNaN(age) && !isNaN(sex), imputed = [], bd = band(age);
      if (FILL) {   // 검사값 빈칸 채움(health_age_api 와 같은 순서): 1) 성·연령대 중앙값 2) 방법이 회귀면 다른 검사값으로 예측
        const its = FILL.items, fmiss = {};
        for (const k of HA_REQ.slice(2)) if (k in its) fmiss[k] = isNaN(X[k]) && idok;
        for (const [k, m] of Object.entries(fmiss)) if (m) { const key = `${Math.trunc(sex)}|${bd}`; X[k] = key in its[k].median ? its[k].median[key] : its[k].median['default']; }
        for (const [k, m] of Object.entries(fmiss)) {
          if (!m || its[k].method !== 'reg') continue;
          const g = its[k].reg; let y = g.intercept; g.predictors.forEach((p, j) => { y += X[p] * g.coef[j]; });
          X[k] = clip(g.log ? Math.exp(y) : y, g.lo, g.hi);
        }
        for (const [k, m] of Object.entries(fmiss)) if (m) imputed.push(k);
      }
      if (isNaN(X.ldl) && X.tg < 400) X.ldl = X.tchol - X.hdl - X.tg / 5;
      const miss = HA_REQ.filter(c => isNaN(X[c])), ok = miss.length === 0 && age >= 19;
      for (const c of HA_OPT) if (isNaN(X[c]) && !isNaN(sex) && bd !== 'nan') { X[c] = meta.impute[String(Math.trunc(sex))][bd][c]; imputed.push(c); }
      const raw = bst.predict(meta.features.map(k => isNaN(X[k]) ? 0 : X[k]));
      const exp = polyval(meta.bias[sex === 1 ? '1' : '0'], age);
      const exam = age + meta.shrink_lambda * (raw - exp);
      let add = 0; for (const [c, a] of Object.entries(meta.add)) add += (isNaN(X[c]) ? 0 : X[c]) * a;
      const ha = Math.max(exam + add, meta.min_health_age), rem = ex(ha, sex);
      const r1 = v => ok ? pyRound(v, 1) : null, a99 = isNaN(age) ? 99 : age;
      const ierr = FILL && !idok, imp = (FILL || {}).impact || {};
      return { health_age: r1(ha), delta: r1(ha - age), life_expectancy: r1(rem), life_span: r1(ha + rem), avg_life_span: r1(age + ex(age, sex)),
        status: ok ? '정상' : (ierr ? '입력 오류' : (a99 < 19 ? '대상 아님' : '필수 입력 누락')),
        reason: ok ? '' : (ierr ? '나이·성별 없음(스크래핑 확인 필요)' : (a99 < 19 ? '대상 아님(만 19세 미만)' : '필수 입력 누락: ' + miss.join(','))), imputed: imputed.join(','),
        input_impact: (ok && imputed.length) ? imputed.map(k => (imp[k] || {}).grade || '하').reduce((a, b) => (GRADE[b] > GRADE[a] ? b : a)) : '', model_version: meta.version };
    }
    return { predict, version: meta.version };
  }

  // ---------- 전체(anyfit_api.predict_anyfit, 1명) ----------
  return function RiskEngine(BUNDLES) {
    const models = {}, refs = {};
    for (const [dis] of DIS_OUT) if (BUNDLES[dis]) { models[dis] = makeModel(dis, BUNDLES[dis]); refs[dis] = BUNDLES[dis].reference || null; }
    const HA = BUNDLES.ha33 ? makeHealthAge(BUNDLES.ha33) : null;
    const r1n = v => (isn(v) ? null : pyRound(v, 1));

    function factors(M, X, base) {
      const ctrl = [], unc = [];
      if (isNaN(base)) return [ctrl, unc];
      for (const [v, name, rec, how] of CTRL) {
        if (!M.featSet.has(v) || !(v in X)) continue;
        if (M.dis in CTRL_ALLOW && !CTRL_ALLOW[M.dis].includes(name)) continue;
        const cur = X[v], X2 = Object.assign({}, X); let bad, tgt = null;
        if (how === 'down' || how === 'up') {
          tgt = X.sex === 1 ? rec[1] : rec[0]; bad = how === 'down' ? cur > tgt : cur < tgt; if (bad) X2[v] = tgt;
        } else if (how === 'quit') { bad = cur === 1; if (bad) { X2.smoke_current = 0; X2.smoke_former = 1; } }
        else { bad = cur === 1; if (bad) X2[v] = 0; }
        if (!bad || isNaN(cur)) continue;
        const r2 = M.predict(X2).risk_10y, ch = (base - r2) / base * 100;
        if (ch > 0) ctrl.push({ FACTOR_NAME: name, CHANGE_RISK_RATIO: pyRound(ch, 2), VALUE_RECOMMENDED: rec === null ? null : tgt, _var: v });
      }
      for (const [v, name] of UNCTRL) {
        if (!M.featSet.has(v) || !(v in X)) continue;
        if (M.dis in UNCTRL_ALLOW && !UNCTRL_ALLOW[M.dis].includes(name)) continue;
        if (X[v] !== 1) continue;
        const r2 = M.predict(Object.assign({}, X, { [v]: 0 })).risk_10y, ch = (base - r2) / base * 100;
        if (ch > 0) unc.push({ FACTOR_NAME: name, CHANGE_RISK_RATIO: pyRound(ch, 2), _var: v });
      }
      const by = (a, b) => b.CHANGE_RISK_RATIO - a.CHANGE_RISK_RATIO;
      return [ctrl.sort(by), unc.sort(by)];
    }

    function predictAnyfit(A, opts) {
      const { X, alc_days_week, flags } = fromAnyfit(A, opts && opts.today);
      const out = { input: { age: r1n(X.age_at_index), sex: isNaN(X.sex) ? null : X.sex, smoke_former: r1n(X.smoke_former), smoke_current: r1n(X.smoke_current),
        pack_years: r1n(X.pack_years), alc_cur: r1n(X.alc_cur), alc_days_week: r1n(alc_days_week), alc_g_week: r1n(X.alc_g_week), input_flags: flags } };
      for (const [dis, name] of DIS_OUT) {
        const M = models[dis]; if (!M) continue;
        const O = M.predict(X), r = O.risk_10y;
        const st = refStats(refs[dis], r, X.sex, X.age_at_index);
        const [ctrl, unc] = factors(M, X, r);
        const fmt = L => L.map((d, k) => {
          let val = null;
          if (d.FACTOR_NAME in NUM) { const x = X[NUM[d.FACTOR_NAME]]; val = isNaN(x) ? null : pyRound(x, 2); }
          else if (d.FACTOR_NAME in A && !isn(A[d.FACTOR_NAME])) { const x = A[d.FACTOR_NAME]; val = typeof x === 'number' ? x : x; }
          const o = { RANK: k + 1, FACTOR_NAME: d.FACTOR_NAME, CHANGE_RISK_RATIO: d.CHANGE_RISK_RATIO, VALUE_CURRENT: val };
          if ('VALUE_RECOMMENDED' in d) o.VALUE_RECOMMENDED = d.VALUE_RECOMMENDED;
          return o;
        });
        out[name] = Object.assign({ STATUS: O.status, REASON: O.reason || null, MODEL_VERSION: M.version, PROBABILITY: isNaN(r) ? null : r,
          PROBABILITY_BY_YEAR: O.risk_by_year }, st, { CONTROLLABLE_FACTOR: fmt(ctrl), UNCONTROLLABLE_FACTOR: fmt(unc),
          IMPUTED_INPUTS: O.imputed.map(k => IMP_CODE[k] || k), INPUT_IMPACT: O.input_impact || null });
      }
      if (HA) {
        const O = HA.predict(X);
        Object.assign(out, { HEALTH_AGE: O.health_age, LIFE_EXPECTANCY: O.life_expectancy, LIFE_SPAN: O.life_span,
          HEALTH_AGE_INFO: { STATUS: O.status, REASON: O.reason || null, IMPUTED: O.imputed || null, INPUT_IMPACT: O.input_impact || null, AVG_LIFE_SPAN: O.avg_life_span, MODEL_VERSION: HA.version } });
      }
      return out;
    }
    return { predictAnyfit, models, DIS_OUT, fromAnyfit, _ndtr: ndtr };
  };
});
