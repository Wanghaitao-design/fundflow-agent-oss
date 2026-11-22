#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""在我这边（Linux）跑：生成要拷到 Windows 上的打包包。

    python3 build-exe/make-kit.py

产物：build-exe/windows-kit-日期时间.zip
里面只放跑起来必要的东西 + build-exe 那套脚本 + 一份示例账单，
不带 .venv / .git / 资料 / 输出结果 / 历史缓存（真账单永远不在其中）。
"""
import sys
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'build-exe' / ('windows-kit-' + datetime.now().strftime('%Y%m%d-%H%M') + '.zip')

顶层文件 = ['gambling_analysis.py', 'case_pack.py']
顶层目录 = ['agent', 'case_packs', 'build-exe']
不要 = ('__pycache__', '.venv', '.git', 'deliverables', 'output', '输出结果',
        '资料', '判据包', 'vendor', 'node_modules', '.agh')
不要后缀 = ('.pyc', '.zip', '.log', '.pkl', '.xlsx', '.xls', '.csv')
必须带 = ('case_packs/', 'agent/range/reports/')


def 要(path: str) -> bool:
    if any(part in 不要 for part in Path(path).parts[:-1]):
        return False
    # 判据表和分析用的样表必须带上，先放行，再按后缀排除
    if path.startswith(必须带):
        return True
    if path.endswith(不要后缀):
        return False
    return True


def main():
    条目 = []
    for f in 顶层文件:
        if (ROOT / f).is_file():
            条目.append(f)
    for d in 顶层目录:
        for p in sorted((ROOT / d).rglob('*')):
            if p.is_file():
                条 = str(p.relative_to(ROOT)).replace('\\', '/')
                if 要(条):
                    条目.append(条)
    样例 = ROOT / 'agent' / 'deliverables' / 'smoke_fixtures'
    样例名 = []
    if 样例.is_dir():
        for p in sorted(样例.glob('*.xlsx')):
            样例名.append(p)
    with zipfile.ZipFile(OUT, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for 条 in 条目:
            z.write(ROOT / 条, 'windows-kit/' + 条)
        for p in 样例名:
            z.write(p, 'windows-kit/示例账单/' + p.name)
    大小 = OUT.stat().st_size
    print('写好了：', OUT)
    print('大小：%.1f MB　文件数：%d（含示例账单 %d 份）'
          % (大小 / 1048576, len(条目) + len(样例名), len(样例名)))
    for 条 in 条目[:8]:
        print('  ', 条)
    print('   ...')
    return 0


if __name__ == '__main__':
    sys.exit(main())
