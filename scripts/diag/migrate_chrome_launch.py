# -*- coding: utf-8 -*-
r"""把 `subprocess.Popen([... '--headless' ...])` 批量换成 `chrome_tree.launch(...)`。

为什么要批量而不是逐个手改（2026-10-28）：全库 57 个探针各自 `Popen` + `install()`，
`install()` 只注册 atexit —— 宿主超时强杀 python 时 atexit **不执行**，Chrome 整棵树变孤儿。
真实事故：6 个孤儿实例 62 个进程 5.83 GB，CPU 96%。修法是让启动点统一走 `launch()`，
由它做 A（Job Object，内核级）/ B（启动前按 profile 清残留）/ C（atexit + 回读确认）。

判据（不是"改完看着对"）：
  before: `--headless` 文件里 `subprocess.Popen` 含 headless 的调用点数 = N
  after : 同一批文件里 `chrome_tree.launch(` 调用点数 = N，且 headless Popen 调用点 = 0

跑法：
    py -3 scripts/diag/migrate_chrome_launch.py --dryrun     # 只报数 + 列出将改的文件
    py -3 scripts/diag/migrate_chrome_launch.py              # 真改（自动 .bak 不出，走 git）

⚠️ 只改**参数区里真的出现 `--headless`** 的 Popen；同一个文件里起 http.server 的 Popen 不动。
"""
import ast
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DIAG = os.path.join(ROOT, 'scripts', 'diag')
sys.stdout.reconfigure(encoding='utf-8')

POPen_RE = re.compile(r'\bsubprocess\.Popen\(')
INSTALL_PREFIX = 'chrome_tree.install('
SKIP_FILES = {'chrome_tree.py', 'chrome_lifecycle_selftest.py', 'migrate_chrome_launch.py'}


def _match_paren(text, open_idx):
    """从 `(` 的位置找配对的 `)`，跳过字符串与注释里的括号。返回 `)` 之后的下标。"""
    depth = 0
    i = open_idx
    n = len(text)
    quote = None
    while i < n:
        c = text[i]
        if quote:
            if c == '\\':
                i += 2
                continue
            if text.startswith(quote, i):
                i += len(quote)
                quote = None
                continue
            i += 1
            continue
        if c in '#':
            j = text.find('\n', i)
            i = n if j < 0 else j + 1
            continue
        if c in '"\'':
            if text.startswith(c * 3, i):
                quote = c * 3
                i += 3
                continue
            quote = c
            i += 1
            continue
        if c == '(':
            depth += 1
        elif c == ')':
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return -1


def _headless_vars(text):
    """找出「被赋过含 `--headless` 的列表」的变量名（`flags = [...]` / `flags += [...]` 都算）。

    为什么需要：4 个文件（gallery_ui_shots / l2d_hand_probe / l2d_costume_ui_verify / shot_real_gpu）
    写成 `flags = [CHROME, '--headless=new', ...]` 再 `Popen(flags, ...)`，参数区里看不到字面
    `--headless`。只按字面匹配会漏掉它们 —— 而 `gallery_ui_shots.Page` 恰恰是 ~70 个脚本的共用出口，
    漏了它等于没修一半。
    """
    names = set()
    for m in re.finditer(r'^\s*([A-Za-z_]\w*)\s*(?:\+?=)\s*\[', text, re.M):
        name = m.group(1)
        end = _match_paren(text, text.index('[', m.end() - 1))
        if end < 0:
            continue
        if '--headless' in text[m.end():end]:
            names.add(name)
    return names


def plan(path):
    """返回 [(popen_start, popen_end, wrapped_by_install)]，只挑 headless 的。"""
    text = open(path, encoding='utf-8').read()
    hvars = _headless_vars(text)
    out = []
    for m in POPen_RE.finditer(text):
        start = m.start()
        open_idx = m.end() - 1
        end = _match_paren(text, open_idx)
        if end < 0:
            continue
        body = text[start:end]
        direct = '--headless' in body
        # 间接形态：第一个位置参数就是那个含 --headless 的变量名
        arg1 = re.match(r'\s*([A-Za-z_]\w*)\s*[,)]', body[len('subprocess.Popen('):])
        indirect = bool(arg1) and arg1.group(1) in hvars
        if not (direct or indirect):
            continue
        wrapped = text[max(0, start - len(INSTALL_PREFIX)):start] == INSTALL_PREFIX
        out.append((start, end, wrapped))
    return text, out


USE_RE = re.compile(r'\bchrome_tree\.(?:launch|install|kill_tree)\b')
IMPORT_RE = re.compile(r'^\s*(?:import\s+chrome_tree\b|from\s+chrome_tree\s+import\b)', re.M)


