# -*- coding: utf-8 -*-
"""rebuild_live2d_full.py — 从 files/AssetBundles/live2d 全量重建 Live2D。

管线（2026-10 修正配方）：1) reconstruct(UnityPy)→model3/moc3/physics3/textures
  2) AssetStudioModCLI 提完整 motions（含 MB_* 复位曲线） 3) 覆盖 motion/
  4) fix_model3 修 model3。moc3/physics3 用 UnityPy 版(与 AS 等价); 不产 cdi3。
安全: 默认干跑; --yes 才动 Output/Live2D(旧目录 move 到 .diag/_old_live2d_<stamp>/ 回滚)
      --limit 样本 / --all 全量; 日志与进度 json 落 .diag(三分法判定)。
用法: py -3 scripts/rebuild_live2d_full.py --limit aersasi_2,ougen_8 --yes
      py -3 scripts/rebuild_live2d_full.py --all --yes
"""
import os, sys, argparse, shutil, subprocess, glob, json, datetime, time
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths as P

ASCLI = os.environ.get('AL_ASCLI') or r'D:\AzurLaneTools\AssetStudioCLI\AssetStudioModCLI.exe'
PY = sys.executable or 'py'
HERE = os.path.dirname(os.path.abspath(__file__))


def run(cmd, logf, cwd=None):
    s = time.time()
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, errors='replace')
        out = (p.stdout or '') + (p.stderr or '')
    except Exception as e:
        out = f'启动失败: {e}'
        p = type('P', (), {'returncode': -1})()
    logf.write(f'$ {" ".join(map(str, cmd))}   rc={p.returncode} ({time.time()-s:.1f}s)\n')
    if out.strip():
        for ln in out.splitlines()[-40:]:
            logf.write('    ' + ln + '\n')
    logf.flush()
    return p.returncode, out


def motion_curves(mdir):
    n = c = 0
    if not os.path.isdir(mdir):
        return 0, 0
    for f in os.listdir(mdir):
        if not f.endswith('.motion3.json'):
            continue
        n += 1
        try:
            c += len(json.load(open(os.path.join(mdir, f), encoding='utf-8')).get('Curves', []))
        except Exception:
            pass
    return n, c

def find_as_motions(tmp):
    base = os.path.join(tmp, 'Live2DOutput', 'Assets', 'ArtResource', 'Live2d')
    hits = glob.glob(os.path.join(base, '*', '*', 'motions'))
    return hits[0] if hits else None


