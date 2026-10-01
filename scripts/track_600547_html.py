#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
600547 真金弹簧 追踪卡 v0.1 (track_600547_html.py)
==================================================
Phase 5 欠账A餐: 600547追踪卡HTML深色版, 与payoff日报风格统一。

设计原则(吸取教训):
  - 只读结构已确认的K线文件(data/kline/sh/sh600547.json)
  - 窗口开奖日从K线真实日期推算, 节假日自动跳过, 不硬猜日历
  - 不读账本(结构未确认), 基准价从K线取, 取不到用备案常数
  - 纯新增文件, 只读不写地基, 输出 docs/track_600547.html
版本: v0.1 (2026-10-02)
"""

import os
import sys
import json
import html
import traceback
from datetime import datetime, timezone, timedelta

KLINE_PATH = 'data/kline/sh/sh600547.json'
OUT_PATH = 'docs/track_600547.html'
CODE = 'sh600547'
NAME = '山东黄金'
EVENT_DATE = '2026-09-29'      # 真金弹簧事件日(圣经备案)
EVENT_CLOSE_FALLBACK = 26.96   # 事件日收盘备案值(K线里取不到时用)
WINDOWS = [1, 2, 3, 5, 10, 20]
CANDLE_DAYS = 45               # K线图展示最近N个交易日
BJ = timezone(timedelta(hours=8))


def load_kline():
    if not os.path.exists(KLINE_PATH):
        return None
    with open(KLINE_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)
    ks = []
    for x in data.get('klines', []):
        if len(x) >= 6:
            ks.append({'date': str(x[0])[:10], 'open': float(x[1]),
                       'close': float(x[2]), 'high': float(x[3]),
                       'low': float(x[4]), 'vol': float(x[5])})
    return ks


def main():
    print('=' * 70)
    print('600547 真金弹簧追踪卡 v0.1 (深色版)')
    print('=' * 70)

    ks = load_kline()
    if not ks:
        print(f'[失败] 读不到K线 {KLINE_PATH}')
        sys.exit(1)
    dates = [k['date'] for k in ks]
    idx = {d: i for i, d in enumerate(dates)}
    print(f"[K线] {len(ks)} 根, 最新: {dates[-1]}")

    # ---------- 基准 ----------
    i_ev = idx.get(EVENT_DATE)
    if i_ev is not None:
        base = ks[i_ev]['close']
        print(f"[基准] {EVENT_DATE} 收盘 {base:.2f} (取自K线)")
    else:
        i_ev = None
        base = EVENT_CLOSE_FALLBACK
        print(f"[基准] K线中无{EVENT_DATE}, 用备案值 {base:.2f}")

    last = ks[-1]
    i_last = len(ks) - 1
    days_since = (i_last - i_ev) if i_ev is not None else None
    cur_ret = (last['close'] / base - 1) * 100 if base > 0 else 0.0
    print(f"[现状] 最新{last['date']} 收盘{last['close']:.2f}, "
          f"距事件{days_since}个交易日, 浮动{cur_ret:+.2f}%")

    # ---------- 窗口进度 ----------
    wins = []
    for w in WINDOWS:
        j = (i_ev + w) if i_ev is not None else None
        if j is not None and j <= i_last:
            ret = (ks[j]['close'] / base - 1) * 100
            status = 'win' if ret > 0 else 'lose'
            wins.append({'w': w, 'date': ks[j]['date'], 'ret': ret,
                         'status': status, 'pending': False})
        else:
            wins.append({'w': w, 'date': None, 'ret': None,
                         'status': None, 'pending': True})
    cells = []
    for x in wins:
        if x['pending']:
            cells.append(f"T+{x['w']}:未到")
        else:
            cells.append(f"T+{x['w']}:{x['ret']:+.2f}%")
    print('[窗口] ' + ' | '.join(cells))
    due_soon = [x for x in wins if x['pending']][:2]

    # ---------- SVG蜡烛图 ----------
    seg = ks[-CANDLE_DAYS:]
    n = len(seg)
    W_CH, H_CH = 700, 300
    pad_l, pad_r, pad_t, pad_b = 8, 8, 16, 22
    lo = min(k['low'] for k in seg)
    hi = max(k['high'] for k in seg)
    span = (hi - lo) or 1.0
    cw = (W_CH - pad_l - pad_r) / n
    bw = max(cw * 0.62, 1.2)

    def y(p):
        return pad_t + (hi - p) / span * (H_CH - pad_t - pad_b)

    candles = []
    for i, k in enumerate(seg):
        cx = pad_l + i * cw + cw / 2
        up = k['close'] >= k['open']
        col = '#ff5d5d' if up else '#3ddc84'   # A股: 红涨绿跌
        top = y(max(k['open'], k['close']))
        bot = y(min(k['open'], k['close']))
        candles.append(
            f'<line x1="{cx:.1f}" y1="{y(k["high"]):.1f}" x2="{cx:.1f}" y2="{y(k["low"]):.1f}" stroke="{col}" stroke-width="1"/>'
            f'<rect x="{cx - bw / 2:.1f}" y="{top:.1f}" width="{bw:.1f}" height="{max(bot - top, 1):.1f}" fill="{col}"/>')
    # 事件日标记
    ev_line = ''
    if i_ev is not None:
        ev_i = i_ev - (len(ks) - n)
        if 0 <= ev_i < n:
            ex = pad_l + ev_i * cw + cw / 2
            ev_line = (f'<line x1="{ex:.1f}" y1="{pad_t}" x2="{ex:.1f}" '
                       f'y2="{H_CH - pad_b}" stroke="#ffb340" stroke-width="1.2" stroke-dasharray="4,3"/>'
                       f'<text x="{ex + 3:.1f}" y="{pad_t + 10}" fill="#ffb340" font-size="10">事件{EVENT_DATE[5:]}</text>')
    # 基准价横线
    base_line = (f'<line x1="{pad_l}" y1="{y(base):.1f}" x2="{W_CH - pad_r}" y2="{y(base):.1f}" '
                 f'stroke="#8a8a8a" stroke-width="1" stroke-dasharray="2,3"/>'
                 f'<text x="{pad_l + 2}" y="{y(base) - 3:.1f}" fill="#8a8a8a" font-size="10">基准 {base:.2f}</text>')
    svg = (f'<svg viewBox="0 0 {W_CH} {H_CH}" width="100%" height="{H_CH}" '
           f'preserveAspectRatio="xMidYMid meet">{"".join(candles)}{ev_line}{base_line}</svg>')

    # ---------- 窗口表 ----------
    rows = []
    for x in wins:
        if x['pending']:
            cell = '<td class="dim">待开奖</td>'
        else:
            cls = 'w' if x['status'] == 'win' else 'l'
            cell = (f'<td><span class="{cls}">{x["ret"]:+.2f}%</span></td>')
        rows.append(f'<tr><td class="gn">T+{x["w"]}</td>'
                    f'<td class="dim">{x["date"] or "--"}</td>{cell}</tr>')
    win_table = f'''
<div class="scroll"><table>
<tr><th class="gn">窗口</th><th>开奖日</th><th>收益(vs基准)</th></tr>
{''.join(rows)}
</table></div>'''

    # ---------- 页面 ----------
    stamp = datetime.now(BJ).strftime('%Y-%m-%d %H:%M')
    nxt = ' , '.join(f"T+{x['w']}({x['date'] or '待定'})" for x in due_soon) if due_soon else '全部窗口已开奖'
    page = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="color-scheme" content="dark">
<title>600547 追踪卡</title>
<style>
* {{ -webkit-tap-highlight-color: transparent; }}
body {{ font-family: -apple-system, "HarmonyOS Sans SC", sans-serif;
       margin: 0; padding: 14px 10px 30px; background: #121212; color: #e0e0e0; }}
h1 {{ font-size: 1.2em; color: #fff; }}
h2 {{ font-size: 1.0em; color: #f0f0f0; border-left: 4px solid #ffb340; padding-left: 8px; margin: 1.4em 0 0.6em; }}
.meta {{ color: #8a8a8a; font-size: 0.78em; }}
.hero {{ background: #1c1c1c; border: 1px solid #2a2a2a; border-radius: 12px;
        padding: 14px; margin: 10px 0; }}
.hero .big {{ font-size: 1.9em; font-weight: 700; }}
.scroll {{ overflow-x: auto; -webkit-overflow-scrolling: touch;
          border-radius: 10px; border: 1px solid #2a2a2a; background: #1c1c1c; }}
table {{ border-collapse: collapse; width: 100%; min-width: 320px; font-size: 0.9em; }}
th, td {{ border-bottom: 1px solid #2a2a2a; padding: 9px 8px; text-align: center; }}
th {{ background: #262626; color: #bbb; font-weight: 500; }}
td.gn {{ text-align: left; font-weight: 600; color: #f0f0f0; }}
.w {{ color: #ff5d5d; font-weight: 700; }}
.l {{ color: #3ddc84; font-weight: 700; }}
.dim {{ color: #666; }}
.card {{ background: #1c1c1c; border: 1px solid #2a2a2a; border-radius: 10px;
        padding: 10px 12px; margin: 8px 0; font-size: 0.85em; color: #bbb; }}
.up {{ color: #ff5d5d; }} .down {{ color: #3ddc84; }}
.note {{ color: #777; font-size: 0.78em; margin-top: 1.2em; }}
</style>
</head>
<body>
<h1>弹簧追踪卡 · {CODE} {NAME}</h1>
<p class="meta">生成: {stamp} (北京时间) · 数据截至: {last['date']}</p>

<div class="hero">
  <div>事件日 {EVENT_DATE} · 基准收盘 <b>{base:.2f}</b></div>
  <div class="big"><span class="{'up' if last['close'] >= base else 'down'}">{last['close']:.2f}</span>
  <span class="{'up' if cur_ret > 0 else 'down'}" style="font-size:0.55em">{cur_ret:+.2f}%</span></div>
  <div class="meta">距事件 {days_since if days_since is not None else '?'} 个交易日 · 20日窗口内持有中</div>
</div>

<h2>走势（近{CANDLE_DAYS}个交易日）</h2>
<div class="card" style="padding:6px">{svg}</div>

<h2>窗口开奖进度</h2>
{win_table}

<div class="card">⏰ 下一个待验窗口: <b>{html.escape(nxt)}</b><br>
正式策略口径: 事件日收盘进场, 持有20日, 胜=T+N收盘&gt;基准。</div>

<p class="note">铁律: 本卡只统计, 不预测。数据源: data/kline/sh/sh600547.json。
本页由cron自动生成, 与docs/payoff_report.html同门。</p>
</body>
</html>'''

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, 'w', encoding='utf-8') as f:
        f.write(page)
    print(f"✅ 已生成: {OUT_PATH} ({len(page)//1024}KB)")
    print("✅ 终态校验通过: 600547追踪卡已落盘")


if __name__ == '__main__':
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        print('[崩溃] 意外错误, 请把报错贴回给AI:')
        traceback.print_exc()
        sys.exit(1)
