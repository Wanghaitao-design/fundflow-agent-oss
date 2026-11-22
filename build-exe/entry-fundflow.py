#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""打出来的软件（fundflow.exe）真正的入口。不是 officer_app.py 本身。

为什么要多这一层（只多一个文件，不改分析的东西）：
  1. 打包成"窗口版"exe 之后没有黑窗口，print 的话没有地方去；
  2. 更要命的是：只要"打开软件"这一步就失败（比如缺个文件、被安全软件拦了），
     程序连一行字都留不下，双击就是闪一下没了，谁也不知道为什么。
  这一层专门负责：把"还没走到分析就出事"的现场写在纸上，并且给民警弹个窗。

产出的纸（都在软件文件夹里，办案电脑上也一样）：
  启动记录.txt    每次打开都写一行，证明它真的被点开过
  运行日志.txt    程序嘴里说的话全抄在这里
  出了点问题.txt  出事的原因，发回来就能定位
"""
import sys
import tempfile
import traceback
from datetime import datetime
from pathlib import Path


def 软件目录():
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def 落纸(名, 文):
    """往软件旁边和临时目录各写一份，哪个写得动算哪个。绝不许自己崩。"""
    for 目录 in (软件目录(), Path(tempfile.gettempdir())):
        try:
            (Path(目录) / 名).write_text(文, encoding='utf-8')
        except Exception:
            continue


class 抄进日志:
    """没有黑窗口时，把 print 的话抄进《运行日志.txt》。"""

    def __init__(self):
        self.文件 = None

    def _开(self):
        if self.文件 is not None:
            return True
        for 目录 in (软件目录(), Path(tempfile.gettempdir())):
            try:
                自 = Path(目录) / '运行日志.txt'
                if 自.exists() and 自.stat().st_size > 512 * 1024:
                    自.write_text('', encoding='utf-8')      # 太长就清一次，别占民警硬盘
                self.文件 = open(自, 'a', encoding='utf-8')
                return True
            except Exception:
                continue
        return False

    def write(self, 文):
        文 = '' if 文 is None else str(文)
        try:
            if self._开():
                self.文件.write(文)
                self.文件.flush()
        except Exception:
            pass
        return len(文)

    def writelines(self, 项):
        for 一 in 项:
            self.write(一)

    def flush(self):
        try:
            if self.文件:
                self.文件.flush()
        except Exception:
            pass

    def isatty(self):
        return False

    def close(self):
        pass


def 补搜索路径():
    """跑源码时也能直接用这个入口（打包后不需要，东西都在 exe 里）。"""
    if getattr(sys, 'frozen', False):
        return
    根 = 软件目录()
    for 地 in (根, 根 / 'agent', 根 / 'agent' / 'mcp_server'):
        if str(地) not in sys.path:
            sys.path.insert(0, str(地))


def 接住打印():
    """只在打包出来的 exe 里接管；平时跑源码不动开发者的控制台。"""
    if not getattr(sys, 'frozen', False):
        return
    for 名 in ('stdout', 'stderr'):
        try:
            if getattr(sys, 名, None) is None:
                setattr(sys, 名, 抄进日志())
        except Exception:
            pass


def 弹窗告警(话):
    """双击就失败时，总得让民警看见一句话，别让他对着没反应的桌面发呆。"""
    try:
        import tkinter as tk
        from tkinter import messagebox
        根 = tk.Tk()
        根.withdraw()
        messagebox.showerror('网赌资金研判打不开', 话 + '\n\n把这个文件发给做软件的人就行：\n出了点问题.txt')
        根.destroy()
    except Exception:
        pass


def main():
    带自检 = ('--自检' in sys.argv or '--selftest' in sys.argv)
    话 = ('%s　打开方式：%s\npython：%s\n软件在这里：%s\n'
          % (datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
             '自检' if 带自检 else ('双击或别的：' + ' '.join(sys.argv[1:]) if len(sys.argv) > 1 else '双击'),
             sys.version.split()[0], 软件目录()))
    补搜索路径()
    接住打印()
    try:
        print('\n' + 话)
    except Exception:
        pass
    落纸('启动记录.txt', 话 + '（后面是分析过程，看运行日志.txt）\n')

    try:
        import officer_app
    except BaseException:
        文 = ('软件一打开就出事了，还没走到分析那一步。原因在下面：\n'
             + datetime.now().strftime('%Y-%m-%d %H:%M:%S') + '\n\n'
             + 话 + '\n' + traceback.format_exc())
        落纸('出了点问题.txt', 文)
        if 带自检:
            落纸('selftest-result.txt', '自检结果：FAIL（一打开就出事，没走到分析）\n' + 文)
            try:
                print('自检结果：FAIL（一打开就出事，没走到分析）\n' + 文)
            except Exception:
                pass
        else:
            弹窗告警('软件一打开就出事了，还没走到分析那一步。')
        return 1

    try:
        return officer_app.主入口()
    except SystemExit:
        raise
    except BaseException:
        落纸('出了点问题.txt', '软件出错了：\n' + traceback.format_exc())
        return 1


if __name__ == '__main__':
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException:
        try:
            落纸('出了点问题.txt', '最外层接住的错：\n' + traceback.format_exc())
        except Exception:
            pass
        raise