def check_prereq():
    if not os.path.isfile(ASCLI):
        sys.exit(f'[FATAL] 找不到 AssetStudioModCLI: {ASCLI}（设 AL_ASCLI）')
    if not os.path.isdir(P.LIVE2D_SRC):
        sys.exit(f'[FATAL] 源目录不存在: {P.LIVE2D_SRC}')
    print(f"[*] 源 bundle 数 = {len(os.listdir(P.LIVE2D_SRC))}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--all', action='store_true')
    ap.add_argument('--limit', help='逗号分隔模型名，样本验证')
    ap.add_argument('--yes', action='store_true', help='执行（默认干跑）')
    ap.add_argument('--skip-reconstruct', action='store_true')
    ap.add_argument('--skip-as', action='store_true')
    ap.add_argument('--skip-fix', action='store_true')
    args = ap.parse_args()

    check_prereq()
    if not (args.all or args.limit):
        print('[*] 用 --all 或 --limit a,b'); return

    names = sorted(os.listdir(P.LIVE2D_SRC)) if args.all else \
        [x.strip() for x in args.limit.split(',') if x.strip()]
    missing = [n for n in names if not os.path.isfile(os.path.join(P.LIVE2D_SRC, n))]
    if missing:
        sys.exit(f'[FATAL] 源里找不到: {missing}')

    stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    bak = os.path.join(P.ROOT, '.diag', f'_old_live2d_{stamp}')
    logp = os.path.join(P.ROOT, '.diag', f'rebuild_l2d_full_{stamp}.log')
    prov = {'stamp': stamp, 'names': names, 'status': {}, 'as_curves_total': 0}
    lg = open(logp, 'w', encoding='utf-8', errors='replace')
    print(f'[*] {len(names)} 模型 | 日志: {os.path.relpath(logp, P.ROOT)}')
    def track(t):
        lg.write(f'# {time.strftime("%H:%M:%S")} [{t}]\n'); lg.flush()

    if not args.yes:
        for n in names:
            print('    - ' + n +
                  ('(已存在→备份重建)' if os.path.isdir(os.path.join(P.LIVE2D_OUT, n)) else '(新建)'))
        print('[*] 干跑完成，加 --yes 执行'); lg.close(); return

    # ---- 备份回收 ----
    if args.all:
        if os.path.isdir(P.LIVE2D_OUT):
            os.makedirs(bak, exist_ok=True)
            for ent in os.listdir(P.LIVE2D_OUT):
                shutil.move(os.path.join(P.LIVE2D_OUT, ent), os.path.join(bak, ent))
            print(f'[+] 回收整个 Output/Live2D → {os.path.relpath(bak, P.ROOT)}')
        os.makedirs(P.LIVE2D_OUT, exist_ok=True)
    else:
        for n in names:
            mdir = os.path.join(P.LIVE2D_OUT, n)
            if os.path.isdir(mdir):
                os.makedirs(os.path.dirname(os.path.join(bak, n)), exist_ok=True)
                shutil.move(mdir, os.path.join(bak, n))

    # ---- 1. reconstruct ----（--all 一次进程；--limit 必须逐模型，因 --name 重复会被 argparse 只取最后一个）
    if not args.skip_reconstruct:
        track('reconstruct')
        if args.all:
            run([PY, os.path.join(HERE, 'reconstruct_live2d.py'), '--all'], lg, cwd=P.ROOT)
        else:
            for n in names:
                run([PY, os.path.join(HERE, 'reconstruct_live2d.py'), '--name', n], lg, cwd=P.ROOT)
        for n in names:
            if os.path.isfile(os.path.join(P.LIVE2D_OUT, n, f'{n}.model3.json')):
                prov['status'][n] = prov['status'].get(n, {}) | {'reconstruct': 'ok'}

    # ---- 2. AS motions ----
    if not args.skip_as:
        track('as-motions')
        for n in names:
            try:
                bundle = os.path.join(P.LIVE2D_SRC, n)
                tmp = os.path.join(P.ROOT, '.diag', f'_as_tmp_{stamp}', n)
                if os.path.isdir(tmp):
                    shutil.rmtree(tmp)
                rc, _ = run([ASCLI, bundle, '-m', 'live2d', '-o', tmp], lg)
                mdir = os.path.join(P.LIVE2D_OUT, n, 'motion')
                os.makedirs(mdir, exist_ok=True)
                am = find_as_motions(tmp)
                if not am or not os.listdir(am):
                    prov['status'][n] = prov['status'].get(n, {}) | {'as': 'FAIL-无motions'}
                    lg.write(f'[WARN] {n}: AS 无 motions {am}\n'); continue
                for f in glob.glob(os.path.join(am, '*.motion3.json')):
                    shutil.copy2(f, os.path.join(mdir, os.path.basename(f)))
                an, ac = motion_curves(mdir)
                prov['as_curves_total'] += ac
                prov['status'][n] = prov['status'].get(n, {}) | {'as': 'ok', 'as_curves': ac, 'as_motions': an}
                lg.write(f'[AS] {n}: {an} motions / {ac} 曲线\n')
                shutil.rmtree(tmp, ignore_errors=True)
            except Exception as e:
                lg.write(f'[AS-ERR] {n}: {e}\n')
                prov['status'][n] = prov['status'].get(n, {}) | {'as': 'EXC:' + str(e)[:60]}

    # ---- 3. fix_model3 ----
    if not args.skip_fix:
        track('fix_model3')
        run([PY, os.path.join(HERE, 'fix_model3.py')], lg, cwd=P.ROOT)

    track('done')
    okm = [k for k, v in prov['status'].items() if v.get('as') == 'ok']
    prov['summary'] = {'total': len(names), 'as_ok': len(okm),
                       'as_curves_total': prov['as_curves_total']}
    with open(os.path.join(P.ROOT, '.diag', f'rebuild_progress_{stamp}.json'), 'w', encoding='utf-8') as f:
        json.dump(prov, f, ensure_ascii=False, indent=1)
    print(f'[SUMMARY] total={len(names)} as_ok={len(okm)} 总曲线={prov["as_curves_total"]}')
    lg.close()


if __name__ == '__main__':
    main()

def find_as_motions(tmp):
    base = os.path.join(tmp, 'Live2DOutput', 'Assets', 'ArtResource', 'Live2d')
    hits = glob.glob(os.path.join(base, '*', '*', 'motions'))
    return hits[0] if hits else None
