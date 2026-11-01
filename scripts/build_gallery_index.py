#!/usr/bin/env python3
"""构建资产浏览器索引 index.json（v2 合并逻辑）。
所有资产按「归一化基ID → 完整皮肤stem」挂载，Spine/Live2D 绑定到对应 skin。
"""
import sys, os, re, json, glob, collections
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
import skin_table  # 皮肤表唯一读取口（azdata 快照 + 设备侧权威表逐字段合并）
import extract_cv_voice as E   # 只要它那份后缀定义（HEI_SUF/ART_SUF）——同一套语义不许写两份
from ship_name_map import SHIP_NAME_MAP

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
OUT = os.path.join(ROOT, 'Output')
# 支持 GALLERY_OUT_DIR 环境变量把产物写到临时目录，供改造后小规模比对，默认写正式 gallery_v2
GAL = os.environ.get('GALLERY_OUT_DIR') or os.path.join(OUT, 'gallery_v2')

# ---------- 语音/台词权威源：skin_voice.json（scripts/extract_cv_voice.py 从 cue/cv-*.b 导出）----------
# 旧口径是「社区 CV_MAP(719 条) → 中文名 → 拼音」归并 Output/Audio/CV/*.wav，
# 结果 740/1008 组船显示「语音 0」而其中 590 组其实有语音（docs/TROUBLESHOOTING.md §47）。
SKIN_VOICE = {}
_sv_path = os.path.join(OUT, 'gallery_v2', 'skin_voice.json')
if os.path.exists(_sv_path):
    SKIN_VOICE = json.load(open(_sv_path, encoding='utf-8'))

# 台词正文（scripts/build_skin_words.py）：给「有表行但主包没下发」的皮肤补 voiceText，
# 少这一步就是 44 张明明有台词却在语音页整页空白（§57 / §6 第 16 条）。缺文件不许静默当 0。
_sw_path = os.environ.get('GALLERY_WORDS_PATH') or os.path.join(OUT, 'gallery_v2', 'skin_words.json')
if not os.path.exists(_sw_path) and not os.environ.get('GALLERY_ALLOW_NO_WORDS'):
    raise SystemExit('缺 %s —— 先跑 py -3 scripts/build_skin_words.py 再建索引；'
                     '确实不需要台词字段时用 GALLERY_ALLOW_NO_WORDS=1 显式放行' % _sw_path)
SKIN_WORDS = json.load(open(_sw_path, encoding='utf-8')) if os.path.exists(_sw_path) else {'m': {}, 'w': {}}

# ---------- 元数据 ----------
meta_by_cn = {}
for s in json.load(open(os.path.join(OUT, 'WikiData', 'ship_data.json'), encoding='utf-8')):
    meta_by_cn[s['name']] = s

# ---------- 新权威元数据源：ship_meta.json（旧 SHIP_NAME_MAP + Wiki meta_by_cn 降级兜底）----------
# 键=完整 bundle stem，值含 cn(皮肤名)/faction/type/rarity/category(舰级，经 ship_group 归并)
# ⚠️ cn 可能含 {namecode:XX} 本地化占位符(§6#8)，故「舰名」优先用干净的 SHIP_NAME_MAP，
#    仅当 SHIP_NAME_MAP 缺失且 cn 为真实名时才用 cn；「阵营/舰种/稀有度」则以 ship_meta 为主(Wiki 覆盖仅 445 太低)。
SHIP_META = {}
# `SHIP_META_PATH` 让「新元数据 + 新索引」能在临时目录里成对跑一遍再比对
# （改取行规则类改动的零回退核对，见 docs/WORKFLOWS.md WF-26）；默认仍是正式区的 ship_meta.json。
_sm_path = os.environ.get('SHIP_META_PATH') or os.path.join(OUT, 'ship_meta.json')
if os.path.exists(_sm_path):
    try:
        SHIP_META = json.load(open(_sm_path, encoding='utf-8'))
    except Exception:
        SHIP_META = {}
PLACEH = re.compile(r'\{namecode:\d+\}')
# 配置表里有一类值**根本不是名字**：游戏自己用遮蔽块字符（▅▇■ 等 U+2580–U+259F）表示被和谐掉的
# 字，还有一整串问号、以及长的拼音/十六进制回显。一旦当组名用，卡片上就会出现
# `▅海▊▇洛▅■芬特▇▆`（实测组 hierophant）或 `？？？`（实测 dosair / unknown1）。
# 判据按「像不像一个真名」写，**不按组名开例外名单**。
# ⚠️ 纯 ASCII 那条**只挡十六进制回显**（2026-10-04 修，见 docs/TROUBLESHOOTING.md 对应条目）：
#    旧写法 `^[A-Za-z0-9_\-\.\s]{5,}$` 想挡 `544845544F574552` 这类回显，却把**正常的英文皮肤名**
#    一起杀了 —— 实测全表 55 行被误杀，含 `qiye_7`→Wind Catcher、`haman_6`→Blushing Fellow、
#    `shengluyisi_4`→Luxury Handle、`bominghan_5`→Briar Maid、`duli_6`→Relaxation.I。
#    收窄成「只含 0-9A-Fa-f 且长度 ≥ 8」后：`2B`/`A2` 放行（尼尔联动真名）、英文单词放行，
#    而 `544845544F574552`（13 位纯十六进制）仍被挡。
HEX_ECHO = re.compile(r'^[0-9A-Fa-f]{8,}$')
NOT_A_NAME = re.compile(r'^[\s？?！!。，,、\-—·]*$|[\u2580-\u259f]')
def _looks_like_echo(v):
    """十六进制回显单独判：NOT_A_NAME 的字符类写法会误杀英文真名（见上）。"""
    return bool(HEX_ECHO.match(v))
def _derived(cn, e):
    """这个名字能撑起的三项字段（配置优先、Wiki 按中文名兜底）。"""
    m = meta_by_cn.get(cn, {}) if cn else {}
    return (bool(e.get('faction') or m.get('faction', '')),
            bool(e.get('type') or m.get('ship_type', '') or m.get('type', '')),
            bool(e.get('rarity') or m.get('rarity', '')))


def _emptier(a, b):
    """a 是否比 b 少撑起至少一项、且一项都没多起来。"""
    return any((not x) and y for x, y in zip(a, b)) and not any(x and not y for x, y in zip(a, b))


def _clean_cn(v):
    """占位符/空/不像真名的 cn 视为无有效名；首尾空白先去掉再判
    （实测 `仲裁者·英普拉·IV ` 带一个尾空格 —— 那是真名，不该和占位符一起被挡）。"""
    v = (v or '').strip()
    if not v or PLACEH.search(v) or NOT_A_NAME.search(v) or _looks_like_echo(v):
        return ''
    return v

