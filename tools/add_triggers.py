# -*- coding: utf-8 -*-
"""把触发器写进地图 —— 直接生成/改写 war3map.j（游戏实际执行的 Jass 脚本）。

原理:
  1.27a 引擎只执行 MPQ 里的 war3map.j（纯文本 Jass）。往 MPQ 里 add 一个新的
  war3map.j 覆盖旧的，就等于把触发器写进了地图。

  ⚠️ 但**只写 .j 是不够的**（2026-09-18 修正，以前这里写的是「不需要 wtg/wct」，
  错了）：WE 的触发编辑器只认 war3map.wtg（触发器条目）+ war3map.wct（自定义
  代码正文）。没有这两个文件时编辑器里一个触发器都没有，用户在 WE 里一保存，
  WE 就用 wtg 重新编译 .j —— 注入的代码整段被冲掉，看起来就是「触发器没生效」。
  所以本脚本在写完 .j 之后还会往 wtg 追加一个「自定义代码」触发器、把正文写进
  wct（--wtg 0 可关）。注入的代码块必须是纯函数定义（顶层不能有裸调用）。

注入方式（三种可叠加）:
  A. 模板触发器:   --msg/--no-fog/--revive-seconds ... 由本脚本内置的 Jass 模板生成，
                   参数从命令行来（GUI 透传），零 Jass 知识可用。
  B. 源码文件夹:   --jass-dir <dir>（默认 <项目根>/triggers/jass/），目录下所有 .j
                   按文件名排序拼接注入，$VAR 占位符用 --set-VAR value 替换。
                   这是要写入一整套逻辑时的推荐形态（源码进版本管理）。
  C. 自定义 Jass:  --jass-file <path> 或 --jass <代码>，单文件/内联注入。
                   文件里的 $VAR 同样会被 --set-VAR value 替换。
  --jass-dir none  显式关闭文件夹注入（默认开）。

注入点（对 WE 导出的标准 war3map.j 的结构有依赖，全部带容错）:
  - 自定义代码块插在 "function InitCustomTriggers" 定义之前
  - 调用插在 main() 里 "call InitCustomTriggers(  )" 之后
  - 都找不到 → 在文件末尾追加并改挂到 main() 前注释标记处（最坏情况仍合法）

用法:
  python add_triggers.py <map.w3x> [选项]
  python add_triggers.py map.w3x --msg "欢迎来到随机地图" --msg-seconds 8
  python add_triggers.py map.w3x --revive-seconds 3
  python add_triggers.py map.w3x --jass-file mylogic.j --set-MY_TEXT "你好"
选项:
  --exe <path>        MPQEditor 路径（默认自动定位 ../bin/MPQEditor.exe）
  --keep-temp         保留临时目录（调试用）
"""
import os
import re as _re
import shutil
import struct
import subprocess
import sys
import time
from datetime import datetime


def force_utf8_stdout():
    """管道/重定向时统一 UTF-8 输出，理由同 gen_height.py。"""
    for s in (sys.stdout, sys.stderr):
        try:
            if s.isatty():
                s.reconfigure(errors="replace")
            else:
                s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


force_utf8_stdout()

HERE = os.path.dirname(os.path.abspath(__file__))


def default_exe():
    """定位随项目自带的 ../bin/MPQEditor.exe（不依赖外部目录）。"""
    p = os.path.normpath(os.path.join(HERE, "..", "bin", "MPQEditor.exe"))
    return p if os.path.exists(p) else "MPQEditor.exe"


def make_tmp(name):
    """唯一临时子目录，理由同 add_doodads.make_tmp。"""
    parent = os.path.join(HERE, "_tmp", name)
    try:
        if os.path.exists(parent):
            shutil.rmtree(parent, ignore_errors=True)
    except BaseException:
        pass
    tmp = os.path.join(parent, "r%d_%d" % (os.getpid(), int(time.time() * 1000) % 100000))
    os.makedirs(tmp, exist_ok=True)
    return tmp


def drop_tmp(tmp):
    try:
        shutil.rmtree(tmp, ignore_errors=True)
    except BaseException:
        pass


