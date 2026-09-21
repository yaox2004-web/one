#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
四维循环看盘法报告 - HTML版（量学原版：大阴实顶+四维对比+个股解读）
=================================================
设计思路（为什么这样写）：
  1. 【起点】先找最近的大阴实顶（量学原版四维看盘的起点）
  2. 【四维对比】从大阴实顶开始做四维对比
     - ① 从右向左看：比较价柱的高低阴阳
     - ② 从上往下看：比较量价的真假大小
     - ③ 从左往右看：比较量柱的远近多少
     - ④ 从下往上看：比较量价的长短伸缩
  3. 【个股解读】用四维看盘法客观描述当前状态，不做主观判断

【重要：无未来函数保证】
  1. 所有判断只用截止到今天收盘的数据
  2. 大阴实顶是历史数据，不是未来数据

量学理论来源：
  - 股海明灯（量学官网论坛）
  - 《量柱擒涨停》黑马王子著
  - 《量线捉涨停》黑马王子著
  - 四维看盘 = 回形针看盘法
"""

import json
import pandas as pd
import numpy as np
from pathlib import Path

# ============================================================
# 【配置区】所有参数阈值都在这里，方便调整！
# ============================================================

# --- 文件路径配置 ---
DATA_DIR = Path(__file__).parent.parent / "data" / "kline"
OUTPUT_DIR = Path(__file__).parent.parent / "data" / "analysis"

# --- 持仓股配置 ---
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

# --- 大阴实顶参数 ---
YIN_BODY_PCT = 3.0        # 中大阴线实体跌幅阈值（%）
YIN_LOOKBACK = 60          # 往前找多少天内的中大阴线

# --- 周期配置 ---
SHORT_WINDOW = 20    # 短期窗口（交易日）
MID_WINDOW = 60      # 中期窗口（交易日）
LONG_WINDOW = 120    # 长期窗口（交易日）

# --- 量价对比参数 ---
VOL_RATIO_HIGH = 1.5     # 量比>1.5算放量
VOL_RATIO_LOW = 0.7      # 量比<0.7算缩量
BODY_RATIO_LONG = 0.6    # 实体占比超过60%算长实体
BODY_RATIO_SHORT = 0.3   # 实体占比<30%算短实体

# --- 位置分位参数 ---
POSITION_HIGH = 70        # 位置>70%算高位
POSITION_LOW = 30         # 位置<30%算低位


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
# 找大阴实顶（四维看盘的起点！）
# ============================================================
def find_big_yin_top(df, lookback_days, yin_body_pct):
    """
    找最近的中大阴线实体顶部（大阴实顶）
    
    量学理论：
    - 四维看盘的起点：从大阴实顶开始看
    - 大阴实顶 = 中大阴线的开盘价（因为是阴线，开盘价>收盘价）
    - 大阴实顶是多空双方上次休战的"警戒点"
    
    【无未来函数】：只用历史数据
    """
    if len(df) < lookback_days:
        return None, None, None, None, None
    
    recent_df = df.iloc[-lookback_days:]
    
    for i in range(len(recent_df)-1, -1, -1):
        row = recent_df.iloc[i]
        
        # 找阴线
        if row['close'] >= row['open']:
            continue
        
        # 计算实体跌幅
        body_pct = (row['open'] - row['close']) / row['close'] * 100
        
        # 中大阴线
        if body_pct >= yin_body_pct:
            big_yin_top = row['open']  # 阴线实体顶部 = 开盘价
            big_yin_bottom = row['close']  # 阴线实体底部 = 收盘价
            big_yin_date = row['date']
            big_yin_vol = row['volume']
            big_yin_idx = len(df) - lookback_days + i  # 在整个df中的索引
            
            return big_yin_top, big_yin_bottom, big_yin_date, big_yin_vol, big_yin_idx
    
    return None, None, None, None, None


# ============================================================
# 生成个股解读
# ============================================================
def generate_interpretation(stock):
    """
    用四维看盘法客观解读个股当前状态
    
    原则：客观描述，不做主观判断
    """
    interpretations = []
    
    # 1. 大阴实顶位置解读
    if stock['big_yin_top']:
        if stock['price_above_yintop']:
            interpretations.append(
                f"当前价格在大阴实顶（{stock['big_yin_top']:.2f}元，{stock['big_yin_date']}）上方，"
                f"高出{stock['price_vs_yintop_pct']:.2f}%。"
                f"说明大阴实顶那天卖出的人，卖出后价格又涨回来了。"
            )
        else:
            interpretations.append(
                f"当前价格在大阴实顶（{stock['big_yin_top']:.2f}元，{stock['big_yin_date']}）下方，"
                f"低于{abs(stock['price_vs_yintop_pct']):.2f}%。"
                f"说明大阴实顶那天卖出的人，卖出后价格继续下跌。"
            )
    else:
        interpretations.append("近60日没有出现中大阴线，说明近期没有明显的多空大战分界线。")
    
    # 2. 阴阳对比解读
    if stock['yang_count'] + stock['yin_count'] > 0:
        if stock['yang_yin_ratio'] > 1.5:
            interpretations.append(
                f"从大阴实顶到今天，阳线{stock['yang_count']}根，阴线{stock['yin_count']}根，"
                f"阴阳比{stock['yang_yin_ratio']:.2f}，阳线明显多于阴线。"
            )
        elif stock['yang_yin_ratio'] < 0.67:
            interpretations.append(
                f"从大阴实顶到今天，阳线{stock['yang_count']}根，阴线{stock['yin_count']}根，"
                f"阴阳比{stock['yang_yin_ratio']:.2f}，阴线明显多于阳线。"
            )
        else:
            interpretations.append(
                f"从大阴实顶到今天，阳线{stock['yang_count']}根，阴线{stock['yin_count']}根，"
                f"阴阳比{stock['yang_yin_ratio']:.2f}，多空双方力量相当。"
            )
    
    # 3. 量价真假解读
    if stock['yin_vol_size'] == "大量":
        interpretations.append(
            f"大阴实顶那天的成交量很大（{stock['yin_vol_size']}），"
            f"说明那天多空双方博弈很激烈。"
        )
    elif stock['yin_vol_size'] == "小量":
        interpretations.append(
            f"大阴实顶那天的成交量很小（{stock['yin_vol_size']}），"
            f"说明那天虽然价格跌了，但成交很清淡。"
        )
    
    # 4. 时间距离解读
    if stock['days_since_yin'] <= 10:
        interpretations.append(
            f"大阴实顶发生在{stock['days_since_yin']}天前，时间很近，"
            f"这个位置的记忆还很新鲜。"
        )
    elif stock['days_since_yin'] <= 30:
        interpretations.append(
            f"大阴实顶发生在{stock['days_since_yin']}天前，时间中等，"
            f"这个位置还有一定的影响力。"
        )
    else:
        interpretations.append(
            f"大阴实顶发生在{stock['days_since_yin']}天前，时间很远，"
            f"这个位置的影响力已经比较弱了。"
        )
    
    # 5. 量的多少对比解读
    if stock['today_vs_yin_vol'] > 100:
        interpretations.append(
            f"今天的成交量是大阴实顶那天的{stock['today_vs_yin_vol']:.1f}%，"
            f"说明今天的博弈比那天还激烈。"
        )
    elif stock['today_vs_yin_vol'] < 50:
        interpretations.append(
            f"今天的成交量是大阴实顶那天的{stock['today_vs_yin_vol']:.1f}%，"
            f"说明今天的成交比那天清淡很多。"
        )
    else:
        interpretations.append(
            f"今天的成交量是大阴实顶那天的{stock['today_vs_yin_vol']:.1f}%，"
            f"和那天差不多。"
        )
    
    # 6. 量价长短伸缩解读
    interpretations.append(
        f"今天的量柱：{stock['vol_length']}；今天的价柱：{stock['price_length']}。"
    )
    
    if stock['body_ratio'] > 60:
        interpretations.append(
            f"今天K线实体占比{stock['body_ratio']:.1f}%，实体较长，"
            f"说明今天多空一方赢了，而且赢得比较彻底。"
        )
    elif stock['body_ratio'] < 30:
        interpretations.append(
            f"今天K线实体占比{stock['body_ratio']:.1f}%，实体很短，"
            f"说明今天多空打了个平手。"
        )
    
    # 7. 位置总结
    interpretations.append(
        f"当前价格在近120日{stock['pos_status']}，近3日涨跌{stock['pct_3d']:+.2f}%，"
        f"近5日涨跌{stock['pct_5d']:+.2f}%。"
    )
    
    return interpretations


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
    
    # ========== 【起点】找大阴实顶 ==========
    big_yin_top, big_yin_bottom, big_yin_date, big_yin_vol, big_yin_idx = find_big_yin_top(
        df, YIN_LOOKBACK, YIN_BODY_PCT
    )
    
    # ========== ① 从右向左看：比较价柱的高低阴阳 ==========
    # 从今天往大阴实顶方向看
    # 对比1：价格在大阴实顶上方还是下方？
    if big_yin_top:
        price_vs_yintop = today_price - big_yin_top
        price_vs_yintop_pct = price_vs_yintop / big_yin_top * 100
        price_above_yintop = price_vs_yintop > 0
    else:
        price_vs_yintop = 0
        price_vs_yintop_pct = 0
        price_above_yintop = None
    
    # 对比2：从大阴实顶到今天，阳线多还是阴线多？
    if big_yin_idx:
        period_df = df.iloc[big_yin_idx:]
        yang_count = sum(period_df['close'] > period_df['open'])
        yin_count = sum(period_df['close'] < period_df['open'])
        yang_yin_ratio = yang_count / max(yin_count, 1)
    else:
        yang_count = 0
        yin_count = 0
        yang_yin_ratio = 0
    
    # 对比3：高低对比
    recent_20 = df.iloc[-SHORT_WINDOW:]
    recent_high = recent_20['high'].max()
    recent_low = recent_20['low'].min()
    
    # ========== ② 从上往下看：比较量价的真假大小 ==========
    # 从大阴实顶的价柱往下看量柱
    # 对比1：大阴实顶的量是大还是小？
    if big_yin_vol:
        # 和近期平均量对比
        avg_vol_20 = recent_20['volume'].mean()
        big_yin_vs_avg = big_yin_vol / avg_vol_20
        
        if big_yin_vs_avg > VOL_RATIO_HIGH:
            yin_vol_size = "大量"
        elif big_yin_vs_avg < VOL_RATIO_LOW:
            yin_vol_size = "小量"
        else:
            yin_vol_size = "平量"
    else:
        yin_vol_size = "未知"
    
    # 对比2：价跌量缩是真跌？价跌量增是假跌？
    # 大阴实顶那天：价跌（阴线）+ 量？
    # 如果价跌量缩 → 真跌（卖方不想卖了）
    # 如果价跌量增 → 假跌（卖方在出货？或者买方在接？）
    if big_yin_vol and big_yin_vs_avg:
        if big_yin_vs_avg > VOL_RATIO_HIGH:
            yin_vol_true = "量大（可能是出货）"
        elif big_yin_vs_avg < VOL_RATIO_LOW:
            yin_vol_true = "量小（真跌，没人接）"
        else:
            yin_vol_true = "量平（正常调整）"
    else:
        yin_vol_true = "未知"
    
    # ========== ③ 从左往右看：比较量柱的远近多少 ==========
    # 从大阴实顶的量柱往右看
    # 对比1：远近——大阴实顶离今天多远？
    if big_yin_idx:
        days_since_yin = len(df) - 1 - big_yin_idx
    else:
        days_since_yin = 0
    
    # 对比2：多少——今天的量 vs 大阴实顶的量
    if big_yin_vol:
        today_vs_yin_vol = today_volume / big_yin_vol * 100
        
        if today_vs_yin_vol > 100:
            vol_more_less = "今天量更大"
        elif today_vs_yin_vol < 50:
            vol_more_less = "今天量更小"
        else:
            vol_more_less = "差不多"
    else:
        today_vs_yin_vol = 0
        vol_more_less = "未知"
    
    # 对比3：时间距离判断影响力
    if days_since_yin <= 10:
        time_impact = "很近（影响力强）"
    elif days_since_yin <= 30:
        time_impact = "中等（影响力一般）"
    else:
        time_impact = "很远（影响力弱）"
    
    # ========== ④ 从下往上看：比较量价的长短伸缩 ==========
    # 从今天的量柱往上看价柱
    # 对比1：量柱长短——今天的量柱是长还是短？
    vol_high_20 = recent_20['volume'].max()
    vol_low_20 = recent_20['volume'].min()
    vol_pos_20 = (today_volume - vol_low_20) / (vol_high_20 - vol_low_20) * 100
    
    if vol_pos_20 > 80:
        vol_length = "长量柱（天量）"
    elif vol_pos_20 < 20:
        vol_length = "短量柱（地量）"
    else:
        vol_length = "中等量柱"
    
    # 对比2：价柱伸缩——今天的价柱是长还是短？
    today_range = today['high'] - today['low']
    avg_range_20 = recent_20.apply(lambda x: x['high'] - x['low'], axis=1).mean()
    range_ratio = today_range / avg_range_20
    
    if range_ratio > 1.5:
        price_length = "长价柱（振幅大）"
    elif range_ratio < 0.7:
        price_length = "短价柱（振幅小）"
    else:
        price_length = "中等价柱"
    
    # 对比3：实体长短
    body_size = abs(today['close'] - today['open'])
    body_ratio = body_size / today_range * 100 if today_range > 0 else 0
    
    if body_ratio > BODY_RATIO_LONG * 100:
        body_length = "长实体"
    elif body_ratio < BODY_RATIO_SHORT * 100:
        body_length = "短实体（十字星）"
    else:
        body_length = "中等实体"
    
    # ========== ⑤ 和历史对比 ==========
    # 短期20日
    short_dist_high = (recent_high - today_price) / today_price * 100
    short_dist_low = (today_price - recent_low) / today_price * 100
    
    # 中期60日
    recent_60 = df.iloc[-MID_WINDOW:] if len(df) > MID_WINDOW else None
    if recent_60 is not None:
        mid_high = recent_60['high'].max()
        mid_low = recent_60['low'].min()
        mid_dist_high = (mid_high - today_price) / today_price * 100
        mid_dist_low = (today_price - mid_low) / today_price * 100
    else:
        mid_high = mid_low = mid_dist_high = mid_dist_low = None
    
    # 长期120日
    recent_120 = df.iloc[-LONG_WINDOW:] if len(df) > LONG_WINDOW else None
    if recent_120 is not None:
        long_high = recent_120['high'].max()
        long_low = recent_120['low'].min()
        long_dist_high = (long_high - today_price) / today_price * 100
        long_dist_low = (today_price - long_low) / today_price * 100
    else:
        long_high = long_low = long_dist_high = long_dist_low = None
    
    # ========== ⑥ 全景总结 ==========
    pos_120 = (today_price - long_low) / (long_high - long_low) * 100 if long_high else 50
    
    if pos_120 > POSITION_HIGH:
        pos_status = "高位"
    elif pos_120 < POSITION_LOW:
        pos_status = "低位"
    else:
        pos_status = "中位"
    
    if today['close'] > today['open']:
        power = "买方占优"
    else:
        power = "卖方占优"
    
    pct_3d = (today['close'] - df.iloc[-4]['close']) / df.iloc[-4]['close'] * 100
    pct_5d = (today['close'] - df.iloc[-6]['close']) / df.iloc[-6]['close'] * 100
    
    stock_data = {
        'name': name,
        'code': f"{market}{code}",
        'date': today['date'],
        'close': today_price,
        'pct_chg': pct_chg,
        # 大阴实顶
        'big_yin_top': big_yin_top,
        'big_yin_bottom': big_yin_bottom,
        'big_yin_date': big_yin_date,
        'big_yin_vol': big_yin_vol,
        # ① 从右向左看
        'price_above_yintop': price_above_yintop,
        'price_vs_yintop_pct': price_vs_yintop_pct,
        'yang_count': yang_count,
        'yin_count': yin_count,
        'yang_yin_ratio': yang_yin_ratio,
        'recent_high': recent_high,
        'recent_low': recent_low,
        # ② 从上往下看
        'yin_vol_size': yin_vol_size,
        'yin_vol_true': yin_vol_true,
        # ③ 从左往右看
        'days_since_yin': days_since_yin,
        'today_vs_yin_vol': today_vs_yin_vol,
        'vol_more_less': vol_more_less,
        'time_impact': time_impact,
        # ④ 从下往上看
        'vol_pos_20': vol_pos_20,
        'vol_length': vol_length,
        'price_length': price_length,
        'body_length': body_length,
        'body_ratio': body_ratio,
        # ⑤ 和历史对比
        'short_dist_high': short_dist_high,
        'short_dist_low': short_dist_low,
        'mid_high': mid_high,
        'mid_low': mid_low,
        'mid_dist_high': mid_dist_high,
        'mid_dist_low': mid_dist_low,
        'long_high': long_high,
        'long_low': long_low,
        'long_dist_high': long_dist_high,
        'long_dist_low': long_dist_low,
        # ⑥ 全景总结
        'pos_status': pos_status,
        'power': power,
        'pct_3d': pct_3d,
        'pct_5d': pct_5d,
    }
    
    # 生成个股解读
    stock_data['interpretations'] = generate_interpretation(stock_data)
    
    return stock_data


# ============================================================
# 生成HTML
# ============================================================
def generate_html(stocks_data, today_str):
    items = []
    for stock in stocks_data:
        if stock is None:
            continue
        
        price_class = "price-up" if stock['pct_chg'] > 0 else "price-down"
        
        # 大阴实顶显示
        if stock['big_yin_top']:
            yintop_text = f"{stock['big_yin_top']:.2f}（{stock['big_yin_date']}）"
        else:
            yintop_text = "无（近60日无中大阴线）"
        
        # 价格在大阴实顶上方/下方
        if stock['price_above_yintop'] is True:
            yintop_status = "上方（强势）"
            yintop_color = "#ef4444"
        elif stock['price_above_yintop'] is False:
            yintop_status = "下方（弱势）"
            yintop_color = "#22c55e"
        else:
            yintop_status = "未知"
            yintop_color = "#94a3b8"
        
        mid_high_str = f"{stock['mid_high']:.2f}" if stock['mid_high'] else '-'
        mid_low_str = f"{stock['mid_low']:.2f}" if stock['mid_low'] else '-'
        long_high_str = f"{stock['long_high']:.2f}" if stock['long_high'] else '-'
        long_low_str = f"{stock['long_low']:.2f}" if stock['long_low'] else '-'
        
        # 个股解读HTML
        interpretation_html = ""
        for i, interp in enumerate(stock['interpretations']):
            interpretation_html += f"<p style='margin:8px 0; padding-left:10px; border-left: 3px solid #fbbf24;'>{interp}</p>\n"
        
        item_html = f"""
        <div class="stock-card">
            <div class="stock-header">
                <div>
                    <div class="stock-name">{stock['name']}</div>
                    <div class="stock-code">{stock['code']}</div>
                </div>
                <div class="stock-price {price_class}">{stock['close']:.2f}元 ({stock['pct_chg']:+.2f}%)</div>
            </div>
            
            <!-- 【起点】大阴实顶 -->
            <div class="step-section">
                <div class="step-title">起点：大阴实顶</div>
                <div class="step-content">
                    <div class="grid-2">
                        <div class="grid-item">
                            <div class="label">大阴实顶（近60日）</div>
                            <div class="value">{yintop_text}</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">当前位置</div>
                            <div class="value" style="color:{yintop_color}">{yintop_status}</div>
                        </div>
                    </div>
                </div>
            </div>
            
            <!-- ① 从右向左看：比较价柱的高低阴阳 -->
            <div class="step-section">
                <div class="step-title">① 从右向左看：比较价柱的高低阴阳</div>
                <div class="step-content">
                    <div class="grid-2">
                        <div class="grid-item">
                            <div class="label">价格vs大阴实顶</div>
                            <div class="value">{stock['price_vs_yintop_pct']:+.2f}%</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">阳线/阴线数量</div>
                            <div class="value">{stock['yang_count']}阳 / {stock['yin_count']}阴</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">阴阳比</div>
                            <div class="value">{stock['yang_yin_ratio']:.2f}</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">20日高点</div>
                            <div class="value">{stock['recent_high']:.2f}</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">20日低点</div>
                            <div class="value">{stock['recent_low']:.2f}</div>
                        </div>
                    </div>
                </div>
            </div>
            
            <!-- ② 从上往下看：比较量价的真假大小 -->
            <div class="step-section">
                <div class="step-title">② 从上往下看：比较量价的真假大小</div>
                <div class="step-content">
                    <div class="grid-2">
                        <div class="grid-item">
                            <div class="label">大阴实顶的量</div>
                            <div class="value">{stock['yin_vol_size']}</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">量价真假判断</div>
                            <div class="value">{stock['yin_vol_true']}</div>
                        </div>
                    </div>
                </div>
            </div>
            
            <!-- ③ 从左往右看：比较量柱的远近多少 -->
            <div class="step-section">
                <div class="step-title">③ 从左往右看：比较量柱的远近多少</div>
                <div class="step-content">
                    <div class="grid-2">
                        <div class="grid-item">
                            <div class="label">时间距离</div>
                            <div class="value">{stock['days_since_yin']}天前</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">时间影响力</div>
                            <div class="value">{stock['time_impact']}</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">今天量vs大阴实顶量</div>
                            <div class="value">{stock['today_vs_yin_vol']:.1f}%</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">量的多少对比</div>
                            <div class="value">{stock['vol_more_less']}</div>
                        </div>
                    </div>
                </div>
            </div>
            
            <!-- ④ 从下往上看：比较量价的长短伸缩 -->
            <div class="step-section">
                <div class="step-title">④ 从下往上看：比较量价的长短伸缩</div>
                <div class="step-content">
                    <div class="grid-2">
                        <div class="grid-item">
                            <div class="label">量柱长短</div>
                            <div class="value">{stock['vol_length']}</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">量能位置(20日)</div>
                            <div class="value">{stock['vol_pos_20']:.1f}%</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">价柱伸缩</div>
                            <div class="value">{stock['price_length']}</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">实体长短</div>
                            <div class="value">{stock['body_length']}</div>
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
            
            <!-- 个股解读 -->
            <div class="step-section">
                <div class="step-title">📖 个股解读（四维看盘法）</div>
                <div class="step-content" style="background: linear-gradient(135deg, #1e3a8a 0%, #1e40af 100%);">
                    {interpretation_html}
                </div>
            </div>
            
            <!-- ⑥ 全景总结 -->
            <div class="step-section">
                <div class="step-title">⑥ 全景总结</div>
                <div class="summary-box">
                    <p>
                        今日{stock['pct_chg']:+.2f}%，{stock['pos_status']}，{stock['power']}。<br>
                        量柱：{stock['vol_length']}，价柱：{stock['price_length']}。<br>
                        大阴实顶：{yintop_text}<br>
                        近3日涨跌：{stock['pct_3d']:+.2f}%，近5日涨跌：{stock['pct_5d']:+.2f}%。<br>
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
        
        .signal-guide {{
            background: #1e293b;
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 20px;
            border: 1px solid #334155;
        }}
        .signal-guide h2 {{
            font-size: 18px;
            color: #fbbf24;
            margin-bottom: 15px;
            padding-bottom: 10px;
            border-bottom: 1px solid #334155;
        }}
        .signal-item {{
            margin-bottom: 12px;
            padding: 10px;
            background: #0f172a;
            border-radius: 8px;
        }}
        .signal-item h3 {{
            font-size: 14px;
            color: #60a5fa;
            margin-bottom: 6px;
        }}
        .signal-item p {{
            font-size: 12px;
            color: #cbd5e1;
            margin-bottom: 4px;
        }}
        .signal-item .source {{
            font-size: 11px;
            color: #94a3b8;
            font-style: italic;
        }}
        
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
        .grid-item .value {{ font-weight: bold; color: #e2e8f0; font-size: 12px; }}
        
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
            <div class="note" style="margin-top:10px;font-size:13px;opacity:0.7">量学原版：大阴实顶 + 四维对比 + 个股解读</div>
        </div>
        
        <!-- 信号说明区（顶部，只放一次） -->
        <div class="signal-guide">
            <h2>四维看盘法说明</h2>
            
            <div class="signal-item">
                <h3>起点：大阴实顶</h3>
                <p><strong>定义：</strong>从今天往左找最近的中大阴线，其实体顶部就是"大阴实顶"</p>
                <p><strong>原理：</strong>大阴实顶是多空双方上次休战的"警戒点"，下次争夺的"起动点"</p>
                <p><strong>为什么从这里开始？</strong>量学认为，最近的大阴线反映了最近一次多空力量的对比，从这里开始看最有意义</p>
                <p class="source">来源：股海明灯（量学官网）</p>
            </div>
            
            <div class="signal-item">
                <h3>① 从右向左看：比较价柱的高低阴阳</h3>
                <p><strong>视线：</strong>从今天往左，往大阴实顶方向看</p>
                <p><strong>对比内容：</strong></p>
                <p>  - 高低：价格在大阴实顶上方还是下方？</p>
                <p>  - 阴阳：从大阴实顶到今天，阳线多还是阴线多？</p>
                <p><strong>目的：</strong>看当前价格的位置和多空力量对比</p>
            </div>
            
            <div class="signal-item">
                <h3>② 从上往下看：比较量价的真假大小</h3>
                <p><strong>视线：</strong>从大阴实顶的价柱往下看量柱</p>
                <p><strong>对比内容：</strong></p>
                <p>  - 大小：大阴实顶的量是大还是小？</p>
                <p>  - 真假：价跌量缩是真跌？价跌量增是假跌？</p>
                <p><strong>目的：</strong>看大阴实顶那天的量价结构</p>
            </div>
            
            <div class="signal-item">
                <h3>③ 从左往右看：比较量柱的远近多少</h3>
                <p><strong>视线：</strong>从大阴实顶的量柱往右看，看到今天的量柱</p>
                <p><strong>对比内容：</strong></p>
                <p>  - 远近：大阴实顶离今天多远？</p>
                <p>  - 多少：今天的量 vs 大阴实顶的量，是多还是少？</p>
                <p><strong>目的：</strong>看大阴实顶的量对今天的影响力</p>
            </div>
            
            <div class="signal-item">
                <h3>④ 从下往上看：比较量价的长短伸缩</h3>
                <p><strong>视线：</strong>从今天的量柱往上看价柱</p>
                <p><strong>对比内容：</strong></p>
                <p>  - 长短：量柱是长还是短？价柱是长还是短？</p>
                <p>  - 伸缩：实体是长还是短？振幅是大还是小？</p>
                <p><strong>目的：</strong>看今天的量价建构</p>
            </div>
            
            <div class="signal-item">
                <h3>个股解读</h3>
                <p><strong>原则：</strong>客观描述，不做主观判断</p>
                <p><strong>内容：</strong>用四维看盘法客观描述当前的状态</p>
            </div>
            
            <div class="signal-item">
                <h3>核心思想</h3>
                <p><strong>本质：</strong>找阴阳失衡与平衡的区别</p>
                <p><strong>原则：</strong>就近对比原则（找最近的，不是随便找的）</p>
                <p><strong>方法：</strong>回形针看盘法（由此及彼、由里向外，逐层解剖）</p>
                <p class="source">来源：股海明灯《四维循环看盘》学习心得</p>
            </div>
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
    print("四维循环看盘报告 - HTML版（量学原版：大阴实顶+四维对比+个股解读）")
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
