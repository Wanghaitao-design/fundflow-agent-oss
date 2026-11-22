"""预热契约自检：不依赖 mcp 包，任何装了 numpy/threadpoolctl 的机器都能跑。

为什么单独有这个文件（2026-11-12）：`protocol_smoke.py` 要 `import mcp`，办案电脑和这台
开发机都可能没装（PyPI 不通时装不上），那段"预热用的库必须来自我们自己的 venv"的断言
就永远没人验过。这里把它单独抽出来：原样抽出 `server.py` 里的 `_WARM_CODE` 起一个子进程，
照 `protocol_smoke.py` 第 77 行那两个断言验一遍。

按 AGENTS.md 的自检规矩：只写「必须不崩 / 该命中必须命中」，不把具体耗时当契约。
"""
import io
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

入口 = Path(__file__).with_name('server.py')


def main():
    源码 = io.open(入口, encoding='utf-8').read()
    代码 = re.search(r"_WARM_CODE = r'''(.*?)'''", 源码, re.S).group(1)
    assert 'import sklearn' not in 代码.replace('from sklearn', 'import sklearn'), \
        '预热代码里又去热 sklearn 了（分析机已经不用它，热它只会拖慢启动）'

    目录 = Path(tempfile.mkdtemp())
    标记, 日志 = 目录 / '_warmup.json', 目录 / '_prewarm.log'
    with open(日志, 'w', encoding='utf-8') as 句柄:
        subprocess.run([sys.executable, '-X', 'utf8', '-c', 代码, str(标记)],
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=句柄,
                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    文本 = 日志.read_text(encoding='utf-8')
    assert '"status": "failed"' not in 文本, '预热子进程显式失败：\n' + 文本

    状态 = [json.loads(行) for 行 in 文本.splitlines() if 行.startswith('{')]
    assert [项.get('status') for 项 in 状态] == ['running', 'imports-ok', 'done'], 状态
    来源 = next(项['numpy_file'] for 项 in 状态 if 项.get('status') == 'imports-ok')
    assert Path(来源).resolve().is_relative_to(Path(sys.prefix).resolve()), \
        '预热用的 numpy 不在本 venv 里：' + 来源
    assert 标记.exists() and json.loads(标记.read_text(encoding='utf-8'))['status'] == 'done', 标记
    print('PREWARM PASS 预热子进程 running→imports-ok→done，numpy 来自 ' + 来源)


if __name__ == '__main__':
    main()