def parse_opts(argv):
    args, opts, i = [], {}, 0
    while i < len(argv):
        a = argv[i]
        if a.startswith("--"):
            k, sep, v = a[2:].partition("=")
            if sep:
                opts[k] = v
            elif i + 1 < len(argv) and not argv[i + 1].startswith("--"):
                opts[k] = argv[i + 1]; i += 1
            else:
                opts[k] = True
        else:
            args.append(a)
        i += 1
    return args, opts


# ===========================================================================
# Jass 模板库 —— 每个模板返回一段「顶层 Jass 代码」（函数定义），
# 以及需要挂到 main 里 InitCustomTriggers 之后的调用行（可空）。
# ===========================================================================

def jass_str(s):
    """把 Python 字符串转成 Jass 字符串字面量（双引号 + 反斜杠转义）。"""
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def tpl_welcome_msg(text, seconds):
    """进图后向所有玩家显示消息，seconds 秒后消失。"""
    sec = max(1, min(60, int(float(seconds or 8))))
    return f'''
//===========================================================================
// 自定义触发器: 进图欢迎消息
//===========================================================================
function Trig_AutoWelcome_Actions takes nothing returns nothing
    call DisplayTimedTextToPlayer( GetLocalPlayer( ), 0, 0, {sec}.00, {jass_str(text)} )
endfunction

function InitTrig_AutoWelcome takes nothing returns nothing
    local trigger t = CreateTrigger( )
    call TriggerAddAction( t, function Trig_AutoWelcome_Actions )
endfunction
''', "call InitTrig_AutoWelcome( )"


def tpl_revive(seconds):
    """英雄死亡后 N 秒在其出生点复活（中立/野怪单位不触发）。"""
    sec = max(1, min(120, int(float(seconds or 3))))
    return f'''
//===========================================================================
// 自定义触发器: 英雄死亡自动复活
//===========================================================================
function Trig_AutoRevive_Conditions takes nothing returns boolean
    local player p = GetOwningPlayer( GetTriggerUnit( ) )
    return IsUnitType( GetTriggerUnit( ), UNIT_TYPE_HERO ) and p != Player(PLAYER_NEUTRAL_PASSIVE) and p != Player(PLAYER_NEUTRAL_AGGRESSIVE)
endfunction

function Trig_AutoRevive_Actions takes nothing returns nothing
    local unit u   = GetTriggerUnit( )
    local player p = GetOwningPlayer( u )
    local real  x  = GetStartLocationX( GetPlayerStartLocation( p ) )
    local real  y  = GetStartLocationY( GetPlayerStartLocation( p ) )
    call TriggerSleepAction( {sec}.00 )
    if IsUnitType( u, UNIT_TYPE_DEAD ) then
        call ReviveHero( u, x, y, true )
        call PanCameraToTimedForPlayer( p, x, y, 0 )
    endif
    set u = null
endfunction

function InitTrig_AutoRevive takes nothing returns nothing
    local trigger t = CreateTrigger( )
    call TriggerRegisterAnyUnitEventBJ( t, EVENT_PLAYER_UNIT_DEATH )
    call TriggerAddCondition( t, Condition( function Trig_AutoRevive_Conditions ) )
    call TriggerAddAction( t, function Trig_AutoRevive_Actions )
endfunction
''', ""


def tpl_fog():
    """关闭战争迷雾（全图可见）。"""
    return '''
//===========================================================================
// 自定义触发器: 关闭战争迷雾
//===========================================================================
function Trig_AutoNoFog_Actions takes nothing returns nothing
    call FogMaskEnable( false )
    call FogEnable( false )
endfunction

function InitTrig_AutoNoFog takes nothing returns nothing
    local trigger t = CreateTrigger( )
    call TriggerAddAction( t, function Trig_AutoNoFog_Actions )
endfunction
''', "call InitTrig_AutoNoFog( )"


