# 동시 접속 부하 시험: 여러 사용자(스레드)가 동시에 predict_anyfit 을 부를 때 요청당 응답 시간·처리량, 결과가 순차 계산과 같은지
# usage: python tests/bench_concurrency.py [동시 사용자 수 ...]   (기본 1 2 4 8 16 32 64, 사용자마다 요청 5번, 요청 = 1명 검진 1건)
#   결과 같음 = 동시에 보낸 요청의 결과가 같은 요청을 혼자 보낸 결과와 같은지
#   REQ_RECORDS=n 이면 요청당 검진 n건, ANYFIT_WORKERS 로 작업 프로세스 상한
import sys, os, json, time
from concurrent.futures import ThreadPoolExecutor
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'api'))
import anyfit_api as A
D = os.path.join(ROOT, 'deploy')
cases = json.load(open(os.path.join(ROOT, 'tests', 'cases.json'), encoding='utf-8'))
levels = [int(x) for x in sys.argv[1:]] or [1, 2, 4, 8, 16, 32, 64]
K, PER_USER = int(os.environ.get('REQ_RECORDS', '1')), 5
dump = lambda o: json.dumps(o, sort_keys=True, default=str)
req = lambda j: [cases[(j * K + i) % len(cases)] for i in range(K)]   # 요청마다 다른 사람

t = time.perf_counter(); A.predict_anyfit(req(0), deploy_dir=D); warm = time.perf_counter() - t   # 작업 프로세스 시작
# 기준값 = 같은 요청을 혼자(동시 요청 없이) 보낸 결과. 여러 명을 한 요청에 묶으면 빈 입력 열이 다른 사람 때문에 생겨 입력 경고(input_flags)가 달라질 수 있어 요청 단위로 비교한다
ref = {j: dump(json.loads(dump(A.predict_anyfit(req(j), deploy_dir=D)))) for j in range(len(cases))}
print(f'CPU {os.cpu_count()}, 작업 프로세스 {A._POOL_N}, 요청당 검진 {K}건, 첫 호출(시작 포함) {warm:.2f}초')
print('| 동시 사용자 | 요청 수 | 처리량(요청/초) | 응답 p50 | 응답 p95 | 응답 최대 | 결과 같음 |\n|---|---|---|---|---|---|---|')

def user(u):
    out = []
    for r in range(PER_USER):
        j = (u * PER_USER + r) % len(cases)
        t = time.perf_counter(); res = dump(json.loads(dump(A.predict_anyfit(req(j), deploy_dir=D)))); out.append((time.perf_counter() - t, res == ref[j]))
    return out

for n in levels:
    t0 = time.perf_counter()
    with ThreadPoolExecutor(n) as ex: rs = [x for o in ex.map(user, range(n)) for x in o]
    wall = time.perf_counter() - t0
    lat = sorted(x for x, _ in rs); q = lambda p: lat[min(len(lat) - 1, int(p * len(lat)))]
    print(f'| {n} | {len(rs)} | {len(rs) / wall:.2f} | {q(0.5):.2f}초 | {q(0.95):.2f}초 | {lat[-1]:.2f}초 | {all(ok for _, ok in rs)} |', flush=True)