# ---------- 占位符展开（2026-10-04，§94）----------
# 表里一批皮肤名的 `name` 是 `{namecode:NNN}` 形态（`进击，{namecode:257}！`、`{namecode:27}、伴你在海边！`），
# `_clean_cn` 把它们判成"无有效名" ⇒ 标签回落成「皮肤N」。实测 35 条残留里 16 条是这种。
# `name_code` 表可读（456 行），`{namecode:17}` → 时雨、`{namecode:22}` → 雪风，展开即可用。
#
# ⚠️ **不能无条件展开**：配置表里存在**占位符指向另一个实体**的情况——
# `shiyu_2` 的 name 是 `进击，{namecode:257}！`，而 `namecode:257` = **伊490**，
# 但这行属于时雨组（ship_group=30115）。展开会得到「进击，伊490！」挂在时雨卡上 ⇒ 是错的。
# ⇒ 判据：**展开结果必须含这张卡自己的舰名**，否则判为不可用、保持现标签。
# 实测 8 条可安全展开、1 条（shiyu_2）指向别的实体被挡。
_NAME_CODE = None
def _name_code():
    global _NAME_CODE
    if _NAME_CODE is None:
        p = os.path.join(ROOT, 'inputs', 'gamecfg', 'name_code.json')
        try:
            _NAME_CODE = json.load(open(p, encoding='utf-8'))
        except Exception:
            _NAME_CODE = {}
    return _NAME_CODE

def expand_placeholder(v, ship_name=''):
    """展开 `{namecode:NNN}` → 中文名；**展开后必须含 `ship_name`** 才认。

    返回 '' 表示不可用（无占位符 / 码查不到 / 展开结果与所属舰不符），调用方据此回落。
    """
    if not v or not PLACEH.search(v):
        return ''
    out = v
    # ⚠️ `PLACEH` 是**无捕获组**正则（`\{namecode:\d+\}`），`findall()` 返回的是整个匹配串
    # `'{namecode:27}'` 而不是码 `'27'` —— 直接拿来查表必然 miss，整段静默失效。
    # ⇒ 这里自己提码，不要复用 `PLACEH.findall()`。
    for code in re.findall(r'\{namecode:(\d+)\}', v):
        rec = _name_code().get(code) or {}
        nm = (rec.get('name') or '').strip()
        if not nm:
            return ''                      # 码查不到 ⇒ 不猜
        out = out.replace('{namecode:%s}' % code, nm)
    if PLACEH.search(out):
        return ''                          # 还有没展开干净的
    if ship_name and ship_name not in out:
        return ''                          # ⚠️ 占位符指向别的实体（实测 shiyu_2→伊490）
    return out.strip()

# 社区快照/拼音表译名与游戏官方中文名差异修正（与 build_ship_meta 保持一致，兜底路径也生效）
NAME_FIX = {'贾斯科涅': '加斯科涅'}

PINS = set(SHIP_NAME_MAP.keys())
ROMAN = {'ii': '改', 'iii': '改三', 'iv': '改四'}
# 后缀真实语义（用户 2026-09-20 确认）：_hx 是和谐处理版立绘（非调色变体），_n 是不显示背景的立绘（非夜战场景）
VARMAP = {'hx': '和谐版', 'n': '无背景版', 'g': 'G', 'meta': 'META', 'asmr': 'ASMR', 'gv': '改造'}
JUNK = {'22', '33', 'unknown3'}  # 明显测试残留
# 「来源标记」类后缀：查基名时要剥，但**不进标签**（用户 2026-10-04 裁定，§92/§94）。
# `_doa` 是死或生联动的来源标记（**不是**"原皮"这种皮肤类型）；`_wjz` 是无舰装。
# ⚠️ 这个集合必须在 `normalize()` 之前定义 —— 组键合成与真名查找**共用**它，
#    两处各写一份就会造出 `gushouchuan_tolove` 这种"表里不存在的实体 id"，
#    后果是**一个角色被拆成多张同名卡片**（实测 55 组）。见 normalize() 里的注释。
ART_ONLY = {'n': '无背景版', 'hx': '和谐版'}   # 画法变体：要剥、且**进标签**（可对比）
SOURCE_SUF = {'wjz', 'doa', 'ex', 'tolove', 'ger'}   # 来源标记：要剥、不进标签

def _is_real_entity(key):
    """这个 key 是不是一个**真实存在的实体**，而不是"带后缀的磁盘键"。

    ⚠️ 2026-10-04 加：`SHIP_NAME_MAP`（手抄舰名表）里**混着若干不是舰名的条目** ——
    实测 `gushouchuan_tolove`（值 '古手川'）也有一行。看着是当初有人把磁盘键直接抄进去的。
    后果：`normalize('gushouchuan_tolove_wjz')` 的剥离循环**第一轮就命中它而 break**，
    返回 `gushouchuan_tolove` 当组键 ⇒ 「古手川唯」被拆成 3 张同名卡片。

    **判据**：带 `_tolove`/`_ger` 这类**来源标记**的 key 一律不是实体 ——
    游戏里没有叫「古手川唯 to love」的舰船。`SHIP_NAME_MAP` 本身不动（手抄表改名的风险
    大过收益），只在合成组键时把这类条目排除。
    """
    tk = key.split('_')
    return not (set(tk[1:]) & SOURCE_SUF)

def normalize(stem):
    """返回 (base, extra_label_tokens)。剥离尾部变体标记直到命中拼音表或无可剥。"""
    toks = stem.split('_')
    # 从尾部剥离变体标记（数字/hx/n/g/meta/asmr/罗马数字/**tolove/ger** 等）
    # ⚠️ 2026-10-04 修：`_tolove` / `_ger` 原先**不在这个白名单里**（它们只在下面
    # `SOURCE_SUF` 中），于是剥到 `_tolove` 就 `break`，`normalize('gushouchuan_tolove')`
    # 返回 `'gushouchuan_tolove'` —— 这个实体在表里根本不存在，却被当成独立组键，
    # 于是**一个角色被拆成 3 张卡**（gushouchuan / gushouchuan_tolove / gushouchuan_tolove_wjz
    # 三张卡片标题都是「古手川唯」）。同理 `_doa` 在 `na_doa` 上也不剥，
    # 造出 `na_doa` 这个假组（截图里「雫」被拆成 na / na_doa 两张卡）。
    # ⇒ 判据统一用 `SOURCE_SUF | VARMAP`，**两处后缀集合不许各写一份**。
    while len(toks) > 1:
        if '_'.join(toks) in PINS and _is_real_entity('_'.join(toks)):
            break
        t = toks[-1]
        if (re.fullmatch(r'\d+', t) or t in VARMAP or t in ROMAN
                or t in SOURCE_SUF or t in ('s1', 's2', 's3')):
            toks.pop()
        else:
            break
    base = '_'.join(toks)
    # 命中表 或 base 本身即在表 → base；否则若首段在表则用首段
    if base not in PINS and len(toks) > 1 and toks[0] in PINS:
        # META/灰烬舰(异格,_alter 形态)不并入本体船——独立成卡才能显示 faction=META。
        # 仅当该 _alter 基名在 ship_meta 里确为 META 阵营时才独立;非 META 的 alter 仍折叠。
        if base.endswith('_alter') and SHIP_META.get(base, {}).get('faction') == 'META':
            return base
        base = toks[0]
    return base

