# 실행 시간 비교: 비개선판(anyfit_api_seq, 순차) vs 개선판(anyfit_api, 질환별 병렬). 결과가 같은지도 확인한다
# usage: python tests/bench_parallel.py [건수 ...]   (기본 1 5 50)
import sys, os, json, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'api'))
import anyfit_api as A
import anyfit_api_seq as S
D = os.path.join(ROOT, 'deploy')
cases = json.load(open(os.path.join(ROOT, 'tests', 'cases.json'), encoding='utf-8'))
sizes = [int(x) for x in sys.argv[1:]] or [1, 5, 50]
recs = lambda n: (cases * (n // len(cases) + 1))[:n]
dump = lambda o: json.dumps(o, sort_keys=True, default=str)

def timed(f, n):
    t = time.perf_counter(); out = f(recs(n), deploy_dir=D); return time.perf_counter() - t, out

print(f'작업 수(자동) {A._usable_workers(17)}, CPU {os.cpu_count()}')
t0, _ = timed(A.predict_anyfit, 1); print(f'개선판 첫 호출(작업 프로세스 시작 포함) {t0:.2f}초')
print('| 건수 | 비개선판(순차) | 개선판(병렬) | 결과 같음 |\n|---|---|---|---|')
for n in sizes:
    ts, a = timed(S.predict_anyfit, n); tp, b = timed(A.predict_anyfit, n)
    print(f'| {n} | {ts:.2f}초 | {tp:.2f}초 | {dump(a) == dump(b)} |')
