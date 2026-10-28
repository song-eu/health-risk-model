# deploy/ 의 모델 JSON 을 모두 넣은 시험 페이지 web/risk_test.html 을 만든다(표준 라이브러리만 사용)
# usage: python web/build_html.py   (레포 최상위에서)
import json, hashlib, os, datetime
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEP, SRC = os.path.join(ROOT, 'deploy'), os.path.join(ROOT, 'web', 'src')

def rd(p): return json.load(open(p, encoding='utf-8')) if os.path.exists(p) else None
B = {}
for d in sorted(os.listdir(DEP)):
    f = lambda n: os.path.join(DEP, d, n)
    if d == 'ha33':
        B[d] = dict(meta=rd(f('meta.json')), model=rd(f('health_age.json')), fill=rd(f('fill.json'))); continue
    meta = rd(f('meta.json')); cox = meta.get('kind') == 'cox'
    raw = open(f('meta.json'), 'rb').read() if cox else open(f('model.json'), 'rb').read() + open(f('meta.json'), 'rb').read()
    B[d] = dict(meta=meta, model=None if cox else rd(f('model.json')), calibration=None if cox else rd(f('calibration.json')),
                reference=rd(f('reference.json')), fill=rd(f('fill.json')), version=hashlib.sha256(raw).hexdigest()[:16])   # deploy_api.Model.version 과 같은 값
bundles = json.dumps(B, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/')
html = open(os.path.join(SRC, 'template.html'), encoding='utf-8').read()
html = html.replace('/*BUNDLES*/', bundles, 1).replace('/*ENGINE*/', open(os.path.join(SRC, 'engine.js'), encoding='utf-8').read(), 1)
html = html.replace('/*BUILD*/', f'build {datetime.date.today().isoformat()}', 1)
out = os.path.join(ROOT, 'web', 'risk_test.html')
open(out, 'w', encoding='utf-8', newline='\n').write(html)
print(out, f'{os.path.getsize(out) / 1e6:.1f} MB,', len(B), 'bundles')