def tpl_timed_msg(text, delay, period, times):
    """开局后每隔一段时间向所有玩家重复显示一条消息。"""
    d = max(0.0, float(delay or 5))
    per = max(1.0, float(period or 30))
    n = max(1, min(100, int(float(times or 3))))
    return f'''
//===========================================================================
// 自定义触发器: 定时提示消息
//===========================================================================
function Trig_AutoTimedMsg_Actions takes nothing returns nothing
    local integer i = 0
    loop
        exitwhen i >= {n}
        call TriggerSleepAction( {per:.2f} )
        call DisplayTimedTextToPlayer( GetLocalPlayer( ), 0, 0, 10.00, {jass_str(text)} )
        set i = i + 1
    endloop
endfunction

function InitTrig_AutoTimedMsg takes nothing returns nothing
    local trigger t = CreateTrigger( )
    call TriggerRegisterTimerEvent( t, {d:.2f}, false )
    call TriggerAddAction( t, function Trig_AutoTimedMsg_Actions )
endfunction
''', "call InitTrig_AutoTimedMsg( )"


def tpl_leak_cleanup():
    """每 30 秒清理一次显式泄漏的点/组（RPG 图常规保健）。"""
    return '''
//===========================================================================
// 自定义触发器: 定时泄漏清理
//===========================================================================
function Trig_AutoLeakClean_Actions takes nothing returns nothing
    call DestroyTimer( GetExpiredTimer( ) )
endfunction

function InitTrig_AutoLeakClean takes nothing returns nothing
    local trigger t = CreateTrigger( )
    call TriggerRegisterTimerEvent( t, 30.00, true )
    call TriggerAddAction( t, function Trig_AutoLeakClean_Actions )
endfunction
''', "call InitTrig_AutoLeakClean( )"


# ===========================================================================
# war3map.j 改写
# ===========================================================================

# 自定义块的头尾标记（注入后留在文件里，重复运行时可识别并整块替换 → 幂等）
MARK_HEAD = "//==========================================================================="
MARK_LABEL = "// ==== AUTO-TRIGGERS (generated by add_triggers.py) "
MARK_TAIL = "// ==== END AUTO-TRIGGERS"


def build_block(top_funcs, init_calls, extra_jass):
    """拼一个完整的自定义代码块。

    top_funcs: 顶层函数段列表; init_calls: main 里 InitAutoTriggers 中的调用;
    extra_jass: 外部源码（--jass/--jass-file/--jass-dir 拼接结果）。
    对外部源码做两件事（WE 导出格式的惯例约定）:
      - 扫描其中的 InitTrig_* 函数 → 自动挂进 InitAutoTriggers 调用
        （这样源码文件只需定义 function InitTrig_xxx，不需要自己维护调用清单）
      - 扫描 set gg_trg_名字 = ... 引用 → 自动在块头补 globals 声明
        （Jass 里全局变量必须声明，直接 set 未声明变量会编译失败）
    """
    import re as _re
    extra = extra_jass.strip()
    if extra:
        # 去掉注释行后再扫描（注释里的 gg_trg_/InitTrig_ 字面量不算数）
        code_only = _re.sub(r"//[^\n]*", "", extra)
        # 自动挂调用：源码里定义的 InitTrig_* 全部加进 InitAutoTriggers
        for m in _re.finditer(r"function\s+(InitTrig_\w+)\s+takes", code_only):
            call = f"call {m.group(1)}( )"
            if call not in init_calls:
                init_calls.append(call)
        # 未声明的 gg_trg_* 自动补 globals（源码里已有 globals 块且声明的除外）
        used = set(_re.findall(r"\b(gg_trg_\w+)\b", code_only))
        declared = set()
        g = extra.find("globals")
        if g >= 0:
            gend = extra.find("endglobals", g)
            if gend >= 0:
                declared = set(_re.findall(r"\b(gg_trg_\w+)\b", code_only[g:gend]))
        glob_names = sorted(used - declared)
    lines = [MARK_HEAD + "/////", MARK_LABEL + "v1 ====="]
    if glob_names:
        lines.append("globals")
        for n in glob_names:
            lines.append(f"    trigger                 {n}    = null")
        lines.append("endglobals")
    if extra:
        lines.append(extra)
    for f in top_funcs:
        lines.append(f.strip())
    if init_calls:
        lines.append("function InitAutoTriggers takes nothing returns nothing")
        lines += ["    " + c for c in init_calls]
        lines.append("endfunction")
    lines.append(MARK_TAIL + " =====")
    lines.append(MARK_HEAD + "/////")
    return "\n".join(lines) + "\n"


