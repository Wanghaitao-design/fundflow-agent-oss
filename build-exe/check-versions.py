# -*- coding: utf-8 -*-
"""看看刚装上的库能不能真用，顺便把版本号打出来。

为什么不直接写在 build-officer.ps1 里：PowerShell 5.1 传给外部程序时会把参数里的双引号吃掉，
python 那边收到的代码就变成 print(pandas,...) 这种，报出来的错全是假的（真踩过）。
"""
import sys

名字 = ['pandas', 'numpy', 'networkx', 'plotly', 'matplotlib', 'openpyxl', 'xlrd',
        'PyInstaller']
好, 坏 = [], []
for m in 名字:
    try:
        模块 = __import__(m)
        好.append('%s=%s' % (m, getattr(模块, '__version__', '?')))
    except Exception as 错:
        坏.append('%s：%s' % (m, 错))
print('　'.join(好))
if 坏:
    print('用不了：' + '；'.join(坏))
    sys.exit(1)
