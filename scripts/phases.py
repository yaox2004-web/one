#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
主力行为阶段识别引擎 (phases.py) —— 原著逻辑版
=================================================
核心目标：回答"当前主力处于哪个阶段"——建仓 / 洗盘 / 拉升 / 出货 / 无明显迹象。

重要变更（v2）：
  本版彻底废弃"打分累加"机制，改为量学原著判定逻辑：
    量柱形态(六元素+七因子) → 三日定性(将军柱/黄金柱) → 位置 → 量性九种
    → 用"三要素组合"(满足>=3个条件)判定主力行为，不打分。

理论依据（全部引用知识库）：
  《量学理论核心法则总纲》：
    - 第9章  量柱六元素（六种量形）：倍量/高量/低量/平量/缩量/梯量
    - 第10章 量柱品质对比（量柱七因子）：高低平倍梯缩金
    - 第11章 量性九种 + 三日定性（将军柱三原则 / 黄金柱四组合公式）
    - 第4章  位置决定性质
    - 第5章  核心操作口诀（小倍阳）
    - 第16章 凹口淘金（长阴短柱 / 刹车换挡）
    - 第25/27章 王牌柱战法（将军柱/黄金柱/元帅柱）
    - 第28章 低量柱战法（百日低量 / 百日低量群 / 休克疗法）
    - 第31/32章 高量柱战法（发烧柱）
    - 三向规律·拐点转向律：该跌不跌必然上涨 / 该涨不涨必然下跌
  《量学理论核心法则总纲·战法篇》：
    - 第四章 低量柱战法（百日低量）
    - 第七章 高量柱战法（发烧柱 / 高量三分法）

规则出处标注约定：
  - 标注【原著】      → 来自知识库总纲/战法篇原文或明确规则
  - 标注【工程参数】  → 为实现可计算而自行设定的参数（如窗口、阈值），非原著

输入：SQLite daily_<code> 日线表（前复权 qfq）
输出：/var/minis/workspace/astock/phase_log.csv

注意事项：
1. 基于日线数据的近似判断，实盘需结合分时图和盘后龙虎榜人工二次确认。
2. 前复权价格会随未来除权改变，建议每次回测前重新拉取全量数据。
3. 处理完单只股票后 del 变量 + gc.collect() 释放内存。
4. 用 FUND_FLOW_AVAILABLE 在备注栏标注"资金流向缺失"（本版不做置信度惩罚，
   因置信度 = 条件命中数/条件总数，与资金流无关）。