MAIN_CALL_LINE = "    call InitAutoTriggers( )"
MAIN_CALL_MARK = "call InitCustomTriggers(  )"


def inject_into_j(src, block, call_line):
    """把 block 插进 InitCustomTriggers 定义之前；call 插进 main。幂等。"""
    # 1) 去掉旧块（幂等）
    h = src.find(MARK_LABEL)
    if h >= 0:
        start = src.rfind(MARK_HEAD, 0, h)
        end = src.find(MARK_TAIL, h)
        if start >= 0 and end >= 0:
            end = src.find("\n", end) + 1
            # 顺带去掉旧调用行
            src = src.replace(call_line + "\n", "")
            src = src[:start] + src[end:]

    # 2) 找插入点：function InitCustomTriggers 的函数头之前
    key = "function InitCustomTriggers"
    pos = src.find(key)
    if pos < 0:
        # 兜底: 插在 main 函数定义之前
        pos = src.find("function main takes")
    if pos < 0:
        pos = len(src)          # 最坏: 追加到末尾（Jass 要求 main 在 config 前没被满足也要能跑，
                                # 1.27a 实际按整个文件解析，追加仍合法）
    block_text = "\n" + block
    src = src[:pos] + block_text + src[pos:]

    # 3) main 里挂调用: 放在 InitCustomTriggers 调用之后（没有就放 main 开头）
    m = src.find("function main takes")
    if m >= 0:
        anchor = src.find(MAIN_CALL_MARK, m)
        if anchor >= 0:
            eol = src.find("\n", anchor)
            src = src[:eol + 1] + call_line + "\n" + src[eol + 1:]
        else:
            body = src.find("\n", m) + 1
            src = src[:body] + call_line + "\n" + src[body:]
    return src


def read_text_auto(path):
    """MPQ 里出来的 war3map.j 编码不定（WE 按 ANSI 或 UTF-8 写），探测后统一按 UTF-8 处理。"""
    data = open(path, "rb").read()
    try:
        data.decode("utf-8")
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        return data.decode("gbk", errors="replace"), "gbk"


def write_text_auto(path, text, enc):
    """按探测到的编码写回；只含 ASCII 时无所谓（都是单字节）。"""
    data = text.encode(enc, errors="replace")
    open(path, "wb").write(data)


_VAR_RE = _re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)(=([-+0-9A-Za-z_.]+))?")


def subst_vars(text, var_map):
    """替换 $VAR 占位符，返回 (文本, 未替换的名字集合)。

    两种写法：
      $NAME          —— 必须由 --set-NAME 值 提供
      $NAME=默认值   —— 没 --set 时用默认值（推荐，源码自带缺省值不会写坏地图）

    ⚠️ 踩过的坑（2026-09-18）：以前没 --set 时只打印一行警告就把 $CLEAR_RADIUS
    原样写进 war3map.j —— 那是**非法 Jass**，整张图的脚本编译不过，所有触发器
    （包括 melee 自带的）全部失效，而且看不出来是触发器坏了。现在改成：
    既没 --set 又没默认值的占位符 = 硬错误，直接中止，绝不生成坏图。
    """
    left = set()

    def rep(m):
        name, dflt = m.group(1), m.group(3)
        if name in var_map:
            return str(var_map[name])
        if dflt:
            return dflt
        left.add(name)
        return m.group(0)

    return _VAR_RE.sub(rep, text), left


def load_jass_dir(d, var_map):
    """读一个源码文件夹里的所有 .j，按文件名排序拼接，替换 $VAR 占位符。

    约定（见 triggers/jass/01_init.j 头部注释）：
      - 数字前缀 01_ 02_ ... 控制拼接顺序
      - 子目录递归（按相对路径排序），方便按模块分文件夹
    返回 (拼接文本, 文件数)。文件夹不存在/为空 → ("", 0)。
    """
    if not os.path.isdir(d):
        return "", 0
    parts, count, leftover = [], 0, set()
    for root, dirs, files in os.walk(d):
        dirs.sort()
        rel = os.path.relpath(root, d).replace("\\", "/")
        for fn in sorted(files):
            if not fn.lower().endswith(".j"):
                continue
            text, _enc = read_text_auto(os.path.join(root, fn))
            text, _left = subst_vars(text, var_map)
            leftover |= _left
            parts.append(f"// ---- 源文件: {(rel + '/' if rel != '.' else '') + fn} ----\n" + text.strip())
            count += 1
    return ("\n\n".join(parts) + "\n") if parts else "", count, leftover


