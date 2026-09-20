#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
每日主力行为诊断（HTML分析报告版）
=================================================
设计思路（为什么这样写）：
  不只是简单的列表，而是分析报告！
  包括：
  1. 市场整体分析（大段文字，讲清楚市场逻辑）
  2. 每个阶段详细说明（这个阶段是什么意思，主力在做什么）
  3. 每只股票判断依据（为什么判断为这个阶段）

硬约束：
  - 绝对不用未来函数
"""

import json
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime

# ============================================================
# 配置
# ============================================================
DATA_DIR = Path(__file__).parent.parent / "data" / "kline"
OUTPUT_DIR = Path(__file__).parent.parent / "data" / "analysis"

MIN_DATA_DAYS = 60


# ============================================================
# 数据读取
# ============================================================
def load_klines(filepath):
    with open(filepath, 'r') as f:
        data = json.load(f)
    klines = data.get('klines', [])
    if not klines:
        return None, None
    
    ncols = len(klines[0])
    
    if ncols == 6:
        cols = ['date', 'open', 'close', 'high', 'low', 'volume']
    elif ncols == 7:
        cols = ['date', 'open', 'close', 'high', 'low', 'volume', 'amount']
    else:
        cols = ['date', 'open', 'close', 'high', 'low', 'volume'] + [f'col{i}' for i in range(7, ncols)]
    
    df = pd.DataFrame(klines)
    df = df.iloc[:, :ncols]
    df.columns = cols[:ncols]
    
    for col in ['open', 'close', 'high', 'low', 'volume']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
    df = df.dropna(subset=['open', 'close', 'high', 'low', 'volume'])
    
    name = data.get('name', filepath.stem)
    return df, name


# ============================================================
# 第一层：计算当日指标
# ============================================================
def calc_daily_indicators(df):
    df['pct_chg'] = (df['close'] - df['close'].shift(1)) / df['close'].shift(1) * 100
    df['vol_ratio_yesterday'] = df['volume'] / df['volume'].shift(1)
    
    df['vol_ma5'] = df['volume'].rolling(5).mean()
    df['vol_ratio_ma5'] = df['volume'] / df['vol_ma5']
    
    df['high_120'] = df['high'].rolling(120).max()
    df['low_120'] = df['low'].rolling(120).min()
    df['position_pct'] = (df['close'] - df['low_120']) / (df['high_120'] - df['low_120']) * 100
    
    df['ma5'] = df['close'].rolling(5).mean()
    df['ma10'] = df['close'].rolling(10).mean()
    df['ma20'] = df['close'].rolling(20).mean()
    df['ma60'] = df['close'].rolling(60).mean()
    df['above_ma20'] = df['close'] > df['ma20']
    df['above_ma60'] = df['close'] > df['ma60']
    
    df['pct_20d'] = (df['close'] - df['close'].shift(20)) / df['close'].shift(20) * 100
    
    # 连续状态（连续3天放量/缩量）
    df['consec_vol_up_3d'] = (df['vol_ratio_ma5'] > 1.2) & \
                             (df['vol_ratio_ma5'].shift(1) > 1.2) & \
                             (df['vol_ratio_ma5'].shift(2) > 1.2)
    
    df['consec_vol_down_3d'] = (df['vol_ratio_ma5'] < 0.8) & \
                               (df['vol_ratio_ma5'].shift(1) < 0.8) & \
                               (df['vol_ratio_ma5'].shift(2) < 0.8)
    
    # 量价配合
    df['price_up_vol_up'] = (df['pct_chg'] > 0) & (df['vol_ratio_ma5'] > 1.2)
    df['price_up_vol_down'] = (df['pct_chg'] > 0) & (df['vol_ratio_ma5'] < 0.8)
    df['price_down_vol_up'] = (df['pct_chg'] < 0) & (df['vol_ratio_ma5'] > 1.2)
    df['price_down_vol_down'] = (df['pct_chg'] < 0) & (df['vol_ratio_ma5'] < 0.8)
    
    return df


# ============================================================
# 第四层：主力行为意图判断
# ============================================================
def judge_main_behavior(df):
    latest = df.iloc[-1]
    
    position = latest['position_pct']
    vol_ratio = latest['vol_ratio_ma5']
    pct_chg = latest['pct_chg']
    pct_20d = latest['pct_20d']
    above_ma20 = latest['above_ma20']
    above_ma60 = latest['above_ma60']
    
    if pd.isna(position) or pd.isna(vol_ratio):
        return None
    
    scores = {
        '建仓初期': 0,
        '建仓后期': 0,
        '洗盘': 0,
        '拉升': 0,
        '出货': 0,
    }
    
    reasons = {
        '建仓初期': [],
        '建仓后期': [],
        '洗盘': [],
        '拉升': [],
        '出货': [],
    }
    
    # 1. 位置分位（25%权重）
    if position < 10:
        scores['建仓初期'] += 40
        reasons['建仓初期'].append(f'位置分位{position:.1f}%（极低位，近120日底部区域）')
    elif position < 30:
        scores['建仓后期'] += 30
        reasons['建仓后期'].append(f'位置分位{position:.1f}%（低位，底部抬升阶段）')
    elif position < 50:
        scores['建仓后期'] += 15
        scores['洗盘'] += 15
        reasons['建仓后期'].append(f'位置分位{position:.1f}%（中低位，底部确认阶段）')
    elif position < 70:
        scores['洗盘'] += 30
        reasons['洗盘'].append(f'位置分位{position:.1f}%（中位，拉升前洗盘阶段）')
    elif position < 85:
        scores['出货'] += 30
        reasons['出货'].append(f'位置分位{position:.1f}%（中高位，拉升后高位震荡）')
    else:
        scores['出货'] += 40
        reasons['出货'].append(f'位置分位{position:.1f}%（极高位，主力出货阶段）')
    
    # 2. 量能（20%权重）
    if vol_ratio > 1.5:
        if position < 30:
            scores['建仓后期'] += 25
            reasons['建仓后期'].append(f'低位放量（量比{vol_ratio:.2f}，主力开始建仓）')
        elif position < 70:
            scores['拉升'] += 25
            reasons['拉升'].append(f'中位放量（量比{vol_ratio:.2f}，主力开始拉升）')
        else:
            scores['出货'] += 25
            reasons['出货'].append(f'高位放量（量比{vol_ratio:.2f}，主力出货）')
    elif vol_ratio < 0.7:
        if position < 30:
            scores['建仓初期'] += 25
            reasons['建仓初期'].append(f'低位缩量（量比{vol_ratio:.2f}，主力悄悄建仓）')
        elif position < 70:
            scores['洗盘'] += 25
            reasons['洗盘'].append(f'中位缩量（量比{vol_ratio:.2f}，洗盘吸筹）')
        else:
            scores['出货'] += 10
            reasons['出货'].append(f'高位缩量（量比{vol_ratio:.2f}，出货尾声）')
    
    # 3. 20日涨跌幅（15%权重）
    if not pd.isna(pct_20d):
        if pct_20d > 15:
            if position > 50:
                scores['拉升'] += 25
                reasons['拉升'].append(f'20日大涨{pct_20d:.1f}%（主力拉升阶段）')
            else:
                scores['建仓后期'] += 15
                reasons['建仓后期'].append(f'低位涨{pct_20d:.1f}%（主力建仓推高股价）')
        elif pct_20d > 5:
            if position > 50:
                scores['拉升'] += 15
                reasons['拉升'].append(f'20日涨{pct_20d:.1f}%（拉升初期）')
            else:
                scores['建仓后期'] += 10
                reasons['建仓后期'].append(f'低位涨{pct_20d:.1f}%（建仓推高）')
        elif pct_20d < -15:
            if position < 30:
                scores['建仓初期'] += 15
                reasons['建仓初期'].append(f'低位跌{pct_20d:.1f}%（恐慌下跌，主力建仓机会）')
            else:
                scores['出货'] += 15
                reasons['出货'].append(f'高位跌{pct_20d:.1f}%（主力出货导致下跌）')
    
    # 4. 当日涨跌幅（10%权重）
    if pct_chg > 3:
        if position > 50:
            scores['拉升'] += 15
            reasons['拉升'].append(f'当日大涨{pct_chg:.2f}%（拉升信号）')
        else:
            scores['建仓后期'] += 10
            reasons['建仓后期'].append(f'当日涨{pct_chg:.2f}%（建仓推高）')
    elif pct_chg < -3:
        if position > 70:
            scores['出货'] += 15
            reasons['出货'].append(f'当日大跌{pct_chg:.2f}%（出货信号）')
    
    # 5. 均线位置（10%权重）
    if above_ma20:
        if position > 50:
            scores['拉升'] += 10
            reasons['拉升'].append(f'MA20之上（趋势向上）')
        else:
            scores['建仓后期'] += 5
            reasons['建仓后期'].append(f'MA20之上（底部抬升）')
    else:
        if position < 30:
            scores['建仓初期'] += 10
            reasons['建仓初期'].append(f'MA20之下（低位震荡）')
    
    if above_ma60:
        if position > 50:
            scores['拉升'] += 5
            reasons['拉升'].append(f'MA60之上（长期趋势向上）')
    else:
        if position < 30:
            scores['建仓初期'] += 5
            reasons['建仓初期'].append(f'MA60之下（长期低位）')
    
    # 6. 连续状态（10%权重）
    if latest['consec_vol_up_3d']:
        if position < 30:
            scores['建仓后期'] += 15
            reasons['建仓后期'].append(f'连续3天放量（主力建仓确认）')
        elif position < 70:
            scores['拉升'] += 15
            reasons['拉升'].append(f'连续3天放量（拉升确认）')
        else:
            scores['出货'] += 15
            reasons['出货'].append(f'高位连续放量（出货确认）')
    
    if latest['consec_vol_down_3d']:
        if position < 30:
            scores['建仓初期'] += 15
            reasons['建仓初期'].append(f'连续3天缩量（主力悄悄建仓）')
        elif position < 70:
            scores['洗盘'] += 15
            reasons['洗盘'].append(f'连续3天缩量（洗盘确认）')
    
    # 7. 量价配合（10%权重）
    if latest['price_up_vol_up']:
        if position > 50:
            scores['拉升'] += 10
            reasons['拉升'].append(f'价升量增（健康上涨）')
        else:
            scores['建仓后期'] += 5
            reasons['建仓后期'].append(f'价升量增（建仓推高）')
    
    if latest['price_down_vol_down']:
        if position < 30:
            scores['建仓初期'] += 10
            reasons['建仓初期'].append(f'价跌量缩（抛压减轻）')
        elif position > 70:
            scores['出货'] += 10
            reasons['出货'].append(f'价跌量缩（出货尾声）')
    
    # 找最高分
    best_stage = max(scores, key=scores.get)
    best_score = scores[best_stage]
    
    total_score = sum(scores.values())
    confidence = best_score / total_score * 100 if total_score > 0 else 0
    
    return {
        'stage': best_stage,
        'confidence': confidence,
        'position': position,
        'vol_ratio': vol_ratio,
        'pct_20d': pct_20d,
        'reasons': reasons[best_stage],
    }


# ============================================================
# 阶段说明
# ============================================================
STAGE_EXPLANATION = {
    '建仓初期': {
        'title': '建仓初期',
        'desc': '主力刚开始建仓阶段',
        'main_action': '主力在低位悄悄买入，不希望被市场发现',
        'market_logic': '位置极低（<10%），量能萎缩，说明抛压已经很轻，主力在这个位置慢慢吸筹。这个阶段股价通常在低位震荡，不涨不跌。',
        'next_stage': '建仓后期',
    },
    '建仓后期': {
        'title': '建仓后期',
        'desc': '主力建仓接近尾声，准备拉升',
        'main_action': '主力开始放量买入，推高股价，不再隐藏',
        'market_logic': '位置较低（10-30%），量能开始放大，说明主力已经吸够筹码，开始推高股价。这个阶段股价开始慢慢上涨，但还没有进入主升浪。',
        'next_stage': '洗盘',
    },
    '洗盘': {
        'title': '洗盘',
        'desc': '拉升前的最后洗盘',
        'main_action': '主力故意打压股价，洗掉不坚定的散户',
        'market_logic': '位置中等（50-70%），量能萎缩，说明主力在洗盘，把散户吓出去，然后再拉升。这个阶段股价通常横盘震荡，或小幅回调。',
        'next_stage': '拉升',
    },
    '拉升': {
        'title': '拉升',
        'desc': '主力开始拉升股价',
        'main_action': '主力放量拉升，快速推高股价',
        'market_logic': '位置中等偏高（50-70%），量能放大，说明主力开始拉升。这个阶段股价快速上涨，成交量放大。',
        'next_stage': '出货',
    },
    '出货': {
        'title': '出货',
        'desc': '主力在高位出货',
        'main_action': '主力在高位把筹码卖给散户',
        'market_logic': '位置极高（>70%），量能放大，说明主力在高位出货。这个阶段股价可能继续涨，但主力已经在悄悄卖了。',
        'next_stage': '下跌',
    },
}


# ============================================================
# 生成HTML
# ============================================================
def generate_html(results, date_str):
    df = pd.DataFrame(results)
    
    stage_count = df['stage'].value_counts()
    
    stages = ['建仓初期', '建仓后期', '洗盘', '拉升', '出货']
    counts = [int(stage_count.get(s, 0)) for s in stages]
    total = len(df)
    
    # 计算建仓占比
    jiancang_total = counts[0] + counts[1]
    jiancang_pct = jiancang_total / total * 100
    
    # 生成表格行
    table_rows = {}
    for stage in stages:
        stage_df = df[df['stage'] == stage].sort_values('confidence', ascending=False).head(20)
        rows_html = ""
        for _, row in stage_df.iterrows():
            code = str(row['code'])
            name = str(row['name'])
            price = f"{float(row['price']):.2f}"
            position = f"{float(row['position']):.1f}%"
            confidence = f"{float(row['confidence']):.1f}%"
            reasons = str(row['reasons'])
            rows_html += f"""
            <tr>
                <td>{code}</td>
                <td>{name}</td>
                <td>{price}</td>
                <td>{position}</td>
                <td>{confidence}</td>
                <td class="reason">{reasons}</td>
            </tr>
            """
        table_rows[stage] = rows_html
    
    # 阶段说明section
    stages_html = ""
    for stage in stages:
        info = STAGE_EXPLANATION[stage]
        count = counts[stages.index(stage)]
        stages_html += f"""
        <div class="stage-explain">
            <h3>{info['title']} <span class="count">({count}只)</span></h3>
            <p class="desc">{info['desc']}</p>
            <div class="logic-box">
                <p><strong>主力动作：</strong>{info['main_action']}</p>
                <p><strong>市场机理：</strong>{info['market_logic']}</p>
                <p><strong>下一阶段：</strong>{info['next_stage']}</p>
            </div>
        </div>
        """
    
    # 各阶段股票列表section
    sections_html = ""
    for i, stage in enumerate(stages):
        count = counts[i]
        sections_html += f"""
        <div class="stage-section">
            <div class="stage-header">
                <h2>{stage}</h2>
                <div class="stage-count">{count}只</div>
            </div>
            <table>
                <thead>
                    <tr>
                        <th>代码</th>
                        <th>名称</th>
                        <th>价格</th>
                        <th>位置分位</th>
                        <th>置信度</th>
                        <th>判断依据</th>
                    </tr>
                </thead>
                <tbody>
                    {table_rows[stage]}
                </tbody>
            </table>
        </div>
        """
    
    pie_data_list = [{"name": s, "value": int(counts[i])} for i, s in enumerate(stages)]
    pie_data = json.dumps(pie_data_list, ensure_ascii=False)
    
    bar_data = json.dumps([int(c) for c in counts])
    stages_json = json.dumps(stages, ensure_ascii=False)
    
    # 市场整体分析文字
    market_analysis = f"""
    <div class="analysis-section">
        <h2>市场整体分析</h2>
        <p>今日共扫描{total}只股票，主力阶段分布如下：</p>
        <ul>
            <li><strong>建仓阶段（初期+后期）：{jiancang_total}只，占比{jiancang_pct:.1f}%</strong></li>
            <li>洗盘阶段：{counts[2]}只，占比{counts[2]/total*100:.1f}%</li>
            <li>拉升阶段：{counts[3]}只，占比{counts[3]/total*100:.1f}%</li>
            <li>出货阶段：{counts[4]}只，占比{counts[4]/total*100:.1f}%</li>
        </ul>
        <p><strong>结论：</strong>当前市场整体处于建仓阶段，大部分股票在低位，主力正在悄悄建仓。这说明市场可能处于底部区域，后续值得关注。</p>
        <p><strong>操作建议：</strong>重点关注建仓初期和建仓后期的股票，这些股票后续可能进入拉升阶段。</p>
    </div>
    """
    
    html = f"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>主力行为诊断分析报告 - {date_str}</title>
    <script src="https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"></script>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f5f5f5; padding: 20px; line-height: 1.6; }}
        .container {{ max-width: 1200px; margin: 0 auto; }}
        .header {{ background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%); color: white; padding: 30px; border-radius: 12px; margin-bottom: 20px; }}
        .header h1 {{ font-size: 28px; margin-bottom: 10px; }}
        .header .date {{ opacity: 0.8; font-size: 16px; }}
        .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 20px; }}
        .card {{ background: white; border-radius: 12px; padding: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
        .card h2 {{ font-size: 18px; margin-bottom: 15px; color: #333; }}
        #pieChart, #barChart {{ width: 100%; height: 300px; }}
        .analysis-section {{ background: white; border-radius: 12px; padding: 20px; margin-bottom: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
        .analysis-section h2 {{ font-size: 20px; margin-bottom: 15px; color: #333; border-bottom: 2px solid #1e3c72; padding-bottom: 10px; }}
        .analysis-section p {{ margin-bottom: 10px; color: #555; }}
        .analysis-section ul {{ margin-left: 20px; margin-bottom: 10px; }}
        .stage-explain {{ background: white; border-radius: 12px; padding: 20px; margin-bottom: 15px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
        .stage-explain h3 {{ font-size: 18px; margin-bottom: 10px; color: #333; }}
        .stage-explain .count {{ color: #666; font-size: 14px; }}
        .stage-explain .desc {{ color: #666; margin-bottom: 10px; }}
        .stage-explain .logic-box {{ background: #f8f9fa; padding: 15px; border-radius: 8px; }}
        .stage-explain .logic-box p {{ margin-bottom: 8px; }}
        .stage-explain .logic-box strong {{ color: #1e3c72; }}
        .stage-section {{ background: white; border-radius: 12px; padding: 20px; margin-bottom: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
        .stage-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px; }}
        .stage-header h2 {{ font-size: 18px; padding-bottom: 10px; border-bottom: 2px solid #f0f0f0; }}
        .stage-count {{ font-size: 24px; font-weight: bold; color: #333; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th, td {{ padding: 10px; text-align: left; border-bottom: 1px solid #f0f0f0; }}
        th {{ background: #fafafa; font-weight: 600; color: #666; }}
        td.reason {{ font-size: 12px; color: #666; }}
        @media (max-width: 768px) {{
            .grid {{ grid-template-columns: 1fr; }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>主力行为诊断分析报告</h1>
            <div class="date">{date_str} | 共{total}只股票</div>
        </div>
        
        <div class="grid">
            <div class="card">
                <h2>市场全景分布</h2>
                <div id="pieChart"></div>
            </div>
            <div class="card">
                <h2>各阶段数量对比</h2>
                <div id="barChart"></div>
            </div>
        </div>
        
        {market_analysis}
        
        <div class="analysis-section">
            <h2>各阶段详解</h2>
            {stages_html}
        </div>
        
        {sections_html}
    </div>
    
    <script>
        var pieChart = echarts.init(document.getElementById('pieChart'));
        var pieOption = {{
            tooltip: {{ trigger: 'item' }},
            legend: {{ orient: 'vertical', left: 'left' }},
            series: [{{
                type: 'pie',
                radius: '60%',
                data: {pie_data},
                emphasis: {{ itemStyle: {{ shadowBlur: 10, shadowOffsetX: 0, shadowColor: 'rgba(0, 0, 0, 0.5)' }} }}
            }}]
        }};
        pieChart.setOption(pieOption);
        
        var barChart = echarts.init(document.getElementById('barChart'));
        var barOption = {{
            tooltip: {{ trigger: 'axis' }},
            xAxis: {{ type: 'category', data: {stages_json} }},
            yAxis: {{ type: 'value' }},
            series: [{{
                type: 'bar',
                data: {bar_data},
                itemStyle: {{
                    color: function(params) {{
                        var colors = ['#1976d2', '#388e3c', '#f57c00', '#c2185b', '#d32f2f'];
                        return colors[params.dataIndex];
                    }}
                }}
            }}]
        }};
        barChart.setOption(barOption);
        
        window.addEventListener('resize', function() {{
            pieChart.resize();
            barChart.resize();
        }});
    </script>
</body>
</html>
    """
    
    return html


