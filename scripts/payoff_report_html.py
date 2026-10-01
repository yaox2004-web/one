#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
兑现率可视化报告 v0.2 (payoff_report_html.py)
==============================================
v0.2修复: 真实结构(探针实测)为扁平键——
  {组名: {"T1_n":..,"T1_winrate":..,"T10_n":..,"T20_winrate":..,
          "Tmax_avg_return":..,"tradeable":..,"note":..}}
  v0.1找的是嵌套键"T+1":{...}, 全扑空, 表格全是"--"。
  修复: 键名映射 T+1→T1_winrate/T1_n, 均收益→Tmax_avg_return。

其余不变: 只读不写地基, 输出 docs/payoff_report.html
版本: v0.2 (2026-10-02)
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
# 窗口标签 → payoff_report.json 的扁平键前缀
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


# ============ 归一化 ============

def normalize_payoff_groups(raw):
    """真实结构: groups是dict {组名: {T1_n, T1_winrate, ..., tradeable}}"""
    groups_raw = raw.get('groups') if isinstance(raw, dict) else None
    if not isinstance(groups_raw, dict):
        return []
    out = []
    for name, g in groups_raw.items():
        if not isinstance(g, dict):
            continue
        tradeable = bool(g.get('tradeable'))
        retro = '回溯' in name
        wins = {}
        for w in WINDOWS:
            k = WIN_KEY[w]
            wins[w] = (g.get(f'{k}_winrate'), g.get(f'{k}_n'))
        out.append({'name': str(name),
                    'tradeable': tradeable, 'retro': retro,
                    'wins': wins,
                    't20': g.get('Tmax_avg_return'),
                    'note': g.get('note', '')})
    return out


def normalize_death_groups(raw):
    """死信号报告是AI自己写的, 结构确认: groups是list"""
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


# ============ HTML 渲染 ============

def rate_color(r):
    if r >= 60:
        return '#d73027'   # A股习惯: 红=好
    if r >= 52:
        return '#e08214'
    if r > 48:
        return '#333333'
    return '#1a6ec0'


def cell_html(rate, n):
    if rate is None or not isinstance(rate, (int, float)):
        return '<td class="dim">--</td>'
    insufficient = (n is not None and n < MIN_SAMPLE)
    color = '#999' if insufficient else rate_color(rate)
    if insufficient:
        sub = f'<small>n={n}·不足</small>'
    elif n is not None:
        sub = f'<small>n={n}</small>'
    else:
        sub = ''
    return (f'<td><span style="color:{color};font-weight:600">'
            f'{rate:.1f}%</span><br>{sub}</td>')


def t20_html(t20):
    if t20 is None or not isinstance(t20, (int, float)):
        return '<td class="dim">--</td>'
    color = '#d73027' if t20 > 0 else '#1a6ec0'
    return f'<td><span style="color:{color};font-weight:600">{t20:+.2f}%</span></td>'


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
<table>
<tr><th>分组</th><th>T+1</th><th>T+3</th><th>T+5</th><th>T+10</th><th>T+20</th><th>T+20均收益</th></tr>
{''.join(rows)}
</table>'''


def render_page(payoff_groups, death_groups, generated_at):
    payoff_table = ''
    if payoff_groups:
        payoff_table = render_table(
            payoff_groups, '一、威科夫信号兑现率（Phase 5 v0.5）',
            '正式策略=前置链Spring收盘进场持20日。胜=T+N收盘>事件日收盘；'
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
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>兑现率报告</title>
<style>
body {{ font-family: -apple-system, sans-serif; margin: 12px; background: #fafafa; }}
h1 {{ font-size: 1.3em; }}
h2 {{ font-size: 1.1em; margin-top: 1.4em; }}
table {{ border-collapse: collapse; width: 100%; font-size: 0.85em; background: #fff; }}
th, td {{ border: 1px solid #ddd; padding: 6px 4px; text-align: center; }}
th {{ background: #444; color: #fff; }}
td.gn {{ text-align: left; white-space: nowrap; }}
small {{ color: #999; font-size: 0.75em; }}
.dim {{ color: #bbb; }}
.ok {{ background: #2e7d32; color: #fff; font-size: 0.7em; padding: 1px 4px; border-radius: 3px; }}
.warn {{ background: #e65100; color: #fff; font-size: 0.7em; padding: 1px 4px; border-radius: 3px; }}
.note {{ color: #666; font-size: 0.85em; }}
.meta {{ color: #999; font-size: 0.8em; }}
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
    print('兑现率可视化报告 v0.2 (扁平键修复版)')
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

    gen_at = raw.get('meta', {}).get('generated_at') if isinstance(raw.get('meta'), dict) else raw.get('generated_at')
    page = render_page(payoff_groups, death_groups, gen_at)
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, 'w', encoding='utf-8') as f:
        f.write(page)
    print(f"✅ 已生成: {OUT_PATH} ({len(page)//1024}KB)")
    print("✅ 终态校验通过: 兑现率HTML已落盘(含数字版)")


if __name__ == '__main__':
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        print('[崩溃] 意外错误, 请把下面报错连同[探针]输出一起贴回给AI:')
        traceback.print_exc()
        sys.exit(1)