def variant_label(stem, base):
    tail = stem[len(base):].strip('_')
    if not tail:
        return '默认立绘'
    parts = []
    for t in tail.split('_'):
        if re.fullmatch(r'\d+', t):
            parts.append(f'皮肤{t}')
        elif t in ROMAN:
            parts.append(ROMAN[t])
        elif t in VARMAP:
            parts.append(VARMAP[t])
        elif t in ('s1','s2','s3'):
            parts.append('SP'+t[-1])
        else:
            parts.append(t)
    return '·'.join(parts)

# ---------- 真名解析（2026-10-04，§92 / WF-24）----------
# 原来 label 只有上面 `variant_label()` 一处赋值 ⇒ 2701/4487 条显示成「皮肤10」，
# 而游戏叫它「泳池里的默契训练」。真名唯一来源是权威表的 `skin_name`
# （ship_meta 里的字段），**不是**目录名反推。
#
# 三条踩过的坑（详见 docs/TROUBLESHOOTING.md §92）：
#  1. 表盘 painting 键**大小写不一致**（表 `haixiao_DOA` vs 盘 `haixiao_doa`）⇒ 查表必须
#     精确优先、再大小写归一（`SHIP_META` 的键是磁盘 stem，这里两个池子都要试）。
#  2. **只剥画法变体，绝不剥数字**。`_N` 是皮肤序号，剥了只剩船名 ⇒ 45 条 `qiye_7` 之类
#     会全变成「企业」，宁可留缺口也不给错名。
#  3. `_clean_cn` 必须已收窄十六进制判据（`_looks_like_echo`），否则英文真名
#     `Wind Catcher` 这类会被当回显杀掉。
#
# 画法变体里**只有 `_n`/`_hx` 会进标签**（用户 2026-10-04 裁定：这两个是"同一张画的
# 不同呈现"，要能对比）；`_wjz`/`_doa`/`_ex`/`_tolove`/`_ger` 是**来源标记不是呈现方式**，
# 配真名后直接消失——`_doa` 尤其重要，用户明确说它是"死或生联动的标记、不是原皮这种皮肤类型"。
# ⚠️ `ART_ONLY` / `SOURCE_SUF` 已挪到文件上方（`normalize()` 之前）—— 组键合成与真名查找共用。

def _real_name(stem, ship_name=''):
    """磁盘 stem -> 权威表里的皮肤真名（查不到或像垃圾串则回空串）。

    顺序：① 整名直接查 ② 逐层剥「画法变体 + 来源标记 + 数字」查。
    ⚠️ 数字**只在剥完之后命中失败时**才继续往下剥——优先整名/全名匹配，
    保证 `qiye_7` 拿到的是它自己那行（Wind Catcher）而不是基船名（企业）。

    占位符（`{namecode:NNN}`）在这一层**不算命中**——`_clean_cn` 会把它判成无效名，
    要等 `true_label` 拿到带占位符的原文后交给 `expand_placeholder` 展开（§94）。
    传 `ship_name` 是为了那道"展开结果必须含本卡舰名"的把关。
    """
    # ① 整名 + 画法变体/来源标记全剥（数字保留）
    toks = stem.split('_')
    tail = []
    while len(toks) > 1 and (toks[-1] in ART_ONLY or toks[-1] in SOURCE_SUF):
        tail.insert(0, toks.pop())
    for cand in ['_'.join(toks)] + ([stem] if tail else []):
        e = SHIP_META.get(cand) or {}
        n = _clean_cn(e.get('skin_name') or e.get('cn'))
        if n:
            return n, list(tail), False
    # ② 还没拿到，才剥数字。⚠️ 这一层拿到的大概率是**裸船名**（`qiye_7`→企业），
    #    调用方靠 flag=True 把它挡掉。
    cur = stem.split('_')
    while len(cur) > 1 and re.fullmatch(r'\d+', cur[-1]):
        cur.pop()
        e = SHIP_META.get('_'.join(cur)) or {}
        n = _clean_cn(e.get('skin_name') or e.get('cn'))
        if n:
            return n, tail, True
    return '', tail, False

def true_label(stem, base, ship_name=''):
    """权威真名 + 该有的画法变体标注；查不到真名就回落原来的 variant_label。

    ⚠️ 防错只对**剥数字那一层**生效：`qiye_7` 剥掉 `_7` 拿到的是基船名「企业」，
    那是船名不是皮肤名，必须丢掉。但**整名/剥来源标记命中的一律照用**——
    `haixiao_doa` 剥掉 `doa` 拿到的「海咲」就是它自己的正确皮肤名
    （这张卡恰好也叫海咲，**不能**因为"名字等于舰名"就误杀，那会把 58 条 `_doa` 打回原形）。
    """
    name, tail, from_strip_num = _real_name(stem, ship_name)
    if name and not (from_strip_num and name == ship_name):
        marks = [ART_ONLY[t] for t in tail if t in ART_ONLY]
        return '·'.join([name] + marks)
    # 占位符兜底（§94）：`_clean_cn` 把 `{namecode:NNN}` 判成无效名 ⇒ 上一路必然拿不到。
    # 这里直接读该行的**原文**再展开，并过那道"展开结果必须含本卡舰名"的把关。
    # ⚠️ `npc` 前缀的一律不处理（用户 2026-10-04：「有 npc 前缀的可以不用管」）——
    #    那些是剧情 NPC 键，表里的 name 多半是 `？？？` 或别的实体，展开出来也是错的。
    if not stem.lower().startswith('npc'):
        toks = stem.split('_')
        t2 = []
        while len(toks) > 1 and (toks[-1] in ART_ONLY or toks[-1] in SOURCE_SUF):
            t2.insert(0, toks.pop())
        for cand in ['_'.join(toks), stem]:
            raw = (SHIP_META.get(cand) or {}).get('skin_name') or ''
            if PLACEH.search(raw or ''):
                ex = expand_placeholder(raw, ship_name)
                # ⚠️ 展开结果**等于本卡舰名**时不能当皮肤名用：那说明这一行就是本体
                # （如 `luoen_3` 的 name 是 `{namecode:439}` → 罗恩，而它是罗恩的第 3 套皮肤）。
                # 换上去会让标签变成与卡片标题重复的「罗恩」，而正确答案是保留「皮肤3」
                # —— 因为表里确实没有第 3 套的皮肤名。宁可留占位式标签也不给错信息。
                if ex and ex != ship_name:
                    # 画法变体标注要跟着一起带上，否则 `liangyue_2_n` 会显示成
                    # 「凉月、伴你在海边！」而丢掉「·无背景版」，与同卡其它皮肤标法不一致。
                    marks = [ART_ONLY[t] for t in t2 if t in ART_ONLY]
                    return '·'.join([ex] + marks)
    return variant_label(stem, base)

