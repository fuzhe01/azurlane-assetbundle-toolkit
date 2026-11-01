# -*- coding: utf-8 -*-
"""定位主脚本里的 JS 语法错误位置（不用浏览器，纯文本状态机）。

背景：本轮改了 index.html 后浏览器报 Uncaught SyntaxError: Invalid or unexpected token，
但 compile_check.py 报 OK —— 说明它检查的不是同一份内容（或用了旧缓存）。
先做静态定位：统计注释符号配对 / 未闭合字符串 / 括号深度。

用法: py -3 scripts/diag/find_js_syntax_error.py
"""
import re
import sys

sys.stdout.reconfigure(encoding='utf-8')
SRC = r'gallery_src\index.html'


def main():
    src = open(SRC, encoding='utf-8').read()
    blocks = re.findall(r'<script[^>]*>(.*?)</script>', src, re.S)
    print('script 块: %s' % [len(b) for b in blocks])
    body = max(blocks, key=len)
    # 计算 body 在原文中的起始行号，便于报行号
    off = src.find(body)
    base_line = src[:off].count('\n') + 1
    print('主块长度 %d，起始行 %d' % (len(body), base_line))

    i, n = 0, len(body)
    state = 'code'
    line = base_line
    issues = []
    depth_stack = []
    while i < n:
        c = body[i]
        if c == '\n':
            line += 1
        if state == 'code':
            two = body[i:i + 2]
            if two == '/*':
                state = 'block'
                bline = line
                i += 2
                continue
            if two == '//':
                state = 'line'
                i += 2
                continue
            if c == '"':
                state = 'dq'
                sline = line
                i += 1
                continue
            if c == "'":
                state = 'sq'
                sline = line
                i += 1
                continue
            if c == '`':
                state = 'bt'
                sline = line
                i += 1
                continue
            if c in '([{':
                depth_stack.append((c, line))
            elif c in ')]}':
                if depth_stack:
                    depth_stack.pop()
            i += 1
            continue
        if state == 'block':
            if body[i:i + 2] == '*/':
                state = 'code'
                i += 2
                continue
            i += 1
            continue
        if state == 'line':
            if c == '\n':
                state = 'code'
            i += 1
            continue
        if state in ('dq', 'sq'):
            q = '"' if state == 'dq' else "'"
            if c == '\\':
                i += 2
                continue
            if c == q:
                state = 'code'
                i += 1
                continue
            if c == '\n':
                issues.append(('字符串未闭合（换行截断）', sline, state))
                state = 'code'
            i += 1
            continue
        if state == 'bt':
            if c == '\\':
                i += 2
                continue
            if c == '`':
                state = 'code'
                i += 1
                continue
            i += 1
            continue
    print('结束状态: %s' % state)
    if state != 'code':
        print('!! 脚本结束时仍处于 %s 状态' % state)
    for it in issues[:12]:
        print('  问题: %s  起始行 %s' % (it[0], it[1]))
    if depth_stack:
        print('!! 未闭合的括号（后 5 个）:')
        for c, l in depth_stack[-5:]:
            print('    %r 开于第 %d 行' % (c, l))
    else:
        print('括号配对正常')

    # 额外：打印每一行里出现 */ 但该行不含 /* 的情况（注释外 */
    print('\n--- 检查 注释外的 */ ---')
    i = 0
    state = 'code'
    line = base_line
    while i < n:
        c = body[i]
        if c == '\n':
            line += 1
        if state == 'code':
            if body[i:i + 2] == '/*':
                state = 'block'
                i += 2
                continue
            if body[i:i + 2] == '//':
                state = 'line'
                i += 2
                continue
            if c == '"':
                state = 'dq'
                i += 1
                continue
            if c == "'":
                state = 'sq'
                i += 1
                continue
            if c == '`':
                state = 'bt'
                i += 1
                continue
            if body[i:i + 2] == '*/':
                ls = body.rfind('\n', 0, i) + 1
                le = body.find('\n', i)
                print('  第 %d 行: %s' % (line, body[ls:le][:160]))
                i += 2
                continue
            i += 1
            continue
        if state == 'block':
            if body[i:i + 2] == '*/':
                state = 'code'
                i += 2
                continue
            i += 1
            continue
        if state == 'line':
            if c == '\n':
                state = 'code'
            i += 1
            continue
        if state in ('dq', 'sq', 'bt'):
            q = '"' if state == 'dq' else ("'" if state == 'sq' else '`')
            if c == '\\':
                i += 2
                continue
            if c == q:
                state = 'code'
            i += 1
            continue
    return 0


if __name__ == '__main__':
    sys.exit(main())