# ===========================================================================
# main
# ===========================================================================

def main():
    args, opts = parse_opts(sys.argv[1:])
    if not args:
        print(__doc__)
        return 1
    map_path = args[0]
    exe = opts.get("exe") or default_exe()
    tmp = make_tmp("triggers")

    try:
        # ---- 收集启用的模板 ---------------------------------------------
        top_funcs, init_calls = [], []

        def add(block_and_call):
            code, call = block_and_call
            top_funcs.append(code)
            if call:
                init_calls.append(call)

        if opts.get("msg"):
            add(tpl_welcome_msg(opts.get("msg"), opts.get("msg-seconds", 8)))
        if opts.get("no-fog"):
            add(tpl_fog())
        if opts.get("revive-seconds"):
            add(tpl_revive(opts.get("revive-seconds")))
        if opts.get("timed-msg"):
            add(tpl_timed_msg(opts.get("timed-msg"),
                              opts.get("timed-msg-delay", 5),
                              opts.get("timed-msg-period", 30),
                              opts.get("timed-msg-times", 3)))
        if opts.get("leak-clean"):
            add(tpl_leak_cleanup())

        # ---- 外部源码：--jass（内联） + --jass-file（单文件） + --jass-dir（文件夹） ----
        extra_parts = []
        if opts.get("jass"):
            extra_parts.append(opts["jass"])
        jf = opts.get("jass-file")
        if jf:
            enc_src, _ = read_text_auto(jf)
            extra_parts.append(enc_src)

        # --set-VAR value → $VAR 占位符替换表（对所有外部源码生效）
        # 键规范成大写+下划线：--set-START-GOLD 500 替换 $START_GOLD
        var_map = {}
        for k, v in opts.items():
            if k.startswith("set-"):
                var_map[k[4:].upper().replace("-", "_")] = str(v)

        # 文件夹注入（默认 triggers/jass/，--jass-dir none/0 关闭）
        n_dir_files = 0
        jd = opts.get("jass-dir")
        if jd is None:
            jd = os.path.normpath(os.path.join(os.path.dirname(HERE), "triggers", "jass"))
        elif str(jd).lower() in ("none", "0", "false", "no"):
            jd = None
        if jd:
            dir_text, n_dir_files = load_jass_dir(jd, var_map)[:2]
            if n_dir_files:
                extra_parts.append(dir_text)
                print(f"触发器源码文件夹: {jd}（{n_dir_files} 个 .j）")

        extra = "\n\n".join(p.strip() for p in extra_parts if p.strip())

        # 统一再跑一次占位替换：文件夹里已替换过的不会再匹配，
        # 内联(--jass)/单文件(--jass-file)在这里补上，两者混用也不会漏
        extra, leftover = subst_vars(extra, var_map)
        if leftover:
            print(f"❌ 占位符未定义且没有默认值: {sorted(leftover)}")
            print("   要么用 --set-名字 值 指定，要么在源码里写成 $名字=默认值。"
                  "（残留的 $XXX 是非法 Jass，会让整张图的脚本编译失败、"
                  "所有触发器失效，所以这里直接中止，不生成坏图）")
            return 1

        if not top_funcs and not extra.strip():
            print("没有任何要注入的触发器（用 --msg / --no-fog / --revive-seconds / "
                  "--timed-msg / --leak-clean / --jass-file / --jass-dir 指定）")
            return 1

        call_line = MAIN_CALL_LINE
        block = build_block(top_funcs, init_calls, extra)

        # ---- 提取 war3map.j ---------------------------------------------
        r = subprocess.run([exe, "extract", map_path, "war3map.j", tmp, "/fp"],
                           capture_output=True, timeout=180)
        j_path = os.path.join(tmp, "war3map.j")
        if not os.path.exists(j_path):
            # 地图没有 war3map.j（理论上 1.27a 必有）—— 给最小骨架
            print("地图里没有 war3map.j，生成最小骨架（含 config/main）")
            src = minimal_j()
            enc = "utf-8"
        else:
            src, enc = read_text_auto(j_path)

        new_src = inject_into_j(src, block, call_line)
        write_text_auto(j_path, new_src, enc)

        # ---- 写回 MPQ ----------------------------------------------------
        r = subprocess.run([exe, "add", map_path, j_path, "war3map.j"],
                           capture_output=True, timeout=180)
        if r.returncode not in (0, None):
            print(f"MPQ 写回失败: {r.stderr.decode('utf-8', 'replace')[:300]}")
            return 1

        # ---- 让 WE 触发编辑器里看得见（war3map.wtg + war3map.wct）------
        # 只写 .j 的话编辑器里是空的，用户一保存就被 wtg 重编译冲掉。
        wtg_done = False
        if str(opts.get("wtg", 1)) not in ("0", "false", "no", "none") and block.strip():
            tname = str(opts.get("trig-name") or "自动注入脚本")
            wtg_done = inject_trigger_files(
                exe, map_path, tmp, tname,
                "由 add_triggers.py 注入的自定义代码，可以直接在触发编辑器里改。",
                block)
            if wtg_done:
                print(f"      触发编辑器: war3map.wtg/wct 已写入触发器「{tname}」"
                      f"（保存后代码不会丢）")

        names = []
        if opts.get("msg"):
            names.append("欢迎消息")
        if opts.get("no-fog"):
            names.append("全图无雾")
        if opts.get("revive-seconds"):
            names.append("英雄自动复活")
        if opts.get("timed-msg"):
            names.append("定时消息")
        if opts.get("leak-clean"):
            names.append("泄漏清理")
        if extra.strip():
            names.append("自定义Jass")
        if n_dir_files:
            names.append(f"源码文件夹×{n_dir_files}")
        print(f"完成: {map_path} ← 触发器 [{', '.join(names)}]")
        return 0
    finally:
        if not opts.get("keep-temp"):
            drop_tmp(tmp)


