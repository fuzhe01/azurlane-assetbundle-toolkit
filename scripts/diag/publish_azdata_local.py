#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 37_parse_sharecfgdata.py --scalar-all 的产物发布为 inputs/azdata 的本机权威数据。

背景：inputs/azdata/*.json 之前是社区 dumper 快照（381，会滞后）。从 10/8 的设备侧
sharecfgdata 用 37 --scalar-all 解出的三表 {id:行} 完整形态与社区 azdata**同构**
（ship_data_statistics 实测 4123 条键完全一致），且设备侧更新：
  ship_skin_template 2870（社区 2863，多 aierdeliqi_9/mile_3 等 7 行）
  ship_data_template 3972（社区 3968）

用法:
  py -3 scripts/diag/publish_azdata_local.py [--dry]

产物:
  inputs/azdata/azdata_ship_skin_template.json
  inputs/azdata/azdata_ship_data_statistics.json
  inputs/azdata/azdata_ship_data_template.json
  inputs/azdata/azdata_version.json
  inputs/azdata/MANIFEST.json   （就地更新 files 列表与 provenance）
"""
import hashlib, json, os, sys, datetime

sys.stdout.reconfigure(encoding='utf-8')
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
SRC = os.path.join(ROOT, '.diag', 'sharecfg_re', 'cfg_json_scalar')
DST = os.path.join(ROOT, 'inputs', 'azdata')

TABLES = ['ship_skin_template', 'ship_data_statistics', 'ship_data_template']
GAME_VERSION = '9.7.385'


def sha(b):
    return hashlib.sha256(b).hexdigest()


def main():
    dry = '--dry' in sys.argv
    files = []
    for t in TABLES:
        p = os.path.join(SRC, t + '.json')
        data = json.load(open(p, encoding='utf-8'))
        raw = json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True).encode('utf-8') + b'\n'
        dst = os.path.join(DST, 'azdata_' + t + '.json')
        if not dry:
            with open(dst, 'wb') as fh:
                fh.write(raw)
        files.append({
            'path': 'azdata_' + t + '.json', 'bytes': len(raw), 'sha256': sha(raw),
            'records': len(data),
        })
        print('%-38s %8d B  %6d 行  %s' % (os.path.basename(dst), len(raw), len(data),
              '写出' if not dry else 'DRY'))

    ver = {
        'game_resources_version': GAME_VERSION,
        'generated_at': datetime.date.today().isoformat(),
        'source': ('本机从 files/AssetBundles/sharecfgdata 用 '
                   'tools/sharecfg_re/37_parse_sharecfgdata.py --scalar-all 直接解出（非社区快照）'),
        'note': '设备侧比社区 381 快照新；ship_skin_template 2870 / statistics 4123 / template 3972',
        'files': files,
    }
    vp = os.path.join(DST, 'azdata_version.json')
    if not dry:
        with open(vp, 'w', encoding='utf-8') as fh:
            json.dump(ver, fh, ensure_ascii=False, indent=2)
    print('azdata_version.json %s (%d B)' % ('写出' if not dry else 'DRY', len(json.dumps(ver, ensure_ascii=False))))

    if not dry:
        mp = os.path.join(DST, 'MANIFEST.json')
        man = json.load(open(mp, encoding='utf-8'))
        man['provenance'] = {
            'kind': '本机解出（非社区快照）',
            'local_landed_at': datetime.date.today().isoformat(),
            'game_resources_version': GAME_VERSION,
            'regenerate_via': 'tools/sharecfg_re/37_parse_sharecfgdata.py --scalar-all --yes + scripts/diag/publish_azdata_local.py',
            'note': '从设备侧 sharecfgdata 直接解出，随游戏更新从 build_ship_meta / extract_live2d_voice 消费端自动覆盖社区快照。',
        }
        man['files'] = files
        with open(mp, 'w', encoding='utf-8') as fh:
            json.dump(man, fh, ensure_ascii=False, indent=2)
        print('MANIFEST.json 已就地更新（%d 条 files）' % len(files))
    return 0


if __name__ == '__main__':
    sys.exit(main())