#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
兑现率可视化报告 v0.3 (payoff_report_html.py)
==============================================
v0.3升级(用户需求):
  - 深色背景主题(用户偏好)
  - 手机自适应(华为Mate30 Pro实测口径): 表格横向可滑+首列吸边+字号适配
v0.2修复: payoff扁平键 T1_winrate/T1_n/Tmax_avg_return
  (v0.1猜嵌套结构扑空, 第6起格式事故, 探针活捉)

结构依据(探针实测): groups={组名: {T1_n,T1_winrate,...,Tmax_avg_return,tradeable,note}}
版本: v0.3 (2026-10-02)
"""

import os
import sys
import json
import html
import traceback
from datetime import datetime, timezone, timedelta

PAYOFF_PATH = 'data/analysis/payoff_report.json'
DEATH_PATH = 'data/analysis/death_signal_report.json'
OUT_PATH = 'docs/payoff_report.html'
WINDOWS = ['T+1', 'T+3', 'T+5', 'T+10', 'T+20']
WIN_KEY = {'T+1': 'T1', 'T+3': 'T3', 'T+5': 'T5', 'T+10': 'T10', 'T+20': 'T20'}
MIN_SAMPLE = 30
BJ = timezone(timedelta(hours=8))


def load_json(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def probe(name, obj, max_chars=500):
    print(f"[探针] {name} 顶层类型: {type(obj).__name__}", end='')
    try:
        if isinstance(obj, dict):
            keys = list(obj.keys())
            print(f", 共 {len(keys)} 键: {keys[:10]}")
            if 'groups' in obj and isinstance(obj['groups'], dict):
                first_k = next(iter(obj['groups']))
                s = json.dumps({first_k: obj['groups'][first_k]},
                               ensure_ascii=False, default=str)
                print(f"[探针] 首组预览: {s[:max_chars]}")
        elif isinstance(obj, list):
            print(f", 共 {len(obj)} 项")
    except Exception as e:
        print(f" (预览失败: {e})")


def find_date_like(raw):
    """在meta里自动找长得像日期的值, 兜底'None'问题"""
    meta = raw.get('meta') if isinstance(raw, dict) else None
    if isinstance(meta, dict):
        for k, v in meta.items():
            s = str(v)
            if len(s) >= 8 and (s[:2] == '20' or '-' in s[:6]):
                return f"{s} ({k})"
    if isinstance(raw, dict) and isinstance(raw.get('generated_at'), str):
        return raw['generated_at']
    return '当日'


def normalize_payoff_groups(raw):
    groups_raw = raw.get('groups') if isinstance(raw, dict) else None
    if not isinstance(groups_raw, dict):
        return []
    out = []
    for name, g in groups_raw.items():
        if not isinstance(g, dict):
            continue
        wins = {}
        for w in WINDOWS:
            k = WIN_KEY[w]
            wins[w] = (g.get(f'{k}_winrate'), g.get(f'{k}_n'))
        out.append({'name': str(name),
                    'tradeable': bool(g.get('tradeable')),
                    'retro': '回溯' in str(name),
                    'wins': wins,
                    't20': g.get('Tmax_avg_return'),
                    'note': g.get('note', '')})
    return out


def normalize_death_groups(raw):
    out = []
    for g in raw.get('groups', []):
        wins = {}
        src = g.get('windows', {})
        for w in WINDOWS:
            cell = src.get(w) or {}
            wins[w] = (cell.get('rate'), cell.get('n'))
        out.append({'name': g.get('name', '?'), 'tradeable': False,
                    'retro': False, 'wins': wins,
                    't20': g.get('t20_mean_ret'), 'note': ''})
    return out


# ============ 深色主题渲染 ============

def rate_color(r):
    """深色背景下提亮: 红=高胜率(A股习惯), 蓝=低"""
    if r >= 60:
        return '#ff5d5d'   # 亮红
    if r >= 52:
        return '#ffb340'   # 亮橙
    if r > 48:
        return '#d4d4d4'   # 中性灰白
    return '#5da9ff'       # 亮蓝


def cell_html(rate, n):
    if rate is None or not isinstance(rate, (int, float)):
        return '<td class="dim">--</td>'
    insufficient = (n is not None and n < MIN_SAMPLE)
    color = '#8a8a8a' if insufficient else rate_color(rate)
    if insufficient:
        sub = f'<small>n={n}·不足</small>'
    elif n is not None:
        sub = f'<small>n={n}</small>'
    else:
        sub = ''
    return (f'<td><span style="color:{color};font-weight:700">'
            f'{rate:.1f}%</span><br>{sub}</td>')


def t20_html(t20):
    if t20 is None or not isinstance(t20, (int, float)):
        return '<td class="dim">--</td>'
    color = '#ff5d5d' if t20 > 0 else '#5da9ff'
    return f'<td><span style="color:{color};font-weight:700">{t20:+.2f}%</span></td>'


def render_table(groups, title, note=''):
    rows = []
    for g in groups:
        badge = ''
        if g['retro']:
            badge = ' <span class="warn">⚠️仅归因</span>'
        elif g['tradeable']:
            badge = ' <span class="ok">✅可交易</span>'
        extra = f' <small>({html.escape(str(g["note"]))})</small>' if g.get('note') else ''
        cells = ''.join(cell_html(*g['wins'][w]) for w in WINDOWS)
        rows.append(f'<tr><td class="gn">{html.escape(g["name"])}{badge}{extra}</td>'
                    f'{cells}{t20_html(g["t20"])}</tr>')
    note_html = f'<p class="note">{note}</p>' if note else ''
    return f'''
<h2>{title}</h2>
{note_html}
<div class="scroll">
<table>
<tr><th class="gn">分组</th><th>T+1</th><th>T+3</th><th>T+5</th><th>T+10</th><th>T+20</th><th>均收益</th></tr>
{''.join(rows)}
</table>
</div>'''


def render_page(payoff_groups, death_groups, generated_at):
    payoff_table = ''
    if payoff_groups:
        payoff_table = render_table(
            payoff_groups, '一、威科夫信号兑现率（Phase 5 v0.5）',
            '正式策略=前置链Spring收盘进场持20日。胜=T+N收盘&gt;事件日收盘；'
            'n&lt;30标"不足"不下结论；回溯组含未来信息仅归因，禁止作交易信号。')
    death_table = ''
    if death_groups:
        death_table = render_table(
            death_groups, '二、死信号对照组（v0.1）',
            '基线=全市场任意日(全历史536万股票日, T+20=47.3%/+0.70%)。'
            '放量破位为反指: 恐慌破位有承接，恰是Spring逻辑的独立证据。')
    stamp = datetime.now(BJ).strftime('%Y-%m-%d %H:%M')
    return f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="color-scheme" content="dark">
<title>兑现率报告</title>
<style>
* {{ -webkit-tap-highlight-color: transparent; }}
body {{
  font-family: -apple-system, "HarmonyOS Sans SC", "HuaweiFont", sans-serif;
  margin: 0; padding: 14px 10px 30px;
  background: #121212; color: #e0e0e0;
}}
h1 {{ font-size: 1.25em; color: #fff; }}
h2 {{ font-size: 1.05em; margin: 1.5em 0 0.6em; color: #f0f0f0;
     border-left: 4px solid #ff5d5d; padding-left: 8px; }}
.meta {{ color: #8a8a8a; font-size: 0.78em; }}
.note {{ color: #9e9e9e; font-size: 0.8em; line-height: 1.5; margin: 0.5em 0 0.6em; }}
.scroll {{
  overflow-x: auto; -webkit-overflow-scrolling: touch;
  border-radius: 10px; border: 1px solid #2a2a2a; background: #1c1c1c;
}}
table {{ border-collapse: collapse; width: 100%; min-width: 560px; font-size: 0.85em; }}
th, td {{ border-bottom: 1px solid #2a2a2a; padding: 9px 6px; text-align: center; white-space: nowrap; }}
th {{ background: #262626; color: #bbb; font-weight: 500; position: sticky; top: 0; }}
tr:last-child td {{ border-bottom: none; }}
td.gn, th.gn {{
  text-align: left; position: sticky; left: 0; z-index: 2;
  background: #1c1c1c; max-width: 46vw;
}}
th.gn {{ background: #262626; z-index: 3; }}
td.gn {{ white-space: normal; word-break: break-all; font-weight: 600; color: #f0f0f0; }}
small {{ color: #777; font-size: 0.72em; }}
.dim {{ color: #555; }}
.ok {{ background: #1b4d2a; color: #6ee08a; font-size: 0.7em;
      padding: 2px 5px; border-radius: 4px; font-weight: 500; }}
.warn {{ background: #4d2a00; color: #ffab40; font-size: 0.7em;
        padding: 2px 5px; border-radius: 4px; font-weight: 500; }}
tr:hover td {{ background: #222; }}
</style>
</head>
<body>
<h1>📊 兑现率日报</h1>
<p class="meta">生成: {stamp} (北京时间) · 数据时点: {html.escape(str(generated_at))}</p>
{payoff_table}
{death_table}
<p class="note">铁律: 信号分组只用事件日收盘前已知信息(无未来函数)。本页由cron每日13:30 UTC自动生成。</p>
</body>
</html>'''


def main():
    print('=' * 70)
    print('兑现率可视化报告 v0.3 (深色主题+手机自适应)')
    print('=' * 70)

    if not os.path.exists(PAYOFF_PATH):
        print(f"[失败] 找不到 {PAYOFF_PATH}, 先等主流程跑出报告")
        sys.exit(1)
    raw = load_json(PAYOFF_PATH)
    probe('payoff_report.json', raw)
    payoff_groups = normalize_payoff_groups(raw)
    print(f"[归一] payoff分组: {len(payoff_groups)} 个")
    if not payoff_groups:
        print("[失败] payoff结构识别失败! 把上面[探针]两行贴回给AI")
        sys.exit(1)
    for g in payoff_groups:
        r20, n20 = g['wins']['T+20']
        r20s = f"{r20:.1f}%" if isinstance(r20, (int, float)) else '--'
        print(f"  - {g['name']}: T+20={r20s} (n={n20})"
              f"{' [回溯]' if g['retro'] else ''}")

    death_groups = []
    if os.path.exists(DEATH_PATH):
        try:
            draw = load_json(DEATH_PATH)
            death_groups = normalize_death_groups(draw)
            print(f"[归一] 死信号分组: {len(death_groups)} 个")
        except Exception as e:
            print(f"[警告] 死信号报告读取失败(不影响主表): {e}")

    gen_at = find_date_like(raw)
    print(f"[日期] 数据时点: {gen_at}")
    page = render_page(payoff_groups, death_groups, gen_at)
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, 'w', encoding='utf-8') as f:
        f.write(page)
    print(f"✅ 已生成: {OUT_PATH} ({len(page)//1024}KB)")
    print("✅ 终态校验通过: 兑现率HTML已落盘(深色版)")


if __name__ == '__main__':
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        print('[崩溃] 意外错误, 请把下面报错连同[探针]输出一起贴回给AI:')
        traceback.print_exc()
        sys.exit(1)
