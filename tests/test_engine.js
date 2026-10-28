// JS 엔진(web/src/engine.js)이 Python API(api/anyfit_api.py)와 같은 값을 내는지 점검
// usage: node tests/test_engine.js   (레포 최상위에서)
// tests/expected_python.json = Python API 로 tests/cases.json(가상 입력 83건)을 돌린 결과(anyfit_api.DIS_OUT 에 obe33 'Obesity' 를 더해 실행)
const fs = require('fs'), path = require('path'), crypto = require('crypto');
const ROOT = path.join(__dirname, '..'), DEP = path.join(ROOT, 'deploy');
const RiskEngine = require(path.join(ROOT, 'web', 'src', 'engine.js'));

function loadBundles() {
  const B = {};
  for (const d of fs.readdirSync(DEP)) {
    const f = n => path.join(DEP, d, n), rd = n => (fs.existsSync(f(n)) ? JSON.parse(fs.readFileSync(f(n), 'utf8')) : null);
    if (d === 'ha33') { B.ha33 = { meta: rd('meta.json'), model: rd('health_age.json'), fill: rd('fill.json') }; continue; }
    const meta = rd('meta.json'), cox = meta.kind === 'cox';
    const buf = cox ? fs.readFileSync(f('meta.json')) : Buffer.concat([fs.readFileSync(f('model.json')), fs.readFileSync(f('meta.json'))]);
    B[d] = { meta, model: cox ? null : rd('model.json'), calibration: cox ? null : rd('calibration.json'), reference: rd('reference.json'), fill: rd('fill.json'),
      version: crypto.createHash('sha256').update(buf).digest('hex').slice(0, 16) };
  }
  return B;
}

const E = RiskEngine(loadBundles());
const cases = JSON.parse(fs.readFileSync(path.join(__dirname, 'cases.json'), 'utf8'));
const exp = JSON.parse(fs.readFileSync(path.join(__dirname, 'expected_python.json'), 'utf8'));
const TODAY = new Date(2026, 9, 26);   // 기대값을 만든 날(AGE 가 출생연도로 온 사례)
// 허용 차이: 출력 마지막 자리 1 단위(위험은 xgboost float32 누적·반올림 경계에서 갈릴 수 있다). 나머지는 같아야 한다
function tol(where) {
  if (/CHANGE_RISK_RATIO|PROBABILITY_RANK/.test(where)) return 0.0101;          // 소수 2자리
  if (/STATISTIC_RATIO/.test(where)) return 0.00101;                             // 소수 3자리
  if (/DS_AGE|HEALTH_AGE|LIFE|AVG_LIFE_SPAN/.test(where)) return 0.101;          // 소수 1자리
  if (/PROBABILITY|STATISTIC_DIFF/.test(where)) return 1.01e-4;                  // 소수 4–6자리
  return 1e-9;
}
let n = 0, exact = 0, fails = [], maxRiskDiff = 0;
function cmp(a, b, where) {
  n++;
  if (a === null || b === null || typeof a !== 'number' || typeof b !== 'number') {
    if (JSON.stringify(a) !== JSON.stringify(b)) fails.push(`${where}: python ${JSON.stringify(a)} js ${JSON.stringify(b)}`); else exact++;
    return;
  }
  const d = Math.abs(a - b);
  if (d === 0) exact++;
  if (/PROBABILITY(_BY_YEAR)?(\[|$)|STATISTIC_DIFF/.test(where)) maxRiskDiff = Math.max(maxRiskDiff, d);
  if (d > tol(where)) fails.push(`${where}: python ${a} js ${b}`);
}
function walk(a, b, where) {
  if (Array.isArray(a) && Array.isArray(b)) {
    if (/FACTOR$/.test(where)) {   // 인자 목록: 같은 인자 집합·값(동점·근소 차이로 순위가 바뀔 수 있어 이름으로 맞춘다)
      const key = x => x.FACTOR_NAME, ma = new Map(a.map(x => [key(x), x])), mb = new Map(b.map(x => [key(x), x]));
      for (const [k, x] of ma) {
        if (!mb.has(k)) { if (x.CHANGE_RISK_RATIO > 0.05) fails.push(`${where}: js 에 ${k} 없음(${x.CHANGE_RISK_RATIO}%)`); continue; }
        const y = mb.get(k); cmp(x.CHANGE_RISK_RATIO, y.CHANGE_RISK_RATIO, `${where}.${k}.CHANGE_RISK_RATIO`);
        cmp(x.VALUE_CURRENT, y.VALUE_CURRENT, `${where}.${k}.VALUE_CURRENT`);
        if ('VALUE_RECOMMENDED' in x) cmp(x.VALUE_RECOMMENDED, y.VALUE_RECOMMENDED, `${where}.${k}.VALUE_RECOMMENDED`);
      }
      for (const [k, y] of mb) if (!ma.has(k) && y.CHANGE_RISK_RATIO > 0.05) fails.push(`${where}: python 에 ${k} 없음(${y.CHANGE_RISK_RATIO}%)`);
      return;
    }
    if (a.length !== b.length && !/input_flags/.test(where)) { fails.push(`${where}: 길이 ${a.length} vs ${b.length}`); return; }
    if (/input_flags/.test(where)) { if (JSON.stringify(a) !== JSON.stringify(b)) fails.push(`${where}: python ${JSON.stringify(a)} js ${JSON.stringify(b)}`); return; }
    a.forEach((x, i) => walk(x, b[i], `${where}[${i}]`)); return;
  }
  if (a && typeof a === 'object' && b && typeof b === 'object') {
    for (const k of Object.keys(a)) { if (!(k in b)) { fails.push(`${where}.${k}: js 에 없음`); continue; } walk(a[k], b[k], `${where}.${k}`); }
    return;
  }
  cmp(a, b, where);
}
const t0 = Date.now();
cases.forEach((c, i) => walk(exp[i], E.predictAnyfit(c, { today: TODAY }), `case${i}`));
// 알려진 차이: case75(DRINKING_AMOUNT 만 있고 DRINKING_TYPE 없음) — Python 은 여러 건을 한 표로 받아 다른 건의 DRINKING_TYPE 열이 생기면
// 이 건의 주종이 빈칸으로 보여 '주종 모름' 표시를 단다. 1건 입력(앱 실제 사용)에서는 두 엔진 모두 소주로 계산하고 표시하지 않는다. 위험값은 같다.
const known = f => /^case75\.input\.input_flags/.test(f);
const real = fails.filter(f => !known(f));
console.log(`비교 값 ${n}개, 완전 일치 ${exact}, 실패 ${real.length}, 알려진 차이 ${fails.length - real.length}, 위험 최대 차이 ${maxRiskDiff.toExponential(2)}, ${Date.now() - t0} ms`);
real.slice(0, 40).forEach(f => console.log('  ' + f));
process.exit(real.length ? 1 : 0);
