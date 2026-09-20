#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
每日主力行为诊断（HTML版）
=================================================
设计思路（为什么这样写）：
  把每日诊断结果做成HTML页面，美观直观。
  包括：
  1. 市场全景饼图
  2. 各阶段数量柱状图
  3. 各阶段股票列表

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
    
    df['ma20'] = df['close'].rolling(20).mean()
    df['above_ma20'] = df['close'] > df['ma20']
    
    df['pct_20d'] = (df['close'] - df['close'].shift(20)) / df['close'].shift(20) * 100
    
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
    
    if pd.isna(position) or pd.isna(vol_ratio):
        return None
    
    scores = {
        '建仓初期': 0,
        '建仓后期': 0,
        '洗盘': 0,
        '拉升': 0,
        '出货': 0,
    }
    
    if position < 10:
        scores['建仓初期'] += 40
    elif position < 30:
        scores['建仓后期'] += 30
    elif position < 50:
        scores['建仓后期'] += 15
        scores['洗盘'] += 15
    elif position < 70:
        scores['洗盘'] += 30
    elif position < 85:
        scores['出货'] += 30
    else:
        scores['出货'] += 40
    
    if vol_ratio > 1.5:
        if position < 30:
            scores['建仓后期'] += 25
        elif position < 70:
            scores['拉升'] += 25
        else:
            scores['出货'] += 25
    elif vol_ratio < 0.7:
        if position < 30:
            scores['建仓初期'] += 25
        elif position < 70:
            scores['洗盘'] += 25
        else:
            scores['出货'] += 10
    
    if not pd.isna(pct_20d):
        if pct_20d > 10:
            if position > 50:
                scores['拉升'] += 25
            else:
                scores['建仓后期'] += 15
        elif pct_20d < -10:
            if position < 30:
                scores['建仓初期'] += 15
            else:
                scores['出货'] += 15
    
    if pct_chg > 3:
        if position > 50:
            scores['拉升'] += 15
        else:
            scores['建仓后期'] += 10
    elif pct_chg < -3:
        if position > 70:
            scores['出货'] += 15
    
    if above_ma20:
        if position > 50:
            scores['拉升'] += 10
        else:
            scores['建仓后期'] += 5
    else:
        if position < 30:
            scores['建仓初期'] += 10
    
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
    }


# ============================================================
# 生成HTML
# ============================================================
def generate_html(results, date_str):
    df = pd.DataFrame(results)
    
    stage_count = df['stage'].value_counts()
    
    stages = ['建仓初期', '建仓后期', '洗盘', '拉升', '出货']
    counts = [stage_count.get(s, 0) for s in stages]
    total = len(df)
    pcts = [c / total * 100 for c in counts]
    
    # 生成表格行
    table_rows = {}
    for stage in stages:
        stage_df = df[df['stage'] == stage].sort_values('confidence', ascending=False).head(20)
        rows_html = ""
        for _, row in stage_df.iterrows():
            code = row['code']
            name = row['name']
            price = f"{row['price']:.2f}"
            position = f"{row['position']:.1f}%"
            confidence = f"{row['confidence']:.1f}%"
            rows_html += f"""
            <tr>
                <td>{code}</td>
                <td>{name}</td>
                <td>{price}</td>
                <td>{position}</td>
                <td>{confidence}</td>
            </tr>
            """
        table_rows[stage] = rows_html
    
    # 各阶段section
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
                    </tr>
                </thead>
                <tbody>
                    {table_rows[stage]}
                </tbody>
            </table>
        </div>
        """
    
    # 饼图数据
    pie_data = json.dumps([{"name": s, "value": counts[i]} for i, s in enumerate(stages)], ensure_ascii=False)
    
    html = f"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>主力行为诊断报告 - {date_str}</title>
    <script src="https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"></script>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f5f5f5; padding: 20px; }}
        .container {{ max-width: 1200px; margin: 0 auto; }}
        .header {{ background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%); color: white; padding: 30px; border-radius: 12px; margin-bottom: 20px; }}
        .header h1 {{ font-size: 28px; margin-bottom: 10px; }}
        .header .date {{ opacity: 0.8; font-size: 16px; }}
        .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 20px; }}
        .card {{ background: white; border-radius: 12px; padding: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
        .card h2 {{ font-size: 18px; margin-bottom: 15px; color: #333; }}
        #pieChart, #barChart {{ width: 100%; height: 300px; }}
        .stage-section {{ background: white; border-radius: 12px; padding: 20px; margin-bottom: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
        .stage-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px; }}
        .stage-header h2 {{ font-size: 18px; padding-bottom: 10px; border-bottom: 2px solid #f0f0f0; }}
        .stage-count {{ font-size: 24px; font-weight: bold; color: #333; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th, td {{ padding: 10px; text-align: left; border-bottom: 1px solid #f0f0f0; }}
        th {{ background: #fafafa; font-weight: 600; color: #666; }}
        @media (max-width: 768px) {{
            .grid {{ grid-template-columns: 1fr; }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>主力行为诊断报告</h1>
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
            xAxis: {{ type: 'category', data: {json.dumps(stages, ensure_ascii=False)} }},
            yAxis: {{ type: 'value' }},
            series: [{{
                type: 'bar',
                data: {json.dumps(counts)},
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
    print("每日主力行为诊断（HTML版）")
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
            'date': df['date'].iloc[-1],
        })
    
    today = datetime.now().strftime('%Y-%m-%d')
    html_content = generate_html(results, today)
    
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_file = OUTPUT_DIR / f"daily_main_behavior_{today}.html"
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    print(f"\n已生成HTML报告: {output_file}")
    
    df_results = pd.DataFrame(results)
    csv_file = OUTPUT_DIR / f"daily_main_behavior_{today}.csv"
    df_results.to_csv(csv_file, index=False, encoding='utf-8-sig')
    print(f"已保存CSV数据: {csv_file}")


if __name__ == "__main__":
    main()
