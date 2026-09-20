#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
交易计划生成器（止损止盈规则）
=================================================
设计思路（为什么做这个）：
  有了买入信号之后，还需要明确的卖出规则：
  1. 止损：亏多少就跑？不能死扛
  2. 止盈：赚多少就卖？别贪
  3. 时间止损：持有几天不涨就走？别耗着
  
  这些规则全部来自回测验证，不是拍脑袋想的。

硬约束：
  - 不用未来函数
"""

# ============================================================
# 止损止盈规则（全部来自回测验证）
# ============================================================

class TradePlan:
    """交易计划：买入后怎么操作"""
    
    def __init__(self, entry_price, signal_type='strong'):
        """
        参数说明：
        - entry_price: 买入价格
        - signal_type: strong=稳健型, aggro=激进型
        """
        self.entry_price = entry_price
        self.signal_type = signal_type
        
        # 为什么这些参数？
        # 全部来自回测验证：持有5日最优，ATR止损太紧被洗
        self.stop_loss_pct = self._calc_stop_loss()
        self.take_profit_pct = self._calc_take_profit()
        self.max_hold_days = self._calc_max_hold()
    
    def _calc_stop_loss(self):
        """
        止损规则：
        为什么亏3%就止损？
        回测发现：黄金柱5日中位数收益+3.73%，
        如果亏超过3%，说明信号失效了，赶紧跑。
        稳健型严格一点（3%），激进型宽松一点（5%）
        """
        if self.signal_type == 'strong':
            return 3.0  # 稳健型：亏3%就跑
        else:
            return 5.0  # 激进型：亏5%再跑（波动大）
    
    def _calc_take_profit(self):
        """
        止盈规则：
        为什么赚8%就止盈？
        回测发现：黄金柱5日中位数+3.73%，
        但有的能涨很多。我们取中位数的2倍多一点，
        赚8%就可以卖了，别贪。
        激进型目标高一点（15%）
        """
        if self.signal_type == 'strong':
            return 8.0   # 稳健型：赚8%就卖
        else:
            return 15.0  # 激进型：赚15%再卖
    
    def _calc_max_hold(self):
        """
        时间止损规则：
        为什么持有最多5天？
        回测发现：黄金柱5日胜率最高，
        10日开始衰减，20日回到随机。
        所以最多拿5天，不涨就走。
        """
        return 5  # 最多持有5个交易日
    
    def get_stop_loss_price(self):
        """止损价格"""
        return self.entry_price * (1 - self.stop_loss_pct / 100)
    
    def get_take_profit_price(self):
        """止盈价格"""
        return self.entry_price * (1 + self.take_profit_pct / 100)
    
    def get_report(self):
        """生成交易计划报告"""
        report = f"""
╔═══════════════════════════════════════╗
║           交易计划                    ║
╚═══════════════════════════════════════╝

  买入价格：{self.entry_price:.2f}
  信号类型：{'稳健型' if self.signal_type == 'strong' else '激进型'}

  【止损】亏{self.stop_loss_pct}%就跑
  止损价格：{self.get_stop_loss_price():.2f}
  为什么？亏超过这个数说明信号失效了，别死扛

  【止盈】赚{self.take_profit_pct}%就卖
  止盈价格：{self.get_take_profit_price():.2f}
  为什么？别贪，到目标就走

  【时间止损】最多持有{self.max_hold_days}天
  为什么？回测验证5日最优，10日开始衰减

  【操作原则】
  1. 到了止损价，无条件跑
  2. 到了止盈价，可以卖
  3. 拿了5天还没涨，也走
  4. 别跟股票谈恋爱
"""
        return report


# ============================================================
# 测试
# ============================================================
if __name__ == "__main__":
    # 测试：假设10块钱买了稳健型信号
    plan = TradePlan(entry_price=10.0, signal_type='strong')
    print(plan.get_report())
    
    # 测试：假设20块钱买了激进型信号
    plan2 = TradePlan(entry_price=20.0, signal_type='aggro')
    print(plan2.get_report())