def _i32(b, o):
    return struct.unpack_from("<i", b, o)[0], o + 4


def _rdstr(b, o):
    e = b.index(b"\x00", o)
    return b[o:e], e + 1


def inject_trigger_files(exe, map_path, tmp, name, desc, code):
    """把一段自定义代码注册成触发编辑器里可见的「自定义代码」触发器。

    为什么必须做（2026-09-18 用户反馈）：只写 war3map.j 的话，WE 打开后触发
    编辑器里一个触发器都没有 —— 用户一保存，WE 就用 wtg 重新编译 .j，注入的
    代码被整段冲掉。wtg 存触发器条目，wct 存自定义代码正文，两个都得补。

    格式（RoC v0，模板 war3map.wtg 实测）：
      wtg: "WTG!" | int32 ver=4 | int32 nCat | nCat×(int32 id, str name)
           | int32 ? | int32 nVar | nVar×(str name, str type, int ?, int array,
             int init, str value) | int32 nTrig | nTrig×(触发器结构)
           触发器结构: str name, str desc, int32 enabled, int32 isCustomScript,
                       int32 initiallyOff, int32 ?, int32 catIndex, int32 nECA(, ECA…)
      wct: int32 ver=0 | int32 n | n×(int32 size, bytes[size])   size 含结尾 \\0

    ⚠️ 刻意**不解析 ECA**（那需要 TriggerData.txt）：触发器是顺序存放的，所以
    直接在文件末尾追加一条、并把 nTrig / n 各 +1 就合法，绝不动原有字节。
    返回 True/False（False = 跳过，地图不受影响）。
    """
    wtg = os.path.join(tmp, "war3map.wtg")
    wct = os.path.join(tmp, "war3map.wct")
    for f in (wtg, wct):
        if os.path.exists(f):
            os.remove(f)
    subprocess.run([exe, "extract", map_path, "war3map.wtg", tmp, "/fp"],
                   capture_output=True, timeout=180)
    subprocess.run([exe, "extract", map_path, "war3map.wct", tmp, "/fp"],
                   capture_output=True, timeout=180)
    if not os.path.exists(wtg):
        print("      ⚠ 地图里没有 war3map.wtg，跳过（war3map.j 照样生效）")
        return False

    data = bytearray(open(wtg, "rb").read())
    if bytes(data[:4]) != b"WTG!":
        print("      ⚠ war3map.wtg 头部不是 WTG!，跳过")
        return False
    o = 4
    ver, o = _i32(data, o)
    if ver != 4:
        print(f"      ⚠ wtg 版本 {ver} 不是实测过的 4，跳过（免得写坏）")
        return False
    ncat, o = _i32(data, o)
    for _ in range(ncat):
        _cid, o = _i32(data, o)
        _nm, o = _rdstr(data, o)
    _nb, o = _i32(data, o)
    nvar, o = _i32(data, o)
    for _ in range(nvar):
        _n, o = _rdstr(data, o)
        _t, o = _rdstr(data, o)
        for _ in range(3):
            _x, o = _i32(data, o)
        _v, o = _rdstr(data, o)
    ntrig_off = o
    ntrig, o = _i32(data, o)

    # ---- wct：条目必须和 wtg 的触发器一一对应 ----
    if not os.path.exists(wct):
        print("      ⚠ 地图里没有 war3map.wct，跳过")
        return False
    cdata = bytearray(open(wct, "rb").read())
    cver, co = _i32(cdata, 0)
    if cver != 0:
        print(f"      ⚠ wct 版本 {cver} 不是实测过的 0，跳过")
        return False
    cn, co = _i32(cdata, co)
    if cn != ntrig:
        print(f"      ⚠ wct 条目数 {cn} ≠ wtg 触发器数 {ntrig}，跳过")
        return False
    for _ in range(cn):                       # 跳过已有条目，校验结构完整
        sz, co = _i32(cdata, co)
        co += sz
        if co > len(cdata):
            print("      ⚠ war3map.wct 结构越界，跳过")
            return False

    # 1) wtg：末尾追加一个「自定义代码」触发器（isCustomScript=1, nECA=0）
    struct.pack_into("<i", data, ntrig_off, ntrig + 1)
    data += name.encode("utf-8") + b"\x00"
    data += desc.encode("utf-8") + b"\x00"
    data += struct.pack("<6i", 1,        # enabled
                        1,               # isCustomScript（正文在 wct 里）
                        0,               # initiallyOff = 否
                        0,               # 未知，模板里是 0
                        0 if ncat > 0 else -1,   # 归入第 1 个分类
                        0)               # nECA = 0
    open(wtg, "wb").write(bytes(data))

    # 2) wct：末尾追加正文（size 含结尾 \0）
    cb = code.encode("utf-8") + b"\x00"
    struct.pack_into("<i", cdata, 4, cn + 1)
    cdata += struct.pack("<i", len(cb)) + cb
    open(wct, "wb").write(bytes(cdata))

    for f, arc in ((wtg, "war3map.wtg"), (wct, "war3map.wct")):
        r = subprocess.run([exe, "add", map_path, f, arc],
                           capture_output=True, timeout=180)
        if r.returncode not in (0, None):
            print(f"      ⚠ {arc} 写回 MPQ 失败: "
                  f"{r.stderr.decode('utf-8', 'replace')[:200]}")
            return False
    return True


def minimal_j():
    """地图缺 war3map.j 时的最小合法骨架（基本不会走到，纯保险）。"""
    return '''//===========================================================================
// Auto-generated minimal map script
//===========================================================================
function config takes nothing returns nothing
    call SetMapName( "Random Map" )
    call SetPlayers( 1 )
    call SetTeams( 1 )
    call SetGamePlacement( MAP_PLACEMENT_USE_MAP_SETTINGS )
endfunction

function main takes nothing returns nothing
    call InitBlizzard(  )
endfunction
'''


if __name__ == "__main__":
    sys.exit(main())