# ---------- ship_meta 反查：base → 代表性条目（同 base 多 stem 中挑 cn 干净/ship/有阵营 的最优）----------
_base2stems = {}
for _stem in SHIP_META:
    _base2stems.setdefault(normalize(_stem), []).append(_stem)

def ship_meta_entry(base):
    """舰级字段(faction/type/rarity/category/en)来源：优先基皮肤自身条目，其次同 base 兄弟。"""
    if base in SHIP_META:
        return SHIP_META[base]
    best = None
    for s in sorted(_base2stems.get(base, [])):
        if s in SHIP_META:
            e = SHIP_META[s]
            score = (1 if e.get('category') == 'ship' else 0,
                     1 if e.get('faction') else 0,
                     1 if e.get('type') else 0,
                     1 if e.get('rarity') else 0)
            if best is None or score > best[0]:
                best = (score, e)
    return best[1] if best else {}

# 能当组名用的来源档：走通配置桥（含大小写不敏感回退）、或从 NPC 立绘表/同族前缀查到，
# 以及人工核验过的 manual。不含 fallback（手抄表，另有更高优先级通道）与 unresolved。
AUTHORITATIVE_CN = {'painting', 'suffix', 'painting_ci', 'suffix_ci',
                    'npc_table', 'npc_suffix', 'npc_family', 'family', 'manual',
                    'bridge', 'bridge_suffix'}

# ---------- 收集 skins（key=完整stem）----------
skins = {}   # stem -> {key,label,base,image,spine_dir,live2d}
ships = {}   # base -> ship dict

def ship_of(base):
    if base in ships:
        return ships[base]
    e = ship_meta_entry(base)
    # 舰名：ship_meta 为权威（解密配置+en 交叉印证，如 beianpudun=北安普敦而非旧表错的"贝尔法斯特"），
    # SHIP_NAME_MAP 是含已知错误的手写猜测表，降为兜底。
    # 但仅当 meta 条目「已解析出阵营」(resolved) 时才信它的 cn——未解析条目(如 kelei→柯蕾/空阵营)
    # 的 cn 可能是皮肤名或错值，此时回落 SHIP_NAME_MAP(可畏)+Wiki。
    # ⚠️ 只认「基皮肤自身」的 cn 作舰名（变体皮肤 cn 是皮肤标题，不能当舰名）；{namecode}占位符视为无名(§6#8)。
    resolved = bool(e.get('faction'))
    name_meta = _clean_cn(SHIP_META[base].get('cn')) if (resolved and base in SHIP_META) else ''
    # 同 base 兄弟上的配置权威名：base 是**合成前缀**（`linghangyuan1`/`nabulesi` 这类不是任何
    # stem 的组键）、或组键自己那条没解析出阵营时，兄弟里可能恰恰带着干净的真名。
    # 要求该条目的 source 属于「从表里查到」的档，否则 cn 可能只是未被解析的拼音回显。
    sib_name = ''
    if e.get('source') in AUTHORITATIVE_CN:
        s = _clean_cn(e.get('cn') or '')
        sib_name = '' if s == base else s
    # ⚠️ 2026-09-29 用户拍板：兜底顺序改成**配置优先**，含已知错名的手抄表 SHIP_NAME_MAP 退到最后
    # （旧顺序下 80 个组显示的是手抄表名而配置里另有真名，如 missr R小姐→好人理查德、
    #   aijiang 海酱→绊爱、strength 力量→仲裁者·司特莲库斯·VIII）。
    # 配置名要先过 `_clean_cn` 那道"像不像真名"的闸——挡掉 `？？？`/遮蔽块/纯 ASCII 之后，
    # 这些组**保留手抄表名**，因为换了就是把占位符摆到卡片上。
    cn = name_meta or sib_name or SHIP_NAME_MAP.get(base) or ''
    cn = NAME_FIX.get(cn, cn)   # 官方译名修正（兜底路径也生效）
    # ⚠️ 零回退不变式：**改名不得让阵营/舰种/稀有度变得比原来更空**。
    #    这三项是「配置优先，Wiki 按中文名兜底」，所以换一个名字会连带换掉 Wiki 那一跳的命中——
    #    实测 kelei 从手抄表的「可畏」换成配置的「柯蕾」后，皇家/航母/超稀有 全掉、
    #    category 从 ship 翻成 story。这类"名字更权威但字段塌了"的配置名一律不用。
    hand = NAME_FIX.get(SHIP_NAME_MAP.get(base) or '', SHIP_NAME_MAP.get(base) or '')
    if cn and hand and cn != hand and _emptier(_derived(cn, e), _derived(hand, e)):
        cn = hand
    meta = meta_by_cn.get(cn, {}) if cn else {}
    npc = bool(re.match(r'(npc|linghangyuan|lingyangzhe)', base))
    # 阵营/舰种/稀有度：ship_meta 主，Wiki meta_by_cn 兜底（Wiki 覆盖仅 445，且须舰名先正确才可信）
    faction = e.get('faction') or meta.get('faction', '')
    stype = e.get('type') or meta.get('ship_type', '') or ('NPC' if npc else '')
    rarity = e.get('rarity') or meta.get('rarity', '')
    category = e.get('category') or ('story' if (npc or not cn) else 'ship')
    ships[base] = {
        'id': base, 'name': cn or base, 'hasCn': bool(cn), 'npc': npc,
        'type': stype, 'rarity': rarity, 'faction': faction, 'category': category,
        'skins': [], 'spineSkins': [], 'live2dSkins': [],
    }
    return ships[base]

def add_skin(stem, rel_image):
    if stem in JUNK:
        return
    base = normalize(stem)
    sh = ship_of(base)
    sk = skins.get(stem)
    if sk is None:
        sh_name = ships.get(base, {}).get('name', '') if base in ships else ''
        sk = {'key': stem, 'label': true_label(stem, base, sh_name), 'image': rel_image,
              'spine': False, 'live2d': ''}
        skins[stem] = sk
        sh['skins'].append(sk)
    elif rel_image and not sk['image']:
        sk['image'] = rel_image

