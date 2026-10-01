#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
量学死信号对照组 v0.1 (death_signal_payoff.py)
================================================
Phase 5 加餐: 给"坏信号"也建兑现率对照组, 两面镜子照市场。
系统已统计"好信号之后发生了什么"(Spring/SOS), 现在统计"坏信号之后发生了什么"。

死信号定义(全部只用事件日收盘前已知信息, 无未来函数):
  1. 巨量阴线  : 成交量 >= 2.0 × 前20日均量, 且 收盘 < 开盘
  2. 长上影线  : 上影线 >= 2%×收盘价, 且 上影线 >= 2×实体
  3. 放量破位  : 成交量 >= 1.5 × 前20日均量, 且 收盘 < 前20日最低价

口径(与Phase 5一致, 用户拍板):
  胜 = T+N收盘 > 事件日收盘 (收盘价口径)
  窗口 T+1/3/5/10/20, 样本<30标"样本不足", T+10/20右删失属正常

纯新增文件: 只读 data/kline, 写 data/analysis/death_signal_report.json
不碰任何地基模块。指数(sh000*/sz399*/bj899*)不参与。
版本: v0.1 (2026-10-02)
"""

import os
import json
from datetime import datetime, timezone, timedelta

# ============ 参数 ============
KLINE_DIR = 'data/kline'
MARKETS = ['sh', 'sz', 'bj']
OUT_PATH = 'data/analysis/death_signal_report.json'
WINDOWS = [1, 3, 5, 10, 20]
VOL_MA = 20            # 均量/新低回看天数
MIN_SAMPLE = 30       # 样本不足红线(用户拍板口径)
VOL_RATIO_BIG = 2.0   # 巨量: 2倍于20日均量
VOL_RATIO_BREAK = 1.5 # 放量破位: 1.5倍
SHADOW_PCT = 0.02     # 长上影: 上影 >= 2%×收盘价
SHADOW_BODY = 2.0     # 长上影: 上影 >= 2×实体

BJ = timezone(timedelta(hours=8))


class Group:
    """一个分组的兑现率累计器"""

    def __init__(self, name):
        self.name = name
        self.n = 0
        self.win = {w: 0 for w in WINDOWS}
        self.cnt = {w: 0 for w in WINDOWS}
        self.ret20 = []

    def add(self, closes, i, total):
        """记一个事件日: i为事件日下标, total为K线总数"""
        self.n += 1
        base = closes[i]
        for w in WINDOWS:
            j = i + w
            if j < total:
                self.cnt[w] += 1
                if closes[j] > base:
                    self.win[w] += 1
                if w == 20:
                    self.ret20.append((closes[j] / base - 1) * 100.0)

    def rate(self, w):
        if self.cnt[w] == 0:
            return None
        return self.win[w] / self.cnt[w] * 100.0

    def to_dict(self):
        return {
            'name': self.name,
            'n_events': self.n,
            'windows': {f'T+{w}': {'n': self.cnt[w], 'win': self.win[w],
                                   'rate': round(self.rate(w), 2) if self.rate(w) is not None else None}
                        for w in WINDOWS},
            't20_mean_ret': round(sum(self.ret20) / len(self.ret20), 2) if len(self.ret20) >= MIN_SAMPLE else None,
        }


def iter_stocks():
    """遍历全市场股票K线文件(跳过指数)"""
    for mkt in MARKETS:
        d = os.path.join(KLINE_DIR, mkt)
        if not os.path.isdir(d):
            continue
        for fname in sorted(os.listdir(d)):
            if not fname.endswith('.json'):
                continue
            code = fname[:-5]
            if code.startswith('sh000') or code.startswith('sz399') or code.startswith('bj899'):
                continue  # 指数不参与
            yield code, os.path.join(d, fname)


def load_kline(path):
    """读K线: {"name":..,"klines":[[日期,开,收,高,低,量],...]} → [(日期,开,收,高,低,量)]"""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        raw = data.get('klines', [])
        k = []
        for item in raw:
            try:
                k.append((str(item[0])[:10], float(item[1]), float(item[2]),
                          float(item[3]), float(item[4]), float(item[5])))
            except (ValueError, IndexError, TypeError):
                continue
        return k
    except Exception:
        return []


def detect(k, groups, baseline):
    """单只股票扫描: 前置条件 → 三类死信号 + 基线"""
    n = len(k)
    if n <= VOL_MA + 1:
        return
    o = [x[1] for x in k]
    c = [x[2] for x in k]
    h = [x[3] for x in k]
    lo = [x[4] for x in k]
    v = [x[5] for x in k]

    for i in range(VOL_MA, n):
        if c[i] <= 0:
            continue
        # 基线: 任意交易日(与死信号同池对比, 公平)
        baseline.add(c, i, n)

        ma_v = sum(v[i - VOL_MA:i]) / VOL_MA
        prior_low = min(lo[i - VOL_MA:i])
        vol = v[i]

        # 1. 巨量阴线
        if ma_v > 0 and vol >= VOL_RATIO_BIG * ma_v and c[i] < o[i]:
            groups['巨量阴线'].add(c, i, n)
        # 2. 长上影线
        body = abs(c[i] - o[i])
        upper = h[i] - max(c[i], o[i])
        if upper > 0 and upper >= SHADOW_PCT * c[i] and upper >= SHADOW_BODY * max(body, 1e-9):
            groups['长上影线'].add(c, i, n)
        # 3. 放量破位
        if ma_v > 0 and vol >= VOL_RATIO_BREAK * ma_v and c[i] < prior_low:
            groups['放量破位'].add(c, i, n)


def main():
    print('=' * 86)
    print('量学死信号兑现率统计 v0.1 (无未来函数·对照组)')
    print('信号: 巨量阴线 / 长上影线 / 放量破位  |  口径: 收盘价, 同Phase 5')
    print('=' * 86)

    groups = {name: Group(name) for name in ('巨量阴线', '长上影线', '放量破位')}
    baseline = Group('全市场任意日')
    n_stocks = 0

    for code, path in iter_stocks():
        k = load_kline(path)
        if len(k) <= VOL_MA + 1:
            continue
        n_stocks += 1
        detect(k, groups, baseline)

    print(f"[扫描] 共 {n_stocks} 只股票")
    if n_stocks == 0:
        print('[失败] 没扫到任何K线, 请确认在仓库根目录运行')
        raise SystemExit(1)

    print()
    print('=' * 86)
    header = f"{'信号':<12}{'样本':>8}{'T+1':>8}{'T+3':>8}{'T+5':>8}{'T+10':>8}{'T+20':>8}{'T+20均收益':>12}"
    print(header)
    print('-' * 86)
    all_groups = [groups['巨量阴线'], groups['长上影线'], groups['放量破位'], baseline]
    for g in all_groups:
        cells = f"{g.name:<12}{g.n:>8}"
        for w in WINDOWS:
            r = g.rate(w)
            if g.cnt[w] >= MIN_SAMPLE and r is not None:
                cells += f"{r:>7.1f}%"
            else:
                cells += f"{'--':>8}"
        if len(g.ret20) >= MIN_SAMPLE:
            cells += f"{sum(g.ret20) / len(g.ret20):>+11.2f}%"
        else:
            cells += f"{'--':>12}"
        flag = '' if g.n >= MIN_SAMPLE else '  (样本不足)'
        print(cells + flag)
    print('=' * 86)

    # ---------- 判决 ----------
    base_t20 = baseline.rate(20)
    print()
    print('[判决] 与全市场任意日基线对比(T+20胜率):')
    for name in ('巨量阴线', '长上影线', '放量破位'):
        g = groups[name]
        r = g.rate(20)
        if r is None or g.cnt[20] < MIN_SAMPLE:
            print(f"  {name}: 样本不足, 不下结论")
            continue
        diff = r - base_t20
        if diff <= -5:
            verdict = '✅ 真死信号(显著弱于大盘), 可作反向过滤'
        elif diff >= 0:
            verdict = '❌ 无区分度(不弱于大盘!), 此信号不适配'
        else:
            verdict = '⚠️ 弱于大盘但不显著, 继续观察'
        print(f"  {name}: {r:.1f}% (基线{base_t20:.1f}%, 差{diff:+.1f}pct) → {verdict}")
    print()
    print('[口径] 胜=T+N收盘>事件日收盘 | 样本<30不下结论 | 数据覆盖全部历史K线(含熊市, 治样本期偏暖病)')

    # ---------- 落盘 ----------
    report = {
        'version': '0.1',
        'generated_at': datetime.now(BJ).strftime('%Y-%m-%d %H:%M'),
        'note': '死信号对照组, 无未来函数, 收盘价口径',
        'baseline_t20_winrate': round(base_t20, 2) if base_t20 else None,
        'groups': [g.to_dict() for g in all_groups],
    }
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"✅ 已生成: {OUT_PATH}")
    print("✅ 终态校验通过: 死信号对照组已落盘")


if __name__ == '__main__':
    main()
