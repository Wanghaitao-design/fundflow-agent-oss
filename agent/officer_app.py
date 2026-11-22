#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""民警版窗口：选一个账单文件夹 → 点开始 → 出 Excel 名单、流向图、情况说明。

设计约束（AGENTS.md）：
  · 不联网、不上传、不写日志到外部；本机算完就算完
  · 不要求使用者装 Python、改配置、敲命令
  · 判据表（案由包）留在程序旁边，可以改表不用重新打包

命令行：
  python agent/officer_app.py            打开窗口
  python agent/officer_app.py --自检      不开窗口，自己造一份小账单跑通全链路（打包前后验家用）
"""
import os
import queue
import sys
import threading
import traceback
import webbrowser
from datetime import datetime
from pathlib import Path

# ── 路径：打包成 exe 之后，一切都以 exe 所在目录为准 ──────────────────────────
冻结模式 = bool(getattr(sys, 'frozen', False))
if 冻结模式:
    程序目录 = Path(sys.executable).resolve().parent
else:
    程序目录 = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(程序目录))
    sys.path.insert(0, str(程序目录 / 'agent' / 'mcp_server'))

# ── 判据表（"什么算异常"那几张表）：打包后优先用软件旁边那一份 ──────────────
# 这样民警拿 Excel 改完，下次打开软件就生效，不用重新打包。
# 注意：下面这段必须在 import officer_pack 之前跑完——officer_pack 一进来就会
# 把词表和门槛数读成常量，晚一步改路径就没用了。
import case_pack as _案由包模块  # noqa: E402

外置判据表 = 程序目录 / 'case_packs'
判据表读不出来 = ''
if 冻结模式 and 外置判据表.is_dir():
    _案由包模块.PACKS = 外置判据表
    判据表来源 = '软件旁边的 case_packs 文件夹（用 Excel 改完，下次打开软件就生效）'
elif 冻结模式:
    判据表来源 = '打进软件里的那一份（改它要重新打包）：' + str(_案由包模块.PACKS)
else:
    判据表来源 = str(_案由包模块.PACKS)
try:
    # 一开门就当场读一遍：表被改坏了当场就说，不等他点了开始才发现
    判据表一句话 = _案由包模块.CasePack().describe()
except Exception as 错:
    判据表读不出来 = '%s: %s' % (type(错).__name__, 错)
    判据表一句话 = '读不出来：' + 判据表读不出来

import officer_pack  # noqa: E402  必须在案由包路径设好之后再导


def 落字到磁盘(名, 文):
    """把字写到能写的地方（打包成 exe 之后没有黑窗口，看不见的错也得留下纸）。"""
    import tempfile
    落 = []
    for 目录 in (程序目录, Path(tempfile.gettempdir())):
        try:
            (Path(目录) / 名).write_text(文, encoding='utf-8')
            落.append(str(Path(目录) / 名))
        except Exception:
            continue
    return 落


def 记崩溃(信息):
    """出错就写进软件旁边的《出了点问题.txt》，民警照着这个文件发回来就行。"""
    文 = ('软件出错了。把这个文件发给做软件的人，不用自己琢磨：\n'
         + datetime.now().strftime('%Y-%m-%d %H:%M:%S') + '\n\n' + 信息)
    try:
        落字到磁盘('出了点问题.txt', 文)
    except Exception:
        pass


def 打开位置(路径):
    """按系统打开文件夹或文件；失败也不许崩。"""
    try:
        if os.name == 'nt':
            os.startfile(str(路径))  # noqa: E401
        elif hasattr(os, 'startfile'):
            os.startfile(str(路径))
        else:
            import subprocess
            subprocess.Popen(['xdg-open', str(路径)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False


def _运行库缺失():
    """真用不了的库必须一开门就看见。

    2026-11-12 改过：分层判定已经换成 numpy 手写，不再用 sklearn，
    原来那句"缺 sklearn 就用简易算法"是句谎话——打包出去的软件里根本没有
    sklearn，每台办案电脑都会白白弹一次红字。现在只查真在用的三样。
    """
    for 模块, 名字 in (('numpy', '数学计算库'), ('pandas', '表格库'), ('matplotlib', '画图库')):
        try:
            __import__(模块)
        except Exception as 错:
            return ('这台电脑上的%s（%s）用不了，%s：软件算不出可靠结果，'
                    '先别把结果拿去用。可以试试双击软件文件夹里的 vc_redist.x64.exe'
                    '（微软运行库，装一次一分钟），不行就找信息科同事或者把'
                    '《出了点问题.txt》发回来。' % (名字, 模块, type(错).__name__))
    return 

def 自检():
    """不开窗口，自己造两份微信账单跑一遍。返回 (是否通过, 日志, 输出目录)。"""
    import tempfile
    from openpyxl import Workbook
    临时 = Path(tempfile.mkdtemp(prefix='officer_selftest_'))
    账单 = 临时 / '账单'
    账单.mkdir()
    行 = ['交易时间', '交易对方账号', '交易对方', '收/支', '金额', '商户单号', '支付方式', '商品', '备注']
    数据 = {
        'syn_bill_A001_微信.xlsx': [('2026-03-01 20:11:00', 'B002', 'B002', '收入', 600.0, 'T1', '零钱', '合成', '合成充值'),
                                    ('2026-03-02 21:05:00', 'B002', 'B002', '收入', 600.0, 'T2', '零钱', '合成', '合成充值'),
                                    ('2026-03-03 22:30:00', 'C009', 'C009', '支出', 1800.0, 'T3', '零钱', '合成', '合成结算')],
        'syn_bill_B002_微信.xlsx': [('2026-03-01 20:11:00', 'A001', 'A001', '支出', 600.0, 'T1', '零钱', '合成', '合成充值'),
                                    ('2026-03-02 21:05:00', 'A001', 'A001', '支出', 600.0, 'T2', '零钱', '合成', '合成充值')],
    }
    for 文件名, 行数据 in 数据.items():
        本 = Workbook()
        页 = 本.active
        页.append(行)
        for r in 行数据:
            页.append(list(r))
        本.save(账单 / 文件名)
    日志 = []
    原stdout = sys.stdout
    try:
        import io
        缓冲 = io.StringIO()
        sys.stdout = 缓冲
        输出 = officer_pack.main(str(账单), 输出目录=str(临时 / '结果'))
        sys.stdout = 原stdout
        日志.append(缓冲.getvalue())
    except Exception:
        sys.stdout = 原stdout
        return False, traceback.format_exc(), None
    应有 = ['1_人员名单.xlsx', '2_资金流向图.png', '3_情况说明.txt']
    缺 = [f for f in 应有 if not (Path(输出) / f).is_file()]
    if 缺:
        return False, '缺产物：' + '、'.join(缺) + '\n' + ''.join(日志), 输出
    全文 = ''.join(日志)
    响 = [ln for ln in 全文.splitlines() if ln.startswith('!!')]
    if 响:
        return False, ('这一轮分析里有%d条要紧提醒，不能算通过：\n%s\n%s'
                       % (len(响), '\n'.join(响), 全文)), 输出
    return True, 全文 + '\n产物齐全：' + '、'.join(应有), 输出


class 窗口:

    def __init__(self, tk, ttk):
        import tkinter as tk_
        self.tk, self.ttk = tk, ttk
        self.根 = tk.Tk()
        self.根.title('网赌资金研判 · 民警版')
        self.根.geometry('760x560')
        self.任务中 = False
        self.结果目录 = None
        self.消息队列 = queue.Queue()

        头 = tk.Frame(self.根, padx=14, pady=10)
        头.pack(fill='x')
        ttk.Label(头, text='网赌资金研判 · 民警版', font=('Microsoft YaHei UI', 15, 'bold')).pack(anchor='w')
        ttk.Label(头, text='把微信、支付宝、银行导出的账单表格放进一个文件夹，选进来，点开始。'
                           '本程序不联网，数据不出这台电脑。',
                  foreground='#57606a', wraplength=690, justify='left').pack(anchor='w', pady=(4, 0))
        缺运行库 = _运行库缺失()
        if 缺运行库:
            tk.Label(头, text=缺运行库, foreground='#cf222e', wraplength=690,
                     justify='left', font=('Microsoft YaHei UI', 10, 'bold')).pack(
                anchor='w', pady=(6, 0))

        # 判据表用的哪一份，写在界面上：答辩和办案都要能回答"你这套标准是谁的表"
        if 判据表读不出来:
            tk.Label(头, text='判据表读不出来：' + 判据表读不出来 +
                              '\n拿 Excel 打开软件旁边 case_packs 里的表改回来，改完重开软件。',
                     foreground='#cf222e', wraplength=690, justify='left',
                     font=('Microsoft YaHei UI', 10, 'bold')).pack(anchor='w', pady=(6, 0))
        else:
            ttk.Label(头, text='判据表：' + 判据表一句话 + '　位置：' + 判据表来源,
                      foreground='#57606a', wraplength=690,
                      justify='left').pack(anchor='w', pady=(6, 0))

        路径区 = tk.Frame(self.根, padx=14)
        路径区.pack(fill='x', pady=(6, 0))
        ttk.Label(路径区, text='账单文件夹').grid(row=0, column=0, sticky='w')
        self.路径框 = ttk.Entry(路径区, width=64)
        self.路径框.grid(row=0, column=1, padx=8, sticky='ew')
        路径区.columnconfigure(1, weight=1)
        ttk.Button(路径区, text='选择文件夹…', command=self.选文件夹).grid(row=0, column=2)

        选项 = tk.Frame(self.根, padx=14, pady=6)
        选项.pack(fill='x')
        ttk.Label(选项, text='身份表（可选，有实名对照就选）').grid(row=0, column=0, sticky='w')
        self.身份框 = ttk.Entry(选项, width=52)
        self.身份框.grid(row=0, column=1, padx=8, sticky='ew')
        选项.columnconfigure(1, weight=1)
        ttk.Button(选项, text='选择身份表…', command=self.选身份表).grid(row=0, column=2)

        按钮区 = tk.Frame(self.根, padx=14, pady=8)
        按钮区.pack(fill='x')
        self.开始钮 = ttk.Button(按钮区, text='开 始 分 析', command=self.开始)
        self.开始钮.pack(side='left')
        ttk.Button(按钮区, text='打开结果文件夹', command=self.开结果).pack(side='left', padx=8)
        ttk.Button(按钮区, text='自检（不用账单）', command=self.跑自检).pack(side='left')
        self.状态 = ttk.Label(按钮区, text='就绪', foreground='#1a7f37')
        self.状态.pack(side='right')

        self.文本 = tk.Text(self.根, height=18, wrap='word', state='disabled',
                           font=('Microsoft YaHei UI', 10))
        self.文本.pack(fill='both', expand=True, padx=14, pady=(0, 6))

        ttk.Label(self.根, text='提示：结论只用于安排排查先后，不是定性；每条都能翻回原表核对（表里标了文件名和行号）。',
                  foreground='#57606a', wraplength=720, justify='left').pack(anchor='w', padx=14, pady=(0, 10))

        上次的 = Path.home() / '.fundflow_上次目录.txt'
        try:
            if 上次的.is_file():
                self.路径框.insert(0, 上次的.read_text(encoding='utf-8').strip())
        except Exception:
            pass
        self.根.after(120, self.收消息)

    # ── 交互 ────────────────────────────────────────────────
    def 写(self, 文字):
        self.文本.configure(state='normal')
        self.文本.insert('end', 文字.rstrip('\n') + '\n')
        self.文本.see('end')
        self.文本.configure(state='disabled')

    def 选文件夹(self):
        from tkinter import filedialog
        选 = filedialog.askdirectory(title='选装账单的文件夹', initialdir=self.路径框.get() or str(Path.home()))
        if 选:
            self.路径框.delete(0, 'end')
            self.路径框.insert(0, 选)

    def 选身份表(self):
        from tkinter import filedialog
        选 = filedialog.askopenfilename(title='选身份对照表', filetypes=[('表格', '*.xlsx *.xls *.csv *.et')])
        if 选:
            self.身份框.delete(0, 'end')
            self.身份框.insert(0, 选)

    def 开始(self):
        if self.任务中:
            return
        目录 = self.路径框.get().strip()
        if not 目录 or not Path(目录).is_dir():
            self.写('先点「选择文件夹…」，选那个装着账单表格的文件夹。')
            return
        身份 = self.身份框.get().strip() or None
        if 身份 and not Path(身份).is_file():
            self.写('身份表路径不对：' + 身份)
            return
        try:
            (Path.home() / '.fundflow_上次目录.txt').write_text(目录, encoding='utf-8')
        except Exception:
            pass
        self.任务中 = True
        self.开始钮.configure(state='disabled')
        self.状态.configure(text='分析中…', foreground='#bf8700')
        self.写('\n=== 开始：' + 目录 + ' ===')

        def 干():
            try:
                输出 = officer_pack.main(目录, 身份)
                self.消息队列.put(('好', str(输出)))
            except Exception:
                self.消息队列.put(('坏', traceback.format_exc()))
        threading.Thread(target=干, daemon=True).start()

    def 跑自检(self):
        if self.任务中:
            return
        self.任务中 = True
        self.开始钮.configure(state='disabled')
        self.状态.configure(text='自检中…', foreground='#bf8700')
        self.写('\n=== 自检：自己造两份账单跑一遍 ===')

        def 干():
            try:
                过, 日志, 输出 = 自检()
                self.消息队列.put(('自检好' if 过 else '坏', (日志 or '') + ('\n自检通过' if 过 else '\n自检失败')))
                if 过 and 输出:
                    self.结果目录 = str(输出)
            except Exception:
                self.消息队列.put(('坏', traceback.format_exc()))
        threading.Thread(target=干, daemon=True).start()

    def 开结果(self):
        if not self.结果目录:
            self.写('还没有结果。先跑一次分析。')
            return
        if not 打开位置(self.结果目录):
            self.写('打不开文件夹，请手工到：' + self.结果目录)

    def 收消息(self):
        try:
            while True:
                类, 内容 = self.消息队列.get_nowait()
                if 类 == '好':
                    self.结果目录 = 内容
                    self.写('结果在：' + 内容)
                    self.写('里面三样：1_人员名单.xlsx、2_资金流向图.png、3_情况说明.txt')
                    self.状态.configure(text='做完了', foreground='#1a7f37')
                    打开位置(内容)
                elif 类 == '自检好':
                    self.写(内容)
                    self.状态.configure(text='自检通过', foreground='#1a7f37')
                else:
                    self.写('出错了，把下面这段发给开发人员：')
                    self.写(内容)
                    self.状态.configure(text='出错', foreground='#cf222e')
                self.任务中 = False
                self.开始钮.configure(state='normal')
        except queue.Empty:
            pass
        self.根.after(150, self.收消息)

    def 跑(self):
        self.根.mainloop()


def main():
    # 窗口里哪个按钮按下去崩了，线程是闷声死的，得让它留纸
    def 线程崩了(细节):
        try:
            错 = 细节.exc_value
            记崩溃(''.join(traceback.format_exception(type(错), 错, 错.__traceback__)))
        except Exception:
            pass
    try:
        threading.excepthook = 线程崩了
    except Exception:
        pass
    if '--自检' in sys.argv or '--selftest' in sys.argv:
        抬头 = ('模式：%s\npython：%s\n软件在这里：%s\n判据表：%s\n位置：%s'
                % ('打包出来的exe' if 冻结模式 else '源码',
                   sys.version.split()[0], 程序目录, 判据表一句话, 判据表来源))
        # 先落一张"开始"的条子：万一后面直接崩掉，打包脚本至少看得见它来过
        落字到磁盘('selftest-result.txt',
                   '自检开始　%s\n%s\n（还没跑完）\n'
                   % (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 抬头))
        if 判据表读不出来:
            文 = ('自检结果：FAIL（判据表读不出来，后面的分析不用跑）\n' + 抬头)
            落字到磁盘('selftest-result.txt', 文)
            try:
                print(文)
            except Exception:
                pass
            return 1
        try:
            过, 日志, 输出 = 自检()
        except BaseException:
            过, 日志, 输出 = False, '自检这一步本身崩了：\n' + traceback.format_exc(), None
        文 = ('自检结果：' + ('PASS' if 过 else 'FAIL') + '\n产物目录：' + (str(输出) if 输出 else '') +
               '\n' + 抬头 + '\n---------------- 过程 ----------------\n%s'
               % (日志 or '(一行日志都没有)'))
        try:
            print(文)
        except Exception:
            pass
        # 窗口版 exe 没有控制台，打印的东西看不见，所以再落一份文件给打包脚本核对
        落字到磁盘('selftest-result.txt', 文)
        return 0 if 过 else 1
    import tkinter as tk
    from tkinter import ttk
    try:
        样式 = ttk.Style()
        for 名 in ('vista', 'clam', 'default'):
            if 名 in 样式.theme_names():
                样式.theme_use(名)
                break
    except Exception:
        pass
    窗口(tk, ttk).跑()
    return 0


def 主入口():
    """打出来的 exe 从这一行走进来（入口在 build-exe/entry-fundflow.py）。"""
    try:
        return main()
    except SystemExit:
        raise
    except BaseException:
        # 打包成 exe 之后没有黑窗口，异常不写下来就谁也看不见
        记崩溃(traceback.format_exc())
        raise


if __name__ == '__main__':
    sys.exit(主入口())
