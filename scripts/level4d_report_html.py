#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
四维循环看盘法报告 - HTML版（含高量柱安全线/风险线）
=================================================
设计思路（为什么这样写）：
  按照四维循环看盘法步骤生成报告！
  ①从右向左找位置 ②从上往下看量柱 ③从左往右比量能 ④从下往上看量价
  ⑤和历史对比 ⑥全景总结
  加高量柱的安全线和风险线！

量学理论来源：
  - 股海明灯（量学官网论坛）
  - 《量柱擒涨停》黑马王子著
  - 《量线捉涨停》黑马王子著

硬约束：
  - 绝对不用未来函数
  - 客观描述，不做主观判断
"""

import json
import pandas as pd
import numpy as np
from pathlib import Path

# ============================================================
# 配置
# ============================================================
DATA_DIR = Path(__file__).parent.parent / "data" / "kline"
OUTPUT_DIR = Path(__file__).parent.parent / "data" / "analysis"

HOLDINGS = [
    ("sh", "600584"),  # 长电科技
    ("sz", "002156"),  # 通富微电
    ("sh", "603283"),  # 赛腾股份
    ("sz", "300394"),  # 天孚通信
    ("sh", "601138"),  # 工业富联
    ("sh", "601231"),  # 环旭电子
    ("sz", "300476"),  # 胜宏科技
    ("sh", "603516"),  # 淳中科技
]


# ============================================================
# 数据读取
# ============================================================
def load_klines(market, code):
    possible_paths = [
        DATA_DIR / market / f"{code}.json",
        DATA_DIR / market / f"{market}{code}.json",
        DATA_DIR / f"{market}{code}.json",
    ]
    
    for filepath in possible_paths:
        if filepath.exists():
            with open(filepath, 'r') as f:
                data = json.load(f)
            
            klines = data.get('klines', [])
            ncols = len(klines[0])
            
            if ncols == 6:
                cols = ['date', 'open', 'close', 'high', 'low', 'volume']
            else:
                cols = ['date', 'open', 'close', 'high', 'low', 'volume', 'amount']
            
            df = pd.DataFrame(klines)
            df = df.iloc[:, :ncols]
            df.columns = cols[:ncols]
            
            for col in ['open', 'close', 'high', 'low', 'volume']:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            
            df = df.dropna(subset=['open', 'close', 'high', 'low', 'volume'])
            
            return df, data.get('name', code)
    
    return None, None


# ============================================================
# 找高量柱的安全线和风险线
# ============================================================
def find_gaoliang_lines(recent_df):
    """
    找最近N日的高量柱，计算安全线和风险线
    
    量学理论定义：
    - 高量柱 = 某一阶段成交量最大的量柱
    - 安全线 = 高量柱K线的顶部
    - 风险线 = 高量柱K线的底部
    
    取实还是取虚：
    - 实体长、影线短 → 取实体顶底
    - 实体短、影线长 → 取K线最低价
    """
    if len(recent_df) < 5:
        return None, None, None, None
    
    # 找最高量柱
    max_vol_idx = recent_df['volume'].idxmax()
    max_vol_row = recent_df.loc[max_vol_idx]
    
    # K线数据
    open_price = max_vol_row['open']
    close_price = max_vol_row['close']
    high_price = max_vol_row['high']
    low_price = max_vol_row['low']
    
    # 计算实体大小和影线大小
    body_size = abs(close_price - open_price)
    total_range = high_price - low_price
    
    if total_range == 0:
        return None, None, None, None
    
    # 实体占比
    body_ratio = body_size / total_range
    
    # 决定取实还是取虚
    if body_ratio > 0.6:
        # 实体长、影线短 → 取实体顶底
        safe_line = max(open_price, close_price)  # 实体顶部
        risk_line = min(open_price, close_price)   # 实体底部
        line_type = "实体"
    else:
        # 实体短、影线长 → 取K线最低价
        safe_line = high_price   # 最高价
        risk_line = low_price    # 最低价
        line_type = "影线"
    
    return safe_line, risk_line, line_type, max_vol_row['date']


# ============================================================
# 生成单只股票的报告数据
# ============================================================
def get_stock_data(market, code):
    df, name = load_klines(market, code)
    
    if df is None:
        return None
    
    today = df.iloc[-1]
    yesterday = df.iloc[-2]
    
    today_price = today['close']
    today_volume = today['volume']
    
    pct_chg = (today['close'] - yesterday['close']) / yesterday['close'] * 100
    
    # ========== ① 从右向左看：找位置 ==========
    # 短期（20日）
    recent_20 = df.iloc[-20:]
    recent_high = recent_20['high'].max()
    recent_low = recent_20['low'].min()
    
    # 中期（60日）
    recent_60 = df.iloc[-60:] if len(df) > 60 else None
    mid_high = mid_low = None
    if recent_60 is not None:
        mid_high = recent_60['high'].max()
        mid_low = recent_60['low'].min()
    
    # 长期（120日）
    recent_120 = df.iloc[-120:] if len(df) > 120 else None
    long_high = long_low = None
    if recent_120 is not None:
        long_high = recent_120['high'].max()
        long_low = recent_120['low'].min()
    
    # ========== 高量柱的安全线和风险线 ==========
    # 短期（20日）
    safe_20, risk_20, type_20, date_20 = find_gaoliang_lines(recent_20)
    
    # 中期（60日）
    safe_60 = risk_60 = type_60 = date_60 = None
    if recent_60 is not None:
        safe_60, risk_60, type_60, date_60 = find_gaoliang_lines(recent_60)
    
    # 长期（120日）
    safe_120 = risk_120 = type_120 = date_120 = None
    if recent_120 is not None:
        safe_120, risk_120, type_120, date_120 = find_gaoliang_lines(recent_120)
    
    # ========== ② 从上往下看：看量柱 ==========
    vol_high_20 = recent_20['volume'].max()
    vol_low_20 = recent_20['volume'].min()
    
    vol_ratio_yesterday = today_volume / yesterday['volume']
    vol_ratio_ma5 = today_volume / df['volume'].iloc[-6:-1].mean()
    
    vol_pos_20 = (today_volume - vol_low_20) / (vol_high_20 - vol_low_20) * 100
    
    # ========== ③ 从左往右看：比量能 ==========
    vol_vs_recent_high = today_volume / vol_high_20 * 100
    vol_vs_recent_low = today_volume / vol_low_20 * 100
    
    v1 = df.iloc[-1]['volume']
    v2 = df.iloc[-2]['volume']
    v3 = df.iloc[-3]['volume']
    if v1 > v2 > v3:
        vol_trend = "连续放量"
    elif v1 < v2 < v3:
        vol_trend = "连续缩量"
    else:
        vol_trend = "无连续趋势"
    
    # ========== ④ 从下往上看：看量价 ==========
    is_yang = today['close'] > today['open']
    
    if is_yang and vol_ratio_yesterday > 1.5:
        vol_price = "放量涨"
    elif is_yang and vol_ratio_yesterday < 0.7:
        vol_price = "缩量涨"
    elif not is_yang and vol_ratio_yesterday > 1.5:
        vol_price = "放量跌"
    elif not is_yang and vol_ratio_yesterday < 0.7:
        vol_price = "缩量跌"
    else:
        vol_price = "平量整理"
    
    body_size = abs(today['close'] - today['open'])
    body_ratio = body_size / (today['high'] - today['low']) * 100
    
    # ========== ⑤ 和历史对比 ==========
    short_dist_high = (recent_high - today_price) / today_price * 100
    short_dist_low = (today_price - recent_low) / today_price * 100
    
    mid_dist_high = (mid_high - today_price) / today_price * 100 if mid_high else 0
    mid_dist_low = (today_price - mid_low) / today_price * 100 if mid_low else 0
    
    long_dist_high = (long_high - today_price) / today_price * 100 if long_high else 0
    long_dist_low = (today_price - long_low) / today_price * 100 if long_low else 0
    
    # ========== ⑥ 全景总结 ==========
    pos_120 = (today_price - long_low) / (long_high - long_low) * 100 if long_high else 50
    if pos_120 > 70:
        pos_status = "高位"
    elif pos_120 < 30:
        pos_status = "低位"
    else:
        pos_status = "中位"
    
    if vol_pos_20 > 80:
        vol_status = "天量"
    elif vol_pos_20 < 20:
        vol_status = "地量"
    else:
        vol_status = "正常"
    
    if is_yang:
        power = "买方占优"
    else:
        power = "卖方占优"
    
    pct_3d = (today['close'] - df.iloc[-4]['close']) / df.iloc[-4]['close'] * 100
    pct_5d = (today['close'] - df.iloc[-6]['close']) / df.iloc[-6]['close'] * 100
    
    return {
        'name': name,
        'code': f"{market}{code}",
        'date': today['date'],
        'close': today_price,
        'pct_chg': pct_chg,
        # ①从右向左
        'recent_high': recent_high,
        'recent_low': recent_low,
        'mid_high': mid_high,
        'mid_low': mid_low,
        'long_high': long_high,
        'long_low': long_low,
        # 高量柱安全线/风险线
        'safe_20': safe_20,
        'risk_20': risk_20,
        'type_20': type_20,
        'date_20': date_20,
        'safe_60': safe_60,
        'risk_60': risk_60,
        'type_60': type_60,
        'date_60': date_60,
        'safe_120': safe_120,
        'risk_120': risk_120,
        'type_120': type_120,
        'date_120': date_120,
        # ②从上往下
        'vol_high_20': vol_high_20,
        'vol_low_20': vol_low_20,
        'vol_ratio_yesterday': vol_ratio_yesterday,
        'vol_ratio_ma5': vol_ratio_ma5,
        'vol_pos_20': vol_pos_20,
        # ③从左往右
        'vol_vs_recent_high': vol_vs_recent_high,
        'vol_vs_recent_low': vol_vs_recent_low,
        'vol_trend': vol_trend,
        # ④从下往上
        'is_yang': is_yang,
        'vol_price': vol_price,
        'body_ratio': body_ratio,
        # ⑤和历史对比
        'short_dist_high': short_dist_high,
        'short_dist_low': short_dist_low,
        'mid_dist_high': mid_dist_high,
        'mid_dist_low': mid_dist_low,
        'long_dist_high': long_dist_high,
        'long_dist_low': long_dist_low,
        # ⑥全景总结
        'pos_status': pos_status,
        'vol_status': vol_status,
        'power': power,
        'pct_3d': pct_3d,
        'pct_5d': pct_5d,
    }


# ============================================================
# 生成HTML
# ============================================================
def generate_html(stocks_data, today_str):
    items = []
    for stock in stocks_data:
        if stock is None:
            continue
        
        price_class = "price-up" if stock['pct_chg'] > 0 else "price-down"
        
        mid_high_str = f"{stock['mid_high']:.2f}" if stock['mid_high'] else '-'
        mid_low_str = f"{stock['mid_low']:.2f}" if stock['mid_low'] else '-'
        
        # 高量柱安全线/风险线字符串
        safe_20_str = f"{stock['safe_20']:.2f}" if stock['safe_20'] else '-'
        risk_20_str = f"{stock['risk_20']:.2f}" if stock['risk_20'] else '-'
        safe_60_str = f"{stock['safe_60']:.2f}" if stock['safe_60'] else '-'
        risk_60_str = f"{stock['risk_60']:.2f}" if stock['risk_60'] else '-'
        safe_120_str = f"{stock['safe_120']:.2f}" if stock['safe_120'] else '-'
        risk_120_str = f"{stock['risk_120']:.2f}" if stock['risk_120'] else '-'
        
        item_html = f"""
        <div class="stock-card">
            <div class="stock-header">
                <div>
                    <div class="stock-name">{stock['name']}</div>
                    <div class="stock-code">{stock['code']}</div>
                </div>
                <div class="stock-price {price_class}">{stock['close']:.2f}元 ({stock['pct_chg']:+.2f}%)</div>
            </div>
            
            <!-- ① 从右向左看 -->
            <div class="step-section">
                <div class="step-title">① 从右向左看：找位置</div>
                <div class="step-content">
                    <div class="grid-2">
                        <div class="grid-item">
                            <div class="label">20日高点</div>
                            <div class="value">{stock['recent_high']:.2f}</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">20日低点</div>
                            <div class="value">{stock['recent_low']:.2f}</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">60日高点</div>
                            <div class="value">{mid_high_str}</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">60日低点</div>
                            <div class="value">{mid_low_str}</div>
                        </div>
                    </div>
                </div>
            </div>
            
            <!-- 高量柱安全线/风险线 -->
            <div class="step-section">
                <div class="step-title">高量柱安全线/风险线</div>
                <div class="step-content">
                    <div class="grid-2">
                        <div class="grid-item">
                            <div class="label">20日安全线</div>
                            <div class="value">{safe_20_str}</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">20日风险线</div>
                            <div class="value">{risk_20_str}</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">60日安全线</div>
                            <div class="value">{safe_60_str}</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">60日风险线</div>
                            <div class="value">{risk_60_str}</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">120日安全线</div>
                            <div class="value">{safe_120_str}</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">120日风险线</div>
                            <div class="value">{risk_120_str}</div>
                        </div>
                    </div>
                </div>
            </div>
            
            <!-- ② 从上往下看 -->
            <div class="step-section">
                <div class="step-title">② 从上往下看：看量柱</div>
                <div class="step-content">
                    <div class="grid-2">
                        <div class="grid-item">
                            <div class="label">20日天量</div>
                            <div class="value">{stock['vol_high_20']:.0f}</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">20日地量</div>
                            <div class="value">{stock['vol_low_20']:.0f}</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">量比(vs昨日)</div>
                            <div class="value">{stock['vol_ratio_yesterday']:.2f}</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">量能位置(20日)</div>
                            <div class="value">{stock['vol_pos_20']:.1f}%</div>
                        </div>
                    </div>
                </div>
            </div>
            
            <!-- ③ 从左往右看 -->
            <div class="step-section">
                <div class="step-title">③ 从左往右看：比量能</div>
                <div class="step-content">
                    <div class="grid-2">
                        <div class="grid-item">
                            <div class="label">vs 20日天量</div>
                            <div class="value">{stock['vol_vs_recent_high']:.1f}%</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">vs 20日地量</div>
                            <div class="value">{stock['vol_vs_recent_low']:.1f}%</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">量比(vs5日)</div>
                            <div class="value">{stock['vol_ratio_ma5']:.2f}</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">量能趋势</div>
                            <div class="value">{stock['vol_trend']}</div>
                        </div>
                    </div>
                </div>
            </div>
            
            <!-- ④ 从下往上看 -->
            <div class="step-section">
                <div class="step-title">④ 从下往上看：看量价</div>
                <div class="step-content">
                    <div class="grid-2">
                        <div class="grid-item">
                            <div class="label">量价组合</div>
                            <div class="value">{stock['vol_price']}</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">实体占比</div>
                            <div class="value">{stock['body_ratio']:.1f}%</div>
                        </div>
                    </div>
                </div>
            </div>
            
            <!-- ⑤ 和历史对比 -->
            <div class="step-section">
                <div class="step-title">⑤ 和历史对比</div>
                <div class="step-content">
                    <p><strong>短期(20日)：</strong>
                        离高点 {stock['short_dist_high']:+.2f}% | 
                        离低点 {stock['short_dist_low']:+.2f}%
                    </p>
                    <p><strong>中期(60日)：</strong>
                        离高点 {stock['mid_dist_high']:+.2f}% | 
                        离低点 {stock['mid_dist_low']:+.2f}%
                    </p>
                    <p><strong>长期(120日)：</strong>
                        离高点 {stock['long_dist_high']:+.2f}% | 
                        离低点 {stock['long_dist_low']:+.2f}%
                    </p>
                </div>
            </div>
            
            <!-- ⑥ 全景总结 -->
            <div class="step-section">
                <div class="step-title">⑥ 全景总结</div>
                <div class="summary-box">
                    <p>
                        今日{stock['pct_chg']:+.2f}%，{stock['vol_status']}，{stock['pos_status']}。<br>
                        量价组合：{stock['vol_price']}，{stock['power']}。<br>
                        近3日涨跌：{stock['pct_3d']:+.2f}%，近5日涨跌：{stock['pct_5d']:+.2f}%。<br>
                        {stock['vol_trend']}。
                    </p>
                </div>
            </div>
        </div>
        """
        items.append(item_html)
    
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>四维循环看盘报告 - {today_str}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; 
            background: #0f172a; 
            color: #e2e8f0; 
            line-height: 1.6;
            padding: 20px;
        }}
        .container {{ max-width: 900px; margin: 0 auto; }}
        .header {{ 
            background: linear-gradient(135deg, #1e3a8a 0%, #1e40af 100%); 
            color: white; 
            padding: 30px; 
            border-radius: 12px; 
            margin-bottom: 20px;
            border-left: 4px solid #fbbf24;
        }}
        .header h1 {{ font-size: 24px; color: #fbbf24; margin-bottom: 8px; }}
        .header .date {{ opacity: 0.8; font-size: 14px; }}
        
        .stock-card {{ 
            background: #1e293b; 
            border-radius: 12px; 
            padding: 20px; 
            margin-bottom: 15px; 
            border: 1px solid #334155;
        }}
        .stock-header {{ 
            display: flex; 
            justify-content: space-between; 
            align-items: center; 
            margin-bottom: 15px; 
            padding-bottom: 15px; 
            border-bottom: 1px solid #334155;
        }}
        .stock-name {{ font-size: 18px; font-weight: bold; color: #e2e8f0; }}
        .stock-code {{ font-size: 12px; color: #94a3b8; }}
        .stock-price {{ font-size: 22px; font-weight: bold; }}
        .price-up {{ color: #ef4444; }}
        .price-down {{ color: #22c55e; }}
        
        .step-section {{ margin-bottom: 15px; }}
        .step-title {{ 
            font-size: 14px; 
            font-weight: bold; 
            color: #60a5fa; 
            margin-bottom: 8px; 
            padding-left: 8px; 
            border-left: 3px solid #fbbf24; 
        }}
        .step-content {{ 
            background: #0f172a; 
            padding: 12px; 
            border-radius: 8px; 
            font-size: 13px; 
            color: #cbd5e1; 
        }}
        .step-content p {{ margin-bottom: 4px; }}
        
        .grid-2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }}
        .grid-item {{ 
            background: #0f172a; 
            padding: 8px; 
            border-radius: 6px; 
            font-size: 13px; 
        }}
        .grid-item .label {{ color: #94a3b8; font-size: 11px; }}
        .grid-item .value {{ font-weight: bold; color: #e2e8f0; }}
        
        .summary-box {{
            background: linear-gradient(135deg, #1e3a8a 0%, #1e40af 100%);
            padding: 15px;
            border-radius: 8px;
            margin-top: 10px;
        }}
        .summary-box p {{ margin: 0; color: #fbbf24; font-size: 13px; line-height: 1.8; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>四维循环看盘报告</h1>
            <div class="date">{today_str}</div>
            <div class="note" style="margin-top:10px;font-size:13px;opacity:0.7">四维循环看盘 + 高量柱安全线/风险线</div>
        </div>
        
        {''.join(items)}
    </div>
</body>
</html>
"""
    
    return html


# ============================================================
# 主函数
# ============================================================
def main():
    print("=" * 60)
    print("四维循环看盘报告 - HTML版（含高量柱安全线/风险线）")
    print("=" * 60)
    
    stocks_data = []
    today_str = ""
    
    for market, code in HOLDINGS:
        try:
            data = get_stock_data(market, code)
            if data:
                stocks_data.append(data)
                today_str = data['date']
                print(f"  已生成：{data['name']}")
        except Exception as e:
            print(f"  Error: {market}{code} {e}")
    
    html_content = generate_html(stocks_data, today_str)
    
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    html_file = OUTPUT_DIR / f"my_holdings_4d_report_{today_str}.html"
    
    with open(html_file, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    print(f"\n已生成HTML报告: {html_file}")


if __name__ == "__main__":
    main()