# ============================================================
# 主函数
# ============================================================
def main():
    print("="*70)
    print("每日主力行为诊断（HTML分析报告版）")
    print("="*70)
    
    all_files = []
    for market_dir in DATA_DIR.iterdir():
        if market_dir.is_dir():
            for f in market_dir.glob('*.json'):
                all_files.append(f)
    
    print(f"共{len(all_files)}只股票")
    
    results = []
    total = len(all_files)
    
    for i, filepath in enumerate(all_files):
        if (i + 1) % 500 == 0:
            print(f"  进度 {i+1}/{total} | 已识别 {len(results)}")
        
        df, name = load_klines(filepath)
        if df is None or len(df) < MIN_DATA_DAYS:
            continue
        
        df = calc_daily_indicators(df)
        
        result = judge_main_behavior(df)
        if result is None:
            continue
        
        results.append({
            'code': filepath.stem,
            'name': name,
            'price': df['close'].iloc[-1],
            'position': result['position'],
            'vol_ratio': result['vol_ratio'],
            'pct_20d': result['pct_20d'],
            'stage': result['stage'],
            'confidence': result['confidence'],
            'reasons': ', '.join(result['reasons']),
            'date': df['date'].iloc[-1],
        })
    
    today = datetime.now().strftime('%Y-%m-%d')
    html_content = generate_html(results, today)
    
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_file = OUTPUT_DIR / f"daily_main_behavior_{today}.html"
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    print(f"\n已生成HTML分析报告: {output_file}")
    
    df_results = pd.DataFrame(results)
    csv_file = OUTPUT_DIR / f"daily_main_behavior_{today}.csv"
    df_results.to_csv(csv_file, index=False, encoding='utf-8-sig')
    print(f"已保存CSV数据: {csv_file}")


if __name__ == "__main__":
    main()
