"""fundflow-toolkit MCP stdio 入口。"""
import logging
import os
import subprocess
import sys
import time

# 避免 Windows joblib 物理核心探测启动 PowerShell。
os.environ['LOKY_MAX_CPU_COUNT'] = '1'
from common import log, DELIVERABLES
from mcp.server.fastmcp import FastMCP
from tools import register_all

logging.basicConfig(stream=sys.stderr, level=logging.INFO)

_WARM_CODE = r'''
import json, os, sys, time, traceback
t = time.perf_counter()
m = sys.argv[1]
def st(v):
    tmp = m + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(v, f)
    os.replace(tmp, m)
    print(json.dumps(v), file=sys.stderr, flush=True)
try:
    st({'status': 'running', 'prefix': sys.prefix})
    import numpy
    import threadpoolctl
    st({'status': 'imports-ok', 'numpy_file': numpy.__file__, 'prefix': sys.prefix})
    # 2026-11-12：这里原来热的是 sklearn.cluster.KMeans——分析机已经不用它了
    # （它就是办案电脑上要装微软运行库、被 360 按文件名拦的那一串）。
    # 层级聚类现在是纯 numpy 手写（见 算法对照/双跑结果-2026-11-12.md），
    # 所以预热改成热 numpy 自己的运算：同样一次小矩阵乘，把 OpenBLAS 那套线程先转起来。
    随 = numpy.random.default_rng(0)
    点 = 随.normal(size=(200, 9))
    with threadpoolctl.threadpool_limits(limits=1):
        (点 @ 点.T).sum()
    st({'status': 'done', 'seconds': round(time.perf_counter() - t, 3)})
except Exception as exc:
    st({'status': 'failed', 'error': str(exc)})
    traceback.print_exc(file=sys.stderr)
'''

def _start_prewarm():
    """非阻塞子进程预热，诊断只写文件。"""
    try:
        marker = DELIVERABLES / '_warmup.json'
        marker.parent.mkdir(parents=True, exist_ok=True)
        with open(DELIVERABLES / '_prewarm.log', 'w', encoding='utf-8') as logf:
            subprocess.Popen([sys.executable, '-c', _WARM_CODE, str(marker)],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=logf,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except Exception as exc:
        log(f'子进程预热启动失败（继续运行）：{type(exc).__name__}: {exc}')

def _preload_heavy():
    """主线程预载：必须在任何 anyio 运行环境启动前完成首次加载。"""
    started = time.perf_counter()
    try:
        # 同上：热 numpy 本身（分析机现在只依赖 numpy 做聚类，不再依赖 sklearn）
        import numpy
        import threadpoolctl
        随 = numpy.random.default_rng(0)
        点 = 随.normal(size=(200, 9))
        with threadpoolctl.threadpool_limits(limits=1):
            (点 @ 点.T).sum()
        log(f'主线程预载完成：{time.perf_counter() - started:.2f}s')
    except Exception as exc:
        log(f'主线程预载失败（继续运行）：{type(exc).__name__}: {exc}')

mcp = FastMCP('fundflow-toolkit')
register_all(mcp)

if __name__ == '__main__':
    _start_prewarm()
    _preload_heavy()
    mcp.run(transport='stdio')
