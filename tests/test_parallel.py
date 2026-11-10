# 병렬 계산 점검: 개선판(anyfit_api, 병렬) = 비개선판(anyfit_api_seq, 순차), 병렬이 실패해도(자원 부족 흉내) 오류 없이 순차로 같은 결과
# usage: python tests/test_parallel.py
import sys, os, json
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'api'))
import anyfit_api as A
import anyfit_api_seq as S
D = os.path.join(ROOT, 'deploy')
cases = json.load(open(os.path.join(ROOT, 'tests', 'cases.json'), encoding='utf-8'))[:10]
dump = lambda o: json.dumps(o, sort_keys=True, default=str)

ref = dump(S.predict_anyfit(cases, deploy_dir=D))   # 비개선판(순차)
os.environ['ANYFIT_WORKERS'] = '4'
ok = []
ok.append(('개선판(병렬) = 비개선판(순차)', dump(A.predict_anyfit(cases, deploy_dir=D)) == ref))
p1 = A._POOL; os.environ['ANYFIT_WORKERS'] = '6'; A.predict_anyfit(cases, deploy_dir=D)
ok.append(('작업 수가 늘어도 풀을 다시 만들지 않음', A._POOL is p1 and p1 is not None))
from concurrent.futures import ThreadPoolExecutor
with ThreadPoolExecutor(4) as T:   # 멀티스레드 서버 흉내: 동시 요청 4개
    outs = list(T.map(lambda _: dump(A.predict_anyfit(cases, deploy_dir=D)), range(4)))
ok.append(('동시 요청 4개 모두 = 비개선판', all(o == ref for o in outs) and A._POOL is p1))
os.environ['ANYFIT_WORKERS'] = '0'
ok.append(('개선판 병렬 끔(ANYFIT_WORKERS=0) = 비개선판', dump(A.predict_anyfit(cases, deploy_dir=D)) == ref))
os.environ['ANYFIT_WORKERS'] = '4'
real_pool = A._pool
A._pool = lambda n: (_ for _ in ()).throw(OSError('자원 부족 흉내'))
ok.append(('병렬 실패 → 순차로 같은 결과', dump(A.predict_anyfit(cases, deploy_dir=D)) == ref)); ok.append(('실패 뒤 병렬 끔', A._POOL_OFF))
A._pool, A._POOL_OFF = real_pool, False
os.environ['ANYFIT_WORKERS'] = 'abc'; ok.append(('잘못된 ANYFIT_WORKERS 도 오류 없음', A._usable_workers(17) >= 0))
for name, v in ok: print(('통과' if v else '실패'), name)
sys.exit(0 if all(v for _, v in ok) else 1)