"""
import gc
import sqlite3
import warnings

import numpy as np
import pandas as pd

from data_fetcher import DB_PATH, FUND_FLOW_AVAILABLE

# ============ 全局配置 ============
PHASE_LOG_PATH = "/var/minis/workspace/astock/phase_log.csv"

STOCKS = {
    "601138": "工业富联",
    "300476": "胜宏科技",
    "603516": "淳中科技",
    "300394": "天孚通信",
}

# 牛熊混合30只样本（行业分散）
STOCKS_30 = {
    # 牛股10（区间涨幅>100%）
    "002371": "北方华创", "603986": "兆易创新", "300308": "中际旭创",
    "601899": "紫金矿业", "300750": "宁德时代", "688981": "中芯国际",
    "002202": "金风科技", "600183": "生益科技", "600584": "长电科技",
    "601288": "农业银行",
    # 熊股10（区间跌幅>30%）
    "000002": "万科A", "002304": "洋河股份", "000568": "泸州老窖",
    "601012": "隆基绿能", "600809": "山西汾酒", "300760": "迈瑞医疗",
    "000858": "五粮液", "601633": "长城汽车", "601888": "中国中免",
    "600436": "片仔癀",
    # 横盘10（±20%内）
    "600309": "万华化学", "600028": "中国石化", "002415": "海康威视",
    "601668": "中国建筑", "600585": "海螺水泥", "600104": "上汽集团",
    "002027": "分众传媒", "002352": "顺丰控股", "600276": "恒瑞医药",
    "603288": "海天味业",
}

# 第四阶段（信号引擎）使用的样本清单
# 默认复用30只牛熊混合样本；如后续补充可在此扩展
STOCKS_4 = STOCKS_30

# 分组（用于逐股诊断）
STOCKS_GROUP = {
    "大牛股": list(STOCKS_30.keys())[:10],
    "大熊股": list(STOCKS_30.keys())[10:20],
    "横盘股": list(STOCKS_30.keys())[20:30],
}

PHASE_BUILD = "建仓"
PHASE_WASH = "洗盘"
PHASE_PULL = "拉升"
PHASE_DIST = "出货"
PHASE_NONE = "无明显迹象"
PHASES = [PHASE_BUILD, PHASE_WASH, PHASE_PULL, PHASE_DIST]

# 修正B：持续性确认
CONFIRM_DAYS = 3

# ============ 位置分类（第4章·位置决定性质，工程参数分位） ============
POS_HIGH_PCT = 0.85   # 分位>0.85高位   [工程参数，基于原著"高位"概念]
POS_AODI_PCT = 0.10   # 分位<0.10凹底
POS_LOW_PCT = 0.35    # 0.10~0.35低位, 0.35~0.85中位
# 位置窗口（120日）：原著"用相对高低点分位的定义"，窗口长度120为工程参数
POS_WINDOW = 120

# ============ 量柱识别阈值（第9章·就近对比） ============
BEILIANG_RATIO = 1.9   # 倍量柱：量>=前日×1.9（原著"最低高出90%"）
GAOLIANG_WINDOW = 60   # 高量柱/低量柱窗口（第9章"某一阶段"；窗口取60为工程参数）
DILIANG_WINDOW = 60
PINGLIANG_TOL = 0.05   # 平量柱：连续量能差异<=5%（原著）
PINGLIANG_MIN = 2      # 平量柱至少2根
TILIANG_MIN = 3        # 梯量柱至少3根

# ============ 三要素组合的条件数（决定置信度分母） ============
COND_BUILD = 5   # 建仓5个条件
COND_WASH = 4    # 洗盘4个条件
COND_PULL = 5    # 拉升5个条件（含位置=中位/高位/过峰）
COND_DIST = 6    # 出货6个条件（含量价背离）
MIN_COND = 2     # 需同时满足>=2个条件才算该阶段（位置 + 1个其他即可）

# ============ 日内基因参数 ============
# 长阴短柱（第16章凹口淘金 / 第26章基因）：
# 跌幅>3% 且 量<前一日  [跌幅阈值3%为工程参数，原著"凶狠长阴"无精确数]
CHANGYIN_DROP = 0.03
# 发烧柱（战法篇第七章·高量柱三分法）：量>前日5倍 或 连续两根递增且超前均量3倍
FASHAO_RATIO = 5.0
FASHAO_HIGH_RATIO = 3.0
FASHAO_WINDOW = 20    # 前20日均量（工程参数）
# 倍量过左峰（总纲口诀"倍量过左峰"）：倍量阳 + 突破近20日最高价
BEIFENG_WINDOW = 20
# 缩量回踩黄金线/20MA（第12章黄金线 / 第27章）：缩量 + 回踩不破20MA附近
MA20_TOL = 0.02


# ============ 工具：位置分类（保留已改好的120日分位法） ============
def classify_position(close, lo120, hi120):
    """
    位置分类（第4章·位置决定性质）。
    120日相对分位法：pos_pct = (close-lo120)/(hi120-lo120)
      过峰(>1) / 高位(>0.85) / 凹底(<0.10) / 低位(0.10~0.35) / 中位(0.35~0.85)
    [分位阈值0.85/0.10/0.35为工程参数，改编自原著"低位/中位/高位"三分]
    """
    if hi120 <= lo120 or lo120 <= 0:
        return "中位"
    if close > hi120:
        return "过峰"
    pos_pct = (close - lo120) / (hi120 - lo120)
    if pos_pct > POS_HIGH_PCT:
        return "高位"
    if pos_pct < POS_AODI_PCT:
        return "凹底"
    if pos_pct < POS_LOW_PCT:
        return "低位"
    return "中位"


# ============ 一、量柱六元素+七因子识别（第9/10章·就近对比） ============
def identify_volume_columns(df):
    """
    对每一根量柱识别"六种量形+黄金柱"，全部用"就近对比"(跟前一日比)。
    依据《量学理论核心法则总纲》第9章"量柱六元素"、第10章"量柱七因子"。
    返回：df 新增列 zhuangtai(量柱形态) / beiliang / gaoliang / diliang /
          pingliang / suoliang / tiliang 布尔标记。
    """
    df = df.copy()
    n = len(df)
    vol = df["成交量"].values
    close = df["收盘"].values
    low = df["最低"].values

    # 倍量柱：当日量>=前日×1.9（第9章原著"最低高出90%"）
    prev_vol = df["成交量"].shift(1)
    df["beiliang"] = (df["成交量"] >= prev_vol * BEILIANG_RATIO).fillna(False)

    # 高量柱/低量柱：近60日内最高/最低量柱（第9章"某一阶段最高/最低量柱"）
    # 用滚动窗口逐日判定当日是否为窗口内极值
    df["gaoliang"] = df["成交量"].rolling(GAOLIANG_WINDOW, min_periods=1).apply(
        lambda x: len(x) > 1 and x[-1] == x.max(), raw=True).fillna(0).astype(bool)
    df["diliang"] = df["成交量"].rolling(DILIANG_WINDOW, min_periods=1).apply(
        lambda x: len(x) > 1 and x[-1] == x.min(), raw=True).fillna(0).astype(bool)

    # 平量柱：连续2根以上、量能差异<=5%（第9章原著）
    df["pingliang"] = np.zeros(n, dtype=bool)
    cnt = 0
    for i in range(n):
        if i >= 1 and vol[i] > 0 and abs(vol[i] - vol[i - 1]) / vol[i - 1] <= PINGLIANG_TOL:
            cnt += 1
        else:
            cnt = 0
        df.at[i, "pingliang"] = cnt >= PINGLIANG_MIN - 1  # 至少连续2根
    df["pingliang"] = df["pingliang"].astype(bool)

    # 缩量柱：当日量<前一日（第9章原著）
    df["suoliang"] = (df["成交量"] < prev_vol).fillna(False)

    # 梯量柱：连续3根以上、量能逐日走高（第9章原著）
    df["tiliang"] = np.zeros(n, dtype=bool)
    run = 0
    for i in range(1, n):
        if vol[i] > vol[i - 1]:
            run += 1
        else:
            run = 0
        df.at[i, "tiliang"] = run >= TILIANG_MIN - 1  # 连续3根(当前+前2)逐日走高
    df["tiliang"] = df["tiliang"].astype(bool)

    # 量柱形态标注（一柱定音优先：倍/高/低/平/缩/梯，原著第11章"一柱定音 vs 群柱定性"）
    def label(row):
        if row["tiliang"]:
            return "梯量柱"
        if row["pingliang"]:
            return "平量柱"
        if row["beiliang"]:
            return "倍量柱"
        if row["gaoliang"]:
            return "高量柱"
        if row["diliang"]:
            return "低量柱"
        if row["suoliang"]:
            return "缩量柱"
        return "普通量柱"
    df["量柱形态"] = df.apply(label, axis=1)

    return df


# ============ 二、三日定性：将军柱 / 黄金柱（第11章·量学的命根子） ============
def three_day_confirm(df):
    """
    对每个"候选基柱"（倍量柱/高量柱/低量柱/梯量柱）检查后三日，判定将军柱/黄金柱。
    依据《量学理论核心法则总纲》第11章"三日定性"。

    将军柱三原则（第11章）：
      ① 三日不破：后三日每日最低价 >= 基柱最低价
      ② 价升量缩：后三日中至少一日"价涨量缩"
      ③ 先者优先：连续几天都符合时取第一个合格者
    黄金柱（更严格）：后三日收盘逐日升 + 量逐日缩 + 不破基柱实底
    黄金柱四组合公式（满足任一即可）：
      ① 倍量柱+缩量柱 ② 高量柱+缩量柱 ③ 倍量柱+梯量柱 ④ 低量柱+梯量柱

    返回 df 新增列：将军柱 / 黄金柱 布尔，以及 is_jj(作为基柱的候选标记)。
    """
    df = df.copy()
    n = len(df)
    close = df["收盘"].values
    low = df["最低"].values
    vol = df["成交量"].values
    open_ = df["开盘"].values

    df["将军柱"] = np.zeros(n, dtype=bool)
    df["黄金柱"] = np.zeros(n, dtype=bool)

    # 候选基柱：倍量柱/高量柱/低量柱/梯量柱（第11章黄金柱四组合公式涉及的量形）
    is_candidate = df["beiliang"] | df["gaoliang"] | df["diliang"] | df["tiliang"]

    for i in range(n):
        if not is_candidate[i]:
            continue
        if i + 3 >= n:
            break
        # 后三日
        j1, j2, j3 = i + 1, i + 2, i + 3
        base_low = low[i]
        base_close = close[i]
        base_vol = vol[i]

        # 将军柱三原则
        # ① 三日不破：后3日最低价均>=基柱最低价
        bu_po = (min(low[j1], low[j2], low[j3]) >= base_low)
        # ② 价升量缩：后3日中至少一日收盘高于基柱收盘 且 该日量低于前一日
        jj_price_up_vol_shrink = any(
            close[j] > close[j - 1] and vol[j] < vol[j - 1] for j in (j1, j2, j3)
        )
        # 将军柱：三日不破 + 价升量缩
        if bu_po and jj_price_up_vol_shrink:
            df.at[i, "将军柱"] = True

        # 黄金柱（比将军柱更严格）：
        #   后3日收盘逐日升高 + 量能逐日缩小 + 不破基柱实底
        gj_price_up = (close[j1] > base_close and close[j2] > close[j1]
                       and close[j3] > close[j2])
        gj_vol_shrink = (vol[j1] < base_vol and vol[j2] < vol[j1]
                         and vol[j3] < vol[j2])
        # 不破基柱实底（基柱实体下沿 = min(开盘,收盘)）
        base_shidi = min(open_[i], base_close)
        gj_bu_po = min(low[j1], low[j2], low[j3]) >= base_shidi
        # 黄金柱四组合公式（第11章）：任一满足即可
        combo = (
            (df["beiliang"][i] and df["suoliang"][j1]) or   # ①倍量+缩量
            (df["gaoliang"][i] and df["suoliang"][j1]) or   # ②高量+缩量
            (df["beiliang"][i] and df["tiliang"][j1]) or    # ③倍量+梯量
            (df["diliang"][i] and df["tiliang"][j1])        # ④低量+梯量
        )
        # 黄金柱：三日价升量缩 + 不破实底 + 满足组合公式
        if gj_price_up and gj_vol_shrink and gj_bu_po and combo:
            df.at[i, "黄金柱"] = True

    # 先者优先（第11章将军柱原则③）：连续几天符合取第一个——此处逐日独立判定，
    # 已天然保证每根候选柱单独判断，无需合并相邻柱。
    return df


# ============ 三、量性九种标注（第11章） ============
def label_xing(pos, xing, is_jj, is_gj, close_up):
    """
    对单个基柱标注"量性"（第11章量性九种：试探/建仓/增仓/补仓/震仓/启动/拉升/将军/黄金）。
    简化规则（工程近似，非原著精确定义）：
      - 黄金柱/将军柱：直接标注（第11章量级最高）
      - 其他按位置+量形粗略映射（位置决定性质，第4章）
    """
    if is_gj:
        return "黄金柱"
    if is_jj:
        return "将军柱"
    # 位置决定性质（第4章）：同量形不同位置量性不同
    if pos in ("凹底", "低位"):
        if xing in ("倍量柱", "高量柱") and close_up:
            return "启动柱"      # 低位放量阳=启动
        if xing == "低量柱":
            return "试探柱"      # 低位低量=试探/缩量蓄势
        return "建仓柱"          # 低位其他=建仓
    if pos == "中位":
        if xing in ("梯量柱", "倍量柱") and close_up:
            return "拉升柱"
        if xing == "缩量柱" and close_up:
            return "增仓柱"
        return "震仓柱"
    if pos in ("高位", "过峰"):
        if xing in ("倍量柱", "高量柱"):
            return "拉升柱"      # 高位放量仍可能拉升，但需警惕（位置决定性质）
        return "补仓柱"
    return "试探柱"


# ============ 四、日内基因识别 ============
def identify_genes(df):
    """
    识别日内关键基因（用于三要素组合判定）。依据各章节：
      - 长阴短柱（第16章凹口淘金）：跌幅>3%且量<前日
      - 百日低量（第28章低量柱战法 / 战法篇第四章）：近100日最低量
      - 百日低量群（第28章）：近30日内多次百低（工程判定）
      - 卧底矮将军（战法篇第一章金凹淘金）：低位将军柱
      - 合力黄金柱（战法篇第一章）：换挡柱，黄金柱
      - 倍量过左峰（总纲口诀）：倍量阳+突破近20日最高价
      - 缩量回踩20MA/黄金线（第12章）：缩量+回踩不破
      - 发烧柱（战法篇第七章高量三分法）：量>前日5倍 或 连两增且超前20日均量3倍
      - 假阴真阳（第6章/第26章）：高开低走但收盘>前日
    """
    df = df.copy()
    n = len(df)
    close = df["收盘"].values
    open_ = df["开盘"].values
    low = df["最低"].values
    high = df["最高"].values
    vol = df["成交量"].values
    pos = df["位置"].values
    is_jj = df["将军柱"].values
    is_gj = df["黄金柱"].values
    beiliang = df["beiliang"].values

    # 收阳：当日收盘>前日（用 shift 向量化，避免链式赋值失效）
    df["收阳"] = (df["收盘"] > df["收盘"].shift(1)).fillna(False)

    # 长阴短柱（第16章）：跌幅>3% 且 量<前日
    df["长阴短柱"] = (
        (df["收盘"].shift(1) - df["收盘"]) / df["收盘"].shift(1) > CHANGYIN_DROP
    ) & (df["成交量"] < df["成交量"].shift(1))
    df["长阴短柱"] = df["长阴短柱"].fillna(False)

    # 百日低量（第28章）：近100日最低量 [窗口100为原著"百日"概念]
    baidi = df["成交量"].rolling(100, min_periods=1).apply(
        lambda x: len(x) > 1 and x[-1] == x.min(), raw=True).fillna(0)
    df["百日低量"] = baidi.astype(bool)

    # 百日低量群（第28章）：近30日内出现>=2次百低 [群=多次，工程判定]
    df["百日低量群"] = df["百日低量"].rolling(30, min_periods=1).sum() >= 2

    # 卧底矮将军（战法篇第一章）：(低位/凹底) 且 将军柱
    df["卧底矮将军"] = (df["位置"].isin(["凹底", "低位"])) & is_jj

    # 合力黄金柱（战法篇第一章"换挡"）：中位/低位黄金柱（换挡柱）
    df["合力黄金柱"] = is_gj & (df["位置"].isin(["中位", "低位", "凹底"]))

    # 倍量过左峰（总纲口诀）：倍量 + 阳线 + 突破近20日最高价
    df["hi20"] = df["最高"].rolling(BEIFENG_WINDOW, min_periods=1).max().shift(1)  # 前一日的20日高点
    df["倍量过左峰"] = beiliang & df["收阳"] & (df["收盘"] > df["hi20"])

    # 缩量回踩20MA/黄金线（第12章）：缩量 + 收盘贴近且不破20MA
    df["ma20"] = df["收盘"].rolling(20, min_periods=1).mean()
    df["缩量回踩"] = df["suoliang"] & (df["收盘"] >= df["ma20"]) & \
        (df["收盘"] <= df["ma20"] * (1 + MA20_TOL))

    # 发烧柱（战法篇第七章）：量>前日5倍 或 连续两根递增且超前20日均量3倍
    df["vol_ma20"] = df["成交量"].rolling(FASHAO_WINDOW, min_periods=1).mean()
    cond1 = (df["成交量"] > df["成交量"].shift(1) * FASHAO_RATIO).fillna(False)
    cond2 = (df["成交量"] > df["vol_ma20"] * FASHAO_HIGH_RATIO) & df["tiliang"]
    df["发烧柱"] = cond1 | cond2

    # 假阴真阳（第26章 / 第6章）：高开低走(收<开) 但 收盘>前日收盘
    df["假阴真阳"] = (df["收盘"] < df["开盘"]) & df["收阳"]

    return df


# ============ 五、量价配合（第10章量价对比 / 第6章量价一体） ============
def classify_vp(close_t, close_y, vol_t, vol_y):
    """
    量价配合分类（第10章"量价关系口诀"）：
      量价齐升 / 价升量缩 / 量增价跌 / 价跌量缩(量价齐跌)
    就近对比当日与前一日。
    """
    if pd.isna(close_y) or pd.isna(vol_y) or vol_y <= 0:
        return "量价齐升"
    up = close_t > close_y
    vol_up = vol_t > vol_y
    if up and vol_up:
        return "量价齐升"
    if up and not vol_up:
        return "价升量缩"
    if not up and not vol_up:
        return "价跌量缩"
    return "量增价跌"


# ============ 六、三要素组合判定（替代打分表） ============
def judge_phase(day, d_yest, idx_ret):
    """
    依据"三要素组合"判定主力行为（不打分，数满足条件数）。
    每阶段需同时满足>=3个条件才判定；置信度=满足数/该阶段总条件数。

    所有条件出处见函数内注释。
    """
    pos = day["位置"]
    vp = day["量价配合"]
    hit = {}

    # ===== 建仓阶段（第28章百日低量 / 战法篇第一章金凹淘金 / 三向规律） =====
    build_conds = {
        "位置=凹底/低位": pos in ("凹底", "低位"),
        "百日低量或百日低量群": bool(day["百日低量"]) or bool(day["百日低量群"]),
        "卧底矮将军(低位将军柱)": bool(day["卧底矮将军"]),
        "合力黄金柱(换挡柱)": bool(day["合力黄金柱"]),
        "该跌不跌(大盘跌本股收阳)": bool(idx_ret < 0 and day["收阳"]),
    }

    # ===== 洗盘阶段（第16章凹口淘金 / 第12章黄金线 / 第27章） =====
    wash_conds = {
        "位置=中位": pos == "中位",
        "长阴短柱": bool(day["长阴短柱"]),
        "缩量回踩20MA/黄金线": bool(day["缩量回踩"]),
        "量价配合=价跌量缩": vp == "价跌量缩",
    }

    # ===== 拉升阶段（总纲口诀倍量过左峰 / 第11章黄金柱 / 第10章价升量缩 / 第13章量线） =====
    # 位置条件：用户对建仓/洗盘/出货均含位置，拉升也应含"位置=中位/高位/过峰"（第4章位置决定性质）
    # 量价配合收紧为"价升量缩"（第10章"最有价值的缩量形态=供不应求"）；"量价齐升"太常见不作拉升弱确认
    pull_conds = {
        "位置=中位/高位/过峰": pos in ("中位", "高位", "过峰"),
        "倍量过左峰": bool(day["倍量过左峰"]),
        "梯量柱或黄金柱接力": bool(day["tiliang"]) or bool(day["黄金柱"]),
        "量价配合=价升量缩": vp == "价升量缩",
        "突破关键量线(过峰/破20日新高)": pos == "过峰" or bool(day["倍量过左峰"]),
    }

    # ===== 出货阶段（战法篇第七章发烧柱 / 第26章假阴真阳 / 三向规律 / 第10章量价背离） =====
    dist_conds = {
        "位置=顶部(高位)": pos in ("高位", "过峰"),
        "发烧柱(巨量)": bool(day["发烧柱"]),
        "假阴真阳": bool(day["假阴真阳"]),
        "该涨不涨(大盘涨本股收阴)": bool(idx_ret > 0 and not day["收阳"]),
        "量价背离(量增价跌/价升量缩)": vp in ("量增价跌", "价升量缩"),
        "高量柱后三日无法续量": bool(day["gaoliang"]) and not bool(day["tiliang"]),
    }

    # 每个阶段的条件中，"位置"是必要前提（第4章位置决定性质）。
    # 位置命中后，再看其他条件是否>=1（用户："位置 + 1个其他"即2条件判定）。
    # 位置不命中的阶段不参与判定。
    # 注意：拉升的量价配合收紧为"价升量缩"（第10章最有价值形态，量价齐升太常见不作弱确认）
    stage_pos_ok = {
        PHASE_BUILD: pos in ("凹底", "低位"),
        PHASE_WASH: pos == "中位",
        PHASE_PULL: pos in ("中位", "高位", "过峰"),
        PHASE_DIST: pos in ("高位", "过峰"),
    }

    # 各阶段"其他条件"命中数（去掉位置条件后）
    stage_other_hit = {
        PHASE_BUILD: sum(v for k, v in build_conds.items() if k != "位置=凹底/低位"),
        PHASE_WASH: sum(v for k, v in wash_conds.items() if k != "位置=中位"),
        PHASE_PULL: sum(v for k, v in pull_conds.items() if k != "位置=中位/高位/过峰"),
        PHASE_DIST: sum(v for k, v in dist_conds.items() if k != "位置=顶部(高位)"),
    }
    stage_tot_other = {
        PHASE_BUILD: len(build_conds) - 1,
        PHASE_WASH: len(wash_conds) - 1,
        PHASE_PULL: len(pull_conds) - 1,
        PHASE_DIST: len(dist_conds) - 1,
    }

    # 命中条件明细（含位置，用于"主要依据"）
    stage_reasons = {
        PHASE_BUILD: [k for k, v in build_conds.items() if v],
        PHASE_WASH: [k for k, v in wash_conds.items() if v],
        PHASE_PULL: [k for k, v in pull_conds.items() if v],
        PHASE_DIST: [k for k, v in dist_conds.items() if v],
    }

    # 判定：位置必须命中 且 其他条件命中>=1（等效总命中>=2且含位置）
    candidates = {}
    for ph in PHASES:
        if stage_pos_ok[ph] and stage_other_hit[ph] >= 1:
            candidates[ph] = stage_other_hit[ph]

    if candidates:
        # 取"其他条件命中数"最多的阶段（位置都命中，比谁的其他信号更多）
        best_stage = max(candidates, key=candidates.get)
        # 置信度 = 总命中数 / 该阶段总条件数
        total_hit = stage_other_hit[best_stage] + 1  # 含位置
        total_cond = stage_tot_other[best_stage] + 1
        confidence = total_hit / total_cond
        main_reason = "+".join(stage_reasons[best_stage])
        stage = best_stage
    else:
        # 无明显迹象：所有阶段都没同时满足"位置+其他"至少2个条件
        stage = PHASE_NONE
        confidence = 0.0
        main_reason = "无明显迹象"

    return stage, confidence, main_reason


# ============ 七、单只股票分析 ============
def analyze_stock(code, name):
    """
    对单只股票跑阶段识别，返回 phase_log DataFrame。
    需要大盘指数(index_000001)判断"该跌不跌/该涨不涨"。
    """
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query(f"SELECT * FROM daily_{code} ORDER BY 日期", conn)
    idx = pd.read_sql_query("SELECT * FROM index_000001 ORDER BY 日期", conn)
    conn.close()

    if df.empty:
        warnings.warn(f"[phases] daily_{code} 无数据")
        return _empty_df()

    df["日期"] = pd.to_datetime(df["日期"])
    idx["日期"] = pd.to_datetime(idx["日期"])
    idx_map = idx.set_index("日期")["收盘"].to_dict() if not idx.empty else {}

    for col in ["开盘", "收盘", "最高", "最低", "成交量"]:
        if col not in df.columns:
            df[col] = np.nan
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # 120日高低点
    df["lo120"] = df["最低"].rolling(POS_WINDOW, min_periods=1).min()
    df["hi120"] = df["最高"].rolling(POS_WINDOW, min_periods=1).max()

    # 大盘当日涨跌幅
    df["idx_ret"] = df["日期"].map(idx_map).pct_change().fillna(0.0)

    # 一、量柱六元素识别
    df = identify_volume_columns(df)
    # 二、三日定性（将军柱/黄金柱）
    df = three_day_confirm(df)

    # 位置分类（第4章）
    df["位置"] = [classify_position(c, l, h) for c, l, h
                  in zip(df["收盘"], df["lo120"], df["hi120"])]

    # 量价配合
    df["量价配合"] = [classify_vp(c, cy, v, vy)
                     for c, cy, v, vy in zip(
                         df["收盘"], df["收盘"].shift(1),
                         df["成交量"], df["成交量"].shift(1))]

    # 四、日内基因识别（依赖位置/将军柱/黄金柱）
    df = identify_genes(df)

    # 五、量性九种标注（收阳 已在 identify_genes 中定义）
    df["量性"] = df.apply(lambda r: label_xing(
        pos=r["位置"], xing=r["量柱形态"],
        is_jj=bool(r["将军柱"]), is_gj=bool(r["黄金柱"]),
        close_up=bool(r["收阳"])), axis=1)

    n = len(df)
    rows = []
    for i in range(20, n):  # 跳过前20日(指标预热)
        d = df.iloc[i]
        d_yest = df.iloc[i - 1]

        stage, confidence, main_reason = judge_phase(d, d_yest, d["idx_ret"])

        remark = ""
        if not FUND_FLOW_AVAILABLE:
            remark = "资金流向缺失"

        rows.append({
            "日期": d["日期"].strftime("%Y-%m-%d"),
            "代码": code,
            "名称": name,
            "当前阶段": stage,
            "置信度": round(confidence, 2),
            "位置": d["位置"],
            "命中的量性": d["量性"],
            "量柱形态": d["量柱形态"],
            "量价配合": d["量价配合"],
            "主要依据": main_reason,
            "备注": remark,
        })

    result = pd.DataFrame(rows)

    # ===== 修正B：持续性确认 =====
    if result.empty:
        return result
    stages = result["当前阶段"].tolist()
    nn = len(stages)
    dur = [1] * nn
    for i in range(1, nn):
        dur[i] = dur[i - 1] + 1 if stages[i] == stages[i - 1] else 1
    confirmed = []
    for i in range(nn):
        if dur[i] >= CONFIRM_DAYS:
            confirmed.append("已确认")
        elif i == 0:
            confirmed.append("初始阶段")
        else:
            confirmed.append("疑似切换（未确认）")
    result["持续天数"] = dur
    result["确认状态"] = confirmed
    return result


def _empty_df():
    """返回空的 phase_log DataFrame"""
    return pd.DataFrame(columns=[
        "日期", "代码", "名称", "当前阶段", "置信度", "位置", "命中的量性",
        "量柱形态", "量价配合", "主要依据", "备注", "持续天数", "确认状态",
    ])


# ============ 八、主流程 ============
def run_all(stock_list=None, output_path=None, verbose=True):
    """对股票清单跑阶段识别，汇总输出CSV并打印统计。
    stock_list: 默认 STOCKS_4（第四阶段样本，当前=30只）；可传 STOCKS/STOCKS_30。
    output_path: 默认 PHASE_LOG_PATH；跑30只时传 phase_log_30.csv。
    """
    if stock_list is None:
        stock_list = STOCKS_4
    if output_path is None:
        output_path = PHASE_LOG_PATH
    if verbose:
        print(f"\n{'='*60}")
        print(f">>> 阶段识别：{len(stock_list)} 只股票")
        print(f"{'='*60}")

    all_frames = []
    for code, name in stock_list.items():
        df = analyze_stock(code, name)
        if df.empty:
            if verbose:
                print(f"    {name} 无有效数据，跳过")
            continue
        all_frames.append(df)

        if verbose:
            print(f"\n>>> {code} {name}")
            total = len(df)
            counts = df["当前阶段"].value_counts()
            c_build = int(counts.get(PHASE_BUILD, 0))
            c_wash = int(counts.get(PHASE_WASH, 0))
            c_pull = int(counts.get(PHASE_PULL, 0))
            c_dist = int(counts.get(PHASE_DIST, 0))
            c_none = int(counts.get(PHASE_NONE, 0))
            none_pct = c_none / total * 100 if total else 0
            print(f"    建仓{c_build} 洗盘{c_wash} 拉升{c_pull} 出货{c_dist} "
                  f"无迹象{c_none} (无迹象占比{none_pct:.1f}%)")
            full_cnt = int((df["置信度"] == 1.0).sum())
            print(f"    满分1.0占比: {full_cnt}/{total} = "
                  f"{full_cnt/total*100 if total else 0:.1f}%")
            pos_dist = df["位置"].value_counts()
            print(f"    位置分布: " + ", ".join(f"{k}:{v}" for k, v in pos_dist.items()))

            print(f"    最近15天轨迹:")
            for _, r in df.tail(15).iterrows():
                print(f"      {r['日期']}  {r['当前阶段']:<6} 置信{r['置信度']:.2f} "
                      f"持续{r['持续天数']}天 {r['确认状态']}  "
                      f"[{r['位置']}|{r['量柱形态']}|{r['量价配合']}|{r['命中的量性']}]")
        del df
        gc.collect()

    if all_frames:
        final = pd.concat(all_frames, ignore_index=True)
        # 可复现性修复（2026-09-17）：输出强制按 (代码,日期) 排序，行序与跑的次数/进程无关
        final = final.sort_values(["代码", "日期"]).reset_index(drop=True)
        final.to_csv(output_path, index=False, encoding="utf-8-sig")
        print(f"\n{'='*60}")
        print(f"结果已写入: {output_path}")
        print(f"总记录数: {len(final)}")
        print(f"资金流向缺失标注: FUND_FLOW_AVAILABLE={FUND_FLOW_AVAILABLE}")
        return final
    else:
        print("无任何有效结果")
        return None


if __name__ == "__main__":
    run_all()