def import_order_problem(path):
    """`chrome_tree` 被用了却还没导入 → 返回一行说明，正常返回 None。

    ⚠️ 这条检查是 2026-10-29 事故的护栏：`rewrite()` 只换了调用点，**没动 import 行**。
    原来那批脚本写的是「先 `Popen`/`launch` 再 `import chrome_tree`」（延迟导入图省事），
    迁移后就变成「`chrome_tree.launch(...)` 跑在一个还没定义的模块名上」——
    `NameError` 直到运行时才炸，`py_compile` 完全看不出来。实测 6 个脚本中招，
    其中 5 个是 WF-16 回归六件套的成员 ⇒ 整条验证链在第 3、4 件直接崩。

    实现必须走 AST：早先用正则扫源码，会把**注释和 docstring 里**提到 `chrome_tree.launch()`
    的文件误判成坏的（实测 3 个假红），而且认不出 `import websocket, chrome_tree, cdp_wait` 这种逗号式导入。
    """
    try:
        src = open(path, encoding='utf-8').read()
        tree = ast.parse(src)
    except SyntaxError as e:
        return '%s: 语法错误 %s' % (os.path.basename(path), e)
    imp = None
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [a.name for a in node.names]
        if any(n == 'chrome_tree' for n in names):
            imp = node.lineno if imp is None else min(imp, node.lineno)
    uses = [n.lineno for n in ast.walk(tree)
            if isinstance(n, ast.Name) and n.id == 'chrome_tree']
    if not uses:
        return None
    first = min(uses)
    if imp is not None and imp <= first:
        return None
    return ('%s:%d 用了 `chrome_tree` 但导入在它之后（或无导入）⇒ NameError；'
            '把 import 挪到第一次使用之前' % (os.path.basename(path), first))


def rewrite(text, sites):
    """把每个 headless Popen 调用点换成 `chrome_tree.launch(...)`。

    ⚠️ 括号必须**逐个配对**地保留，不能整段吞掉：第一次写这段时对非 install 包裹的形态
    切到了 `end`（Popen 的闭合 `)` 之后），于是 `launch(` 少了一个 `)` —— `py_compile`
    报 `'(' was never closed`，53 个文件会一次性全坏。所以：
      非包裹：`subprocess.Popen(BODY)`            → `chrome_tree.launch(BODY)`
      包裹  ：`chrome_tree.install(subprocess.Popen(BODY))` → `chrome_tree.launch(BODY)`
    两种形态的 BODY 都取 `open_idx+1 : end-1`（参数本身，不含 Popen 的闭合括号）。
    """
    for start, end, wrapped in sorted(sites, reverse=True):
        open_idx = start + len('subprocess.Popen(') - 1
        body = text[open_idx + 1:end - 1]
        new = 'chrome_tree.launch(' + body + ')'
        if wrapped:
            pre = start - len(INSTALL_PREFIX)
            # text[end] 是 install 自己的 ')'，要连它一起吃掉
            text = text[:pre] + new + text[end + 1:]
        else:
            text = text[:start] + new + text[end:]
    # `launch()` 内部已经调过 install，紧跟其后的 `X = chrome_tree.install(X)` 是纯冗余，
    # 留着会让同一棵树注册两个 atexit 回调（无害但会重复回读进程表，拖慢退出）。
    # 只删「同一个变量确实由 launch 赋值」的那一行，别的 install 调用不碰。
    def _drop(m):
        var = m.group(1)
        return '' if re.search(r'\b%s\s*=\s*chrome_tree\.launch\(' % re.escape(var), text) else m.group(0)

    text = re.sub(r'\n[ \t]*(\w+)\s*=\s*chrome_tree\.install\(\s*\1\s*\)[ \t]*(?=\n)', _drop, text)
    return text


def main():
    dry = '--dryrun' in sys.argv
    audit = '--audit' in sys.argv
    only = None
    if '--only' in sys.argv:
        only = set(sys.argv[sys.argv.index('--only') + 1].split(','))
    total_sites = 0
    touched = []
    problems = []
    order_bad = []
    for name in sorted(os.listdir(DIAG)):
        if not name.endswith('.py') or name in SKIP_FILES:
            continue
        if only and name not in only:
            continue
        path = os.path.join(DIAG, name)
        bad = import_order_problem(path)
        if bad:
            order_bad.append(bad)
        try:
            text, sites = plan(path)
        except Exception as e:
            problems.append('%s: 解析失败 %s' % (name, e))
            continue
        if not sites:
            continue
        if 'chrome_tree' not in text:
            problems.append('%s: 用了 headless Popen 但没 import chrome_tree' % name)
        total_sites += len(sites)
        touched.append((name, len(sites)))
        if dry or audit:
            continue
        new = rewrite(text, sites)
        # 只校验语法，不当成"语义已对"的证据（WF-46：py_compile 只证语法）
        try:
            compile(new, path, 'exec')
        except SyntaxError as e:
            problems.append('%s: 改写后语法错误 %s' % (name, e))
            continue
        with open(path, 'w', encoding='utf-8', newline='') as f:
            f.write(new)

    if audit:
        print('迁移现状：headless Popen 调用点 %d 个（应为 0）' % total_sites)
        if order_bad:
            print('\n[FAIL] %d 个脚本「用了 chrome_tree 但导入在使用之后」：' % len(order_bad))
            for p in order_bad:
                print('   ' + p)
        else:
            print('[PASS] 全部 %d 个脚本的 `chrome_tree` 导入都在首次使用之前' % (
                len([n for n in os.listdir(DIAG) if n.endswith('.py') and n not in SKIP_FILES])))
        return 1 if (order_bad or total_sites) else 0

    print('将迁移的 headless Popen 调用点: %d 个，分布在 %d 个文件' % (total_sites, len(touched)))
    for name, n in touched:
        print('   %-34s %d' % (name, n))
    if problems:
        print('\n[WARN] %d 条需要人工确认：' % len(problems))
        for p in problems:
            print('   ' + p)
    if dry:
        print('\n[dryrun] 未写盘。去掉 --dryrun 执行。')
        return 0
    print('\n已写盘。接着跑：py -3 -m py_compile 全部改动文件，再重扫确认 0 个 headless Popen。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