# 立绘
for p in glob.glob(os.path.join(OUT, 'Paintings_v2', '*.png')):
    stem = os.path.splitext(os.path.basename(p))[0]
    add_skin(stem, 'Paintings_v2/' + os.path.basename(p))

# Spine（目录名即某 skin 的 stem；内含 1..N 个部件 .skel 需合成）
def layer_order(name):
    # B(身体)<M(脸)<T(头发/装饰) 参考原 viewer 图层序，bg 最底
    if '_bg' in name or name.endswith('bg'): return 0
    if name.endswith('B') or 'B_' in name: return 1
    if name.endswith('M') or 'M_' in name: return 2
    if name.endswith('T') or 'T_' in name: return 3
    return 2
SPINE_NO_PARTS = []      # 有 .skel 却没有 parts.json 的目录 —— 攒起来末尾非零退出
SPINE_ORDER_FALLBACK = []  # parts.json 里没有权威绘制序（老文件）→ 只能按层名启发式排的目录
for d in glob.glob(os.path.join(OUT, 'Spine_v2', '*')):
    if not os.path.isdir(d): continue
    stem = os.path.basename(d)
    if not glob.glob(os.path.join(d, '*.skel')):
        continue          # 空壳目录（如 fulangxisike_2 只有一个散 PNG），本来就没有可合成的层
    # 分层只认 prefab 权威清单，**不再按目录 glob 猜**：同目录里除了真分层还躺着
    # `_hx`（和谐版）等变体的 skel，它们不是层、是另一张画 —— 实测 30 个目录被多画、
    # 15 对本体/_hx 的 CG 因此逐像素完全相同（docs/TROUBLESHOOTING.md §58）。
    pj = os.path.join(d, 'parts.json')
    if not os.path.isfile(pj):
        # 刻意不回落到 glob：回落等于把这个 bug 换个地方留着，只是没人再看得见。
        # 由 `extract_spine_v2.py --parts-only` 补齐后再来。
        SPINE_NO_PARTS.append(stem)
        continue
    layers = json.load(open(pj, encoding='utf-8'))['layers']
    act = [l for l in layers if l.get('active') is not False]
    # 绘制序**优先照 prefab 的真实层级序**（parts.json 的 `order`，DFS 先序 = 先画的在下面）。
    # 为什么不再只信 `layer_order`：它按层名后缀分桶，而 `tianjinfeng_2` 的房间层叫 `2B2`
    # （结尾是数字不是 `B`）⇒ 与本体同桶、桶内按 parts.json 的任意顺序排 ⇒ 本体先画、
    # 被不透明房间整块盖住（用户报"空中那份天津风没显示"，2026-10-05）。
    # 老 parts.json 没有 order 字段时仍回落到启发式，但**必须点名**，不许静默。
    if act and all(isinstance(l.get('order'), int) for l in act):
        parts = [l['layer'] for l in sorted(act, key=lambda l: l['order'])]
    else:
        SPINE_ORDER_FALLBACK.append(stem)
        parts = sorted((l['layer'] for l in act), key=layer_order)
    base = normalize(stem)
    sk = skins.get(stem)
    if sk is None:
        add_skin(stem, '')
        sk = skins[stem]
    sk['spine'] = {'folder': stem, 'parts': parts}
    ship_of(base)['spineSkins'].append(stem)
if SPINE_NO_PARTS:
    print(f"! {len(SPINE_NO_PARTS)} 个 Spine 目录有 .skel 但没有 parts.json —— "
          f"分层的权威清单缺失，拒绝猜。先跑 "
          f"`py -3 scripts/extract_spine_v2.py --parts-only --bak Output/_OLD_bak/spine_parts_<日期>/ <目录...>`"
          f"（写正式区必须带 --bak：这批是纯新增时备份会是 0 份，但覆写范围必须当场声明）。"
          f"\n  清单: {SPINE_NO_PARTS[:20]}")
    sys.exit(1)
if SPINE_ORDER_FALLBACK:
    print(f"! {len(SPINE_ORDER_FALLBACK)} 个 Spine 目录的 parts.json 没有 order 字段（老文件）—— "
          f"绘制序只能按层名后缀启发式排，重跑 "
          f"`py -3 scripts/extract_spine_v2.py --parts-only --bak Output/_OLD_bak/spine_parts_<日期>/ <目录...>` 补齐"
          f"（这些是**覆写**，前身字节会落到 --bak 里）。"
          f"\n  清单: {SPINE_ORDER_FALLBACK[:20]}")

# Spine setup-pose 全屏 CG（cg_export.html 导出到 CG_v2/，目录名=皮肤 stem）
# ⚠️ 只接受**已有同名立绘**的 stem。取证时写进 CG_v2 的中间图（`tianjinfeng_2_CHK.png`、
#    `_DARKFIX`、`_ALL_anim`、`_L_tianjinfeng_2`、`*_CMP_*` 这些）不是皮肤，
#    过去会被 `add_skin` 就地造出一张假船卡（实测 11 张）。跳过必须**点名打印**，不许静默。
cg_orphans = []
for p in glob.glob(os.path.join(OUT, 'CG_v2', '*.png')):
    stem = os.path.splitext(os.path.basename(p))[0]
    sk = skins.get(stem)
    if sk is None:
        cg_orphans.append(os.path.basename(p))
        continue
    sk['cg'] = 'CG_v2/' + os.path.basename(p)
if cg_orphans:
    print('[i] CG_v2 里 %d 张图没有同名立绘，按中间产物跳过、不进索引：%s'
          % (len(cg_orphans), ', '.join(sorted(cg_orphans))))

# Live2D
for d in glob.glob(os.path.join(OUT, 'Live2D', '*')):
    if not os.path.isdir(d): continue
    if not glob.glob(os.path.join(d, '*.model3.json')): continue
    stem = os.path.basename(d)
    base = normalize(stem)
    sk = skins.get(stem)
    if sk is None:
        add_skin(stem, '')
        sk = skins[stem]
    sk['live2d'] = 'Live2D/' + stem
    sk['live2dBase'] = stem
    ship_of(base)['live2dSkins'].append(stem)

# 皮肤级语音计数：skin_voice.json 的键就是画廊 bundleID，逐皮肤挂条数与「可点击出声」标记
VOICE_ORPHAN = 0
for stem, e in SKIN_VOICE.items():
    sk = skins.get(stem)
    if sk is None:
        VOICE_ORPHAN += 1          # 测试残留(22/33/unknown3)等 JUNK 皮肤不进索引
        continue
    files = {l.get('f') for l in (e.get('lines') or []) if l.get('f')}
    sk['voiceCount'] = len(files)
    sk['voiceTap'] = bool(e.get('tap'))

