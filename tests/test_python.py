# Python API(api/anyfit_api.py)가 tests/expected_python.json 과 같은 값을 내는지 점검
# usage: python tests/test_python.py   (레포 최상위에서, requirements.txt 설치 후)
import sys, os, json, math
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'api'))
import anyfit_api
anyfit_api.DIS_OUT['obe33'] = 'Obesity'   # 기대값은 비만(정의서 출력에 없음)까지 포함해 만들었다

cases = json.load(open(os.path.join(ROOT, 'tests', 'cases.json'), encoding='utf-8'))
exp = json.load(open(os.path.join(ROOT, 'tests', 'expected_python.json'), encoding='utf-8'))
got = json.loads(json.dumps(anyfit_api.predict_anyfit(cases, deploy_dir=os.path.join(ROOT, 'deploy')),
                            default=lambda o: o.item() if hasattr(o, 'item') else str(o)))
fails, n = [], 0
def walk(a, b, where):
    global n
    if isinstance(a, dict):
        for k in a: walk(a[k], b.get(k) if isinstance(b, dict) else None, f'{where}.{k}')
    elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for i, (x, y) in enumerate(zip(a, b)): walk(x, y, f'{where}[{i}]')
    else:
        n += 1
        if isinstance(b, float) and math.isnan(b): b = None   # 건강나이 대상 아님 = NaN(알려진 출력 형식, README)
        if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
            if abs(a - b) > 1e-9: fails.append(f'{where}: 기대 {a} 결과 {b}')
        elif a != b: fails.append(f'{where}: 기대 {a!r} 결과 {b!r}')
for i, (a, b) in enumerate(zip(exp, got)): walk(a, b, f'case{i}')
print(f'비교 값 {n}개, 실패 {len(fails)}'); [print('  ' + f) for f in fails[:40]]
sys.exit(1 if fails else 0)
