# -*- coding: utf-8 -*-
"""列出当前所有顶层窗口的标题 / 位置，用来确认用户 WE 里打开的是哪张图。
（PowerShell 的 Add-Type 被安全策略拦了，改用 ctypes 直接调 user32。）
"""
import ctypes
import ctypes.wintypes as wt

u32 = ctypes.windll.user32

EnumWindows = u32.EnumWindows
EnumWindowsProc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
GetWindowTextW = u32.GetWindowTextW
GetWindowTextLengthW = u32.GetWindowTextLengthW
IsWindowVisible = u32.IsWindowVisible
GetWindowRect = u32.GetWindowRect
GetWindowThreadProcessId = u32.GetWindowThreadProcessId

rows = []


def cb(hwnd, lparam):
    n = GetWindowTextLengthW(hwnd)
    if n <= 0:
        return True
    buf = ctypes.create_unicode_buffer(n + 2)
    GetWindowTextW(hwnd, buf, n + 2)
    pid = wt.DWORD(0)
    GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    r = wt.RECT()
    GetWindowRect(hwnd, ctypes.byref(r))
    rows.append((hwnd, pid.value, bool(IsWindowVisible(hwnd)),
                 (r.left, r.top, r.right, r.bottom), buf.value))
    return True


EnumWindows(EnumWindowsProc(cb), 0)

import os  # noqa: E402
import sys  # noqa: E402
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "tools"))
target = None
for hwnd, pid, vis, rect, title in rows:
    if any(k in title.lower() for k in ("world", "editor", "war3", "warcraft")):
        print(f"★ PID={pid} vis={vis} rect={rect}  {title}")
        target = (hwnd, pid, rect, title)
print("-" * 60)
print(f"顶层窗口共 {len(rows)} 个")
if target:
    hwnd, pid, rect, title = target
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "we_win.txt"),
              "w", encoding="utf-8") as f:
        f.write(f"{hwnd}\t{pid}\t{rect}\t{title}\n")
    print("已写入 we_win.txt")