# ---------- 变体包语音（主包本地缺失时盘上仅剩的 -gift / -battle 导出）----------
# 包号来自游戏自己的皮肤表（painting → 皮肤行 id // 10），不再走社区 CV_MAP 那条归并链。
# 一个 painting 若同时属于两个发声实体（如 lafei 既是舰船 10117 也是剧情角色 90024），
# 就把这一档**整体放弃**——按 §47 的教训，派错声比留空更糟。
SKIN_ROWS = {}
for _r in skin_table.load().values():
    if isinstance(_r, dict):
        _p = str(_r.get('painting') or '').strip().lower()
        if _p:
            SKIN_ROWS.setdefault(_p, set()).add(int(_r.get('id') or 0) // 10)
VARIANT_PACK = {}
for _f in glob.glob(os.path.join(OUT, 'Audio', 'CV', 'cv-*.wav')):
    _m = re.match(r'cv-(\d+)-(\w+)\.wav$', os.path.basename(_f))
    if _m:
        VARIANT_PACK.setdefault(int(_m.group(1)), []).append('Audio/CV/' + _m.group(0))
VAR_TAIL = re.compile(r'(_hx|_n|_rw|_bj|_jz|_alter|_heihei|_hei)+$')
VOICE_EXTRA = 0
for stem, sk in skins.items():
    if sk.get('voiceCount'):
        continue
    cands = {stem.lower(), VAR_TAIL.sub('', stem.lower())}
    packs = set()
    for c in cands:
        packs |= SKIN_ROWS.get(c, set())
    hits = sorted({f for p in packs for f in VARIANT_PACK.get(p, [])})
    # 「歧义」的判据是**命中的包号**而不是候选包号：lafei 同名有舰船(10117)与剧情角色(90024)两行，
    # 但盘上只有 cv-10117-gift.wav ⇒ 唯一命中，归属没有二义；两个号都有变体包时才放弃。
    if len({p for p in packs if p in VARIANT_PACK}) == 1:
        sk['voiceExtra'] = hits
        VOICE_EXTRA += 1

# ---------- 「只有台词、没有音频」的那批皮肤 ----------
# 判据与 build_skin_words.py 的第二趟同源：语音表里没这条皮肤、词表 m 里有 ⇒ 台词能显示、不能播。
# voiceCount 语义不变（仍= 可播音频条数），只加一个新字段，前端据此放行语音标签。
_W_M = SKIN_WORDS.get('m') or {}
_W_W = SKIN_WORDS.get('w') or {}
VOICE_TEXT_ONLY = 0
for stem, sk in skins.items():
    if sk.get('voiceCount'):
        continue
    sid = _W_M.get(stem)
    n = len(_W_W.get(sid) or {}) if sid else 0
    if n:
        sk['voiceText'] = n
        VOICE_TEXT_ONLY += 1


def ship_voice_text(sh):
    """船级「台词条数（无可播音频的那些皮肤）」——语音标签能不能放行要看这个 + voiceCount。"""
    return sum(sk.get('voiceText') or 0 for sk in sh['skins'] if not sk.get('voiceCount'))


def ship_voice_count(sh):
    """船级「语音 N 条」= 该船全部皮肤去重后的音频文件数（同一包同一条台词只算一次）。"""
    files = set()
    for sk in sh['skins']:
        e = SKIN_VOICE.get(sk['key'])
        if e:
            files |= {l.get('f') for l in (e.get('lines') or []) if l.get('f')}
        files |= set(sk.get('voiceExtra') or [])
    return len(files)

# ---------- 舰船/剧情角色 分层重分类（收集完成后，按皮肤标记+阵营+维基+塞壬覆盖综合判定）----------
# 单一字段不可靠：塞壬 unknown* 带 900000+ 假 stats（误判 ship）；联动可玩船(hdn/DOA/海王星/NieR)缺 stats（误判 story）。
SIREN_PREFIX = re.compile(r'^(unknown|sairen|error|npc|linghangyuan|lingyangzhe|tansuozhe|aijiang|tbniang|congmang|missd|missr|magician)')
COLLAB_SKIN = re.compile(r'(_doa|_tolove|_idol|_idolns)')   # 联动/偶像皮肤只出现在可玩船上 → 判舰船
# 用户确认的可玩船(Bon Homme Richard，仅 _alter 皮肤) + story_review.md 勾选的 31 条自机（2026-09-20）
EXTRA_SHIP = {'haorenlichade',
    'lafeiii','i404','tansuozhe','2b','a2','suweiaitongmengnew','linghangyuan3','lingyangzhe3',
    'i13','i168','i19','i25','i26','i56','i58','hdn101','hdn102','lanliii','congmang',
    'aijiang','aijiangbb','aijiangcl','aijiangcv','aijiangdd',
    'vtuber_aqua_wjz','vtuber_ayame_wjz','vtuber_fubuki_wjz','vtuber_matsuri_wjz',
    'vtuber_mio_wjz','vtuber_shion_wjz','vtuber_sora_wjz'}
WIKI_NAMES = set(meta_by_cn.keys())

# 「其他」档判据的唯一正本在 `scripts/gallery_buckets.py`（索引器与闸门共用一份，见那份的 §85 说明）
# 用户 2026-10-05 定档：类别只留 舰船 / 剧情角色 / 其他；`_alter`（META）不在此档，
# 例外只有 `npc*_alter` 与 `left/mid/right*_alter`。
from gallery_buckets import is_other     # noqa: E402


def reclassify():
    for s in ships.values():
        k = s['id']; name = s['name']
        if is_other(k):                                        # 组件立绘 / 剪影 / 剧情分身
            s['category'] = 'other'; s['faction'] = ''; s['type'] = ''; s['rarity'] = ''
        elif k in EXTRA_SHIP:                                  # 用户勾选确认的自机：舰船 + 保留 ship_meta 属性
            s['category'] = 'ship'
        elif ('？' in name) or SIREN_PREFIX.match(k):           # 塞壬/BOSS/NPC：剧情角色 + 清空战斗属性
            s['category'] = 'story'; s['faction'] = ''; s['type'] = ''; s['rarity'] = ''
        elif s['faction'] or name in WIKI_NAMES or any(COLLAB_SKIN.search(sk['key']) for sk in s['skins']):
            s['category'] = 'ship'
        else:
            s['category'] = 'story'
reclassify()

# 每船 skins 排序（默认在前，皮肤号升序）
def skin_sort(s):
    return (s['label'] != '默认立绘', s['key'])
for sh in ships.values():
    sh['skins'].sort(key=skin_sort)
    sh['voiceCount'] = ship_voice_count(sh)
    vt = ship_voice_text(sh)
    if vt:
        sh['voiceText'] = vt          # 只在有值时写，避免给 964 组船凭空加一个 0

ship_list = sorted(ships.values(),
                   key=lambda s: (s['npc'], not s['hasCn'], s['faction'], s['type'], s['name']))

# ---------- 剧情剪影外迁（§88：`_hei` 是剧情里的黑脸剪影，不是皮肤、也没有配音）----------
# 它们不进各船的「皮肤/变体」列表、也不进主网格，只从顶部第 4 档「剧情剪影」进（用户 2026-10-03 拍板）。
# ⚠️ 判据复用语音层那一份后缀定义（`extract_cv_voice.HEI_SUF`），**不许在这里再写一遍正则**——
#    同一套语义在两个脚本各写一份，就是 §85 那批错派的成因。
silhouettes = []
skin_owner = {sk['key']: sh['id'] for sh in ship_list for sk in sh['skins']}   # 剥完 _hei 后那张皮肤属于哪艘船
for sh in ship_list:
    keep = []
    for sk in sh['skins']:
        if not E.HEI_SUF.search(sk['key'].lower()):
            keep.append(sk)
            continue
        src_skin = E.HEI_SUF.sub('', sk['key'])        # aerjiliya_hei→aerjiliya、congmang_2_hei→congmang_2
        owner = skin_owner.get(src_skin)               # congmang_2 不是船，它是 congmang 的皮肤2
        silhouettes.append({
            'key': sk['key'], 'label': sk['label'], 'image': sk['image'],
            'ship': owner or sh['id'], 'srcSkin': src_skin if owner else '',
            'shipName': (ships.get(owner) or sh)['name']})
    sh['skins'] = keep
# 只剩剪影的船（1 艘）从主网格摘掉——它的全部"皮肤"都是剪影，留着就是一张假卡
ship_list = [sh for sh in ship_list if sh['skins']]

# （2026-10-04 那轮的「三族 45 条外迁进剪影档」已撤销 —— 见文件末尾的秘书舰 NPC 分卡块：
#  它们是彩色皮肤、各有配音包，不是剪影。用户 2026-10-05 改判为三档制。）

# 来源船必须真能在主网格点开，否则前端那条链接是死的（`shipCn` 就是这个意思）
alive = {sh['id'] for sh in ship_list}
for s in silhouettes:
    s['shipCn'] = s['ship'] in alive
silhouettes.sort(key=lambda x: (x['ship'], x['key']))

# ---------- 形态族外迁（`_alter`/`_memory`/`_dark`）----------
# 判据是**归属**而不是"有没有这个后缀"：`E.form_root(key)` 剥掉画法层之后若仍带形态后缀，
# 再看它等不等于这张卡的 id —— 等于就是这张卡自己的条目（META 卡的无背景版 `X_alter_n`，不动），
# 不等于才是挂错了宿主（本体卡下的 `hermit_alter`，搬走）。全库 147 条里 45 条属后者。
# `_hx` 按用户要求留在皮肤页做"和谐前后"对比，只有形态族自带的 `_hx` 才跟着本尊走。
FAMILY_CN = {'alter': '改造', 'memory': '记忆', 'dark': '暗黑'}
variants = []
for sh in ship_list:
    keep = []
    for sk in sh['skins']:
        root = E.form_root(sk['key'])
        fm = E.FORM_SUF.search(root)
        if not fm or root == sh['id'].lower():
            keep.append(sk)
            continue
        name = _clean_cn((SHIP_META.get(root) or {}).get('cn')) or root
        v = {'key': sk['key'], 'label': sk['label'], 'image': sk['image'],
             'root': root, 'family': fm.group(1), 'familyCn': FAMILY_CN[fm.group(1)],
             'name': name, 'host': sh['id'], 'hostName': sh['name']}
        for f in ('voiceCount', 'voiceText'):
            if sk.get(f):
                v[f] = sk[f]
        variants.append(v)
    sh['skins'] = keep
ship_list = [sh for sh in ship_list if sh['skins']]
alive = {sh['id'] for sh in ship_list}
for v in variants:
    v['hostOk'] = v['host'] in alive          # 宿主卡点不开的话，前端那条链接就是死的
variants.sort(key=lambda x: (x['family'], x['root'], x['key']))

# ---------- 秘书舰 NPC 三族：做成 3 张实体卡（2026-10-05 用户定三档制，它们属「剧情角色」）----------
# 2026-10-04 那轮把这三族 45 条整体搬进 `silhouettes`（当时只为了解决"显示成皮肤1/皮肤2"），
# 代价是它们**不再是卡**、还顶着「剧情剪影」的名——而它们是彩色皮肤、各有配音包。
# 权威源 `inputs/gamecfg/npc_painting_name.json`（由 secretary_special_ship 发布）每行带
# `character_id` + `cn` + `group` + `row_id`：character_id 就是"哪个角色"（1000 领航员-TB /
# 2000 领洋者-娜比娅 / 3000 探索者-艾普洛），group 是"哪套皮肤"，row_id 最小的那行是游戏自己的
# 默认形态（1000 → `tbniang`），拿它当卡 id。
NPC_TAB = json.load(open(os.path.join(ROOT, 'inputs', 'gamecfg', 'npc_painting_name.json'),
                         encoding='utf-8')) if os.path.exists(
    os.path.join(ROOT, 'inputs', 'gamecfg', 'npc_painting_name.json')) else {}
EXPLORER_BASE = re.compile(r'^(?:npc)?(?:tansuozhe|lingyangzhe|linghangyuan)\d*(?:_\d+)*(?:_n)?$')
by_char = collections.defaultdict(list)
for _k, _r in NPC_TAB.items():
    by_char[_r['character_id']].append((_r['row_id'], _k, _r))
sec_cards = {}          # character_id -> 船卡
for _cid, rows in by_char.items():
    rows.sort()
    base = rows[0][1]
    sec_cards[_cid] = {'id': base, 'name': rows[0][2]['cn'], 'hasCn': True, 'npc': True,
                       'type': '', 'rarity': '', 'faction': '', 'category': 'story',
                       'voiceCount': 0, 'skins': [], 'spineSkins': [], 'live2dSkins': [],
                       'charId': _cid}
_key2char = {}
for _cid, rows in by_char.items():
    for _rid, _k, _r in rows:
        _key2char[_k.lower()] = _cid
# 画法变体（`linghangyuan3_2_n` / `..._hx`）在权威表里没有自己的行，剥掉画法后缀再认角色，
# 否则它们会被当成"认不出"退回剪影档（实测 4 条）。
_SUF_RE = re.compile(r'(_n|_hx)+$')
for _k, _cid in list(_key2char.items()):
    _b = _SUF_RE.sub('', _k)
    if _b != _k:
        _key2char.setdefault(_b + '_n', _cid)
        _key2char.setdefault(_b + '_hx', _cid)

explorer_moved = 0
sec_orphans = []
for sh in ship_list:
    keep = []
    for sk in sh['skins']:
        kk = sk['key'].lower()
        cid = _key2char.get(kk)
        if cid is None and not EXPLORER_BASE.match(kk):
            keep.append(sk)
            continue
        if cid is None:                       # 表里没这一行：族内认不出角色，退回剪影档
            sec_orphans.append(sk['key'])
            silhouettes.append({'key': sk['key'], 'label': sk['label'], 'image': sk['image'],
                                'ship': sh['id'], 'srcSkin': '', 'shipName': sh['name']})
            continue
        card = sec_cards[cid]
        # 默认形态那一行**也是它自己的皮肤**（与普通船一致：卡 id == 默认皮肤 key）。
        # 曾经把它跳过 ⇒ `tbniang` 这张立绘从索引里整个消失（闸门报「皮肤掉出索引」），
        # 而且卡片的缩略图会掉到 `linghangyuan1_1` 上。
        card['skins'].append(sk)
        explorer_moved += 1
    sh['skins'] = keep
ship_list = [sh for sh in ship_list if sh['skins']]
for card in sec_cards.values():
    card['skins'].sort(key=lambda s: (NPC_TAB.get(s['key'], {}).get('group', 0), s['key']))
    # 船级语音数必须在**并完皮肤之后**重算：建卡那一刻 skins 还是空的，
    # 沿用创建时的 0 会让这三张卡在页面上继续显示"无语音"（实测 with_voice 一次都没动）。
    card['voiceCount'] = ship_voice_count(card)
    ships[card['id']] = card
    ship_list.append(card)
print('[i] 秘书舰 NPC：%d 条皮肤已并回 %d 张角色卡（%s），%d 条认不出角色退回剪影档 %s'
      % (explorer_moved, len(sec_cards),
         ' / '.join('%s×%d皮肤' % (c['name'], len(c['skins'])) for c in
                    sorted(sec_cards.values(), key=lambda x: x['charId'])),
         len(sec_orphans), ('：' + ', '.join(sorted(sec_orphans))) if sec_orphans else ''))

# ---------- 三档制的 category 落位（前端只认 ship / story / other 三个值）----------
# `silhouettes` 里现在只剩两类：真 `_hei` 剧情剪影、以及族内认不出角色的条目 ⇒ 都进「其他」。
# `variants` 是挂在别人卡下的 `_alter`/`_memory`/`_dark` 立绘 ⇒ 按**它自己那个 root** 判档：
# 组件立绘/剧情分身 → 其他，表里能查到自机舰级信息的 → 舰船，其余 → 剧情角色。
for s in silhouettes:
    s['category'] = 'other'
for v in variants:
    v['category'] = ('other' if is_other(v['root']) else
                     'ship' if (SHIP_META.get(v['root']) or {}).get('category') == 'ship'
                     else 'story')
alive = {sh['id'] for sh in ship_list}      # 秘书舰那 3 张卡是刚补进来的，宿主可达性要重算
for v in variants:
    v['hostOk'] = v['host'] in alive

cnt = {
    'ships': len(ship_list), 'with_cn': sum(1 for s in ship_list if s['hasCn']),
    'silhouettes': len(silhouettes),
    'variants': len(variants),
    'skins': sum(len(s['skins']) for s in ship_list),
    'spine': len(skins and [k for k,v in skins.items() if v['spine']]),
    'live2d': sum(1 for v in skins.values() if v['live2d']),
    'with_voice': sum(1 for s in ship_list if s['voiceCount']),
    'voice_skins': sum(1 for v in skins.values() if v.get('voiceCount')),
    'voice_text_skins': VOICE_TEXT_ONLY,        # 只有台词、没有可播音频的皮肤（§6 第 16 条）
    'npc': sum(1 for s in ship_list if s['npc']),
    'with_faction': sum(1 for s in ship_list if s['faction']),
    'ship': sum(1 for s in ship_list if s['category'] == 'ship'),
    'story': sum(1 for s in ship_list if s['category'] == 'story'),
    'other': sum(1 for s in ship_list if s['category'] == 'other')
               + len(silhouettes)
               + sum(1 for v in variants if v['category'] == 'other'),
}
index = {'generated': 'v2', 'counts': cnt, 'ships': ship_list,
         'silhouettes': silhouettes, 'variants': variants}
os.makedirs(GAL, exist_ok=True)
# ---------- 动作回落表必须跟当前 Live2D 动作一起更新（2026-10-19）----------
# 前端只读 gallery_v2/motion_chain.json；如果只更新 Live2D 不重建它，新动作会沿用旧 best/旧组清单。
# 放在写 index 前：任何一次正常索引重建（含 update_pipeline 的 derive）都会顺带刷新。
if os.path.abspath(GAL) == os.path.abspath(os.path.join(OUT, 'gallery_v2')):
    import subprocess
    _chain_script = os.path.join(ROOT, 'scripts', 'build_motion_chain_map.py')
    _rc = subprocess.call([sys.executable, _chain_script, '--write'])
    if _rc != 0:
        raise SystemExit('build_motion_chain_map.py 失败（rc=%d）—— 动作回落表未更新，拒绝写 index' % _rc)

json.dump(index, open(os.path.join(GAL, 'index.json'), 'w', encoding='utf-8'),
          ensure_ascii=False)
# 同时输出 index.js，令 index.html 可直接以 file:// 双击打开时也能读到数据
js = json.dumps(index, ensure_ascii=False, separators=(',', ':'))
open(os.path.join(GAL, 'index.js'), 'w', encoding='utf-8').write('window.GALLERY=' + js + ';')

unmapped = [s['id'] for s in ship_list if not s['hasCn'] and not s['npc']]
lines = [f"统计 {cnt}",
         f"语音源未命中索引的皮肤 {VOICE_ORPHAN}（JUNK/未导出目录），"
         f"skin_voice 共 {len(SKIN_VOICE)} 皮肤",
         f"非NPC未映射 ({len(unmapped)}): {unmapped[:60]}", "样例:"]
for s in ship_list[:6]:
    lines.append(f"  {s['id']}->{s['name']} 皮肤{len(s['skins'])} spine{len(s['spineSkins'])} l2d{len(s['live2dSkins'])} 语音{s['voiceCount']}")
open(os.path.join(GAL, '_build_report.txt'), 'w', encoding='utf-8').write('\n'.join(lines))
print('DONE', cnt)
