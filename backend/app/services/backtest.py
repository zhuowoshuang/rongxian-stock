"""
回测服务
基于数据库中的真实历史行情数据模拟策略表现
"""
import numpy as np
from datetime import date, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import and_

from app.models.stock import Stock
from app.models.daily_price import DailyPrice
from app.models.stock_score import StockScore
from app.models.financial_metric import FinancialMetric


# 策略配置：选股条件
STRATEGY_CONFIG = {
    "fundamental_medium_long": {
        "name": "基本面中长期",
        "filter": lambda sc: sc.total_score >= 65,
        "top_n": 10,
        "min_score": 65,
    },
    "value_investing": {
        "name": "价值投资",
        "filter": lambda sc: sc.valuation_score >= 15 and sc.quality_score >= 20,
        "top_n": 8,
        "min_score": 60,
    },
    "growth_investing": {
        "name": "成长投资",
        "filter": lambda sc: sc.growth_score >= 15 and sc.total_score >= 60,
        "top_n": 8,
        "min_score": 60,
    },
    "momentum": {
        "name": "趋势动量",
        "filter": lambda sc: sc.trend_score >= 15 and sc.total_score >= 60,
        "top_n": 10,
        "min_score": 60,
    },
    "quality_first": {
        "name": "质量优先",
        "filter": lambda sc: sc.quality_score >= 24 and sc.risk_score >= 7,
        "top_n": 6,
        "min_score": 65,
    },
}


def run_backtest(
    db: Session,
    strategy: str,
    market: str,
    start_date: str,
    end_date: str,
    rebalance: str = "monthly",
    initial_capital: float = 1000000.0,
) -> dict:
    """
    基于真实历史数据运行回测
    支持策略: fundamental_medium_long / value_investing / growth_investing / momentum / quality_first
    """
    strategy_cfg = STRATEGY_CONFIG.get(strategy, STRATEGY_CONFIG["fundamental_medium_long"])
    stocks = db.query(Stock).filter(Stock.market == market, Stock.status == "ACTIVE").all()
    if not stocks:
        return {"error": "未找到该市场的股票"}

    stock_ids = [s.id for s in stocks]
    stock_map = {s.id: s for s in stocks}

    # 获取所有交易日
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)

    prices = (
        db.query(DailyPrice)
        .filter(
            DailyPrice.stock_id.in_(stock_ids),
            DailyPrice.trade_date >= start,
            DailyPrice.trade_date <= end,
        )
        .order_by(DailyPrice.trade_date)
        .all()
    )

    if not prices:
        return {"error": "该时间段内无历史数据，请先运行 seed 脚本导入数据"}

    # 按日期分组
    date_map: dict[date, dict[int, DailyPrice]] = {}
    for p in prices:
        if p.trade_date not in date_map:
            date_map[p.trade_date] = {}
        date_map[p.trade_date][p.stock_id] = p

    trade_dates = sorted(date_map.keys())
    if len(trade_dates) < 5:
        return {"error": f"历史数据不足（仅 {len(trade_dates)} 个交易日），无法回测"}

    # 获取所有历史评分（用于 point-in-time 查询，避免前视偏差）
    all_scores = (
        db.query(StockScore)
        .filter(StockScore.stock_id.in_(stock_ids))
        .order_by(StockScore.stock_id, StockScore.score_date)
        .all()
    )
    # 按 stock_id 分组，每组按日期排序
    scores_by_stock: dict[int, list] = {}
    for sc in all_scores:
        scores_by_stock.setdefault(sc.stock_id, []).append(sc)

    def get_score_at_date(sid: int, as_of: date) -> float:
        """获取某只股票在 as_of 日期或之前最近的评分"""
        sc_list = scores_by_stock.get(sid, [])
        best = None
        for sc in sc_list:
            if sc.score_date <= as_of:
                best = sc
            else:
                break
        return best.total_score if best else 50.0

    # 确定调仓频率
    if rebalance == "quarterly":
        rebalance_days = 63  # ~3 months
    else:
        rebalance_days = 21  # ~1 month

    # 初始化回测
    equity = initial_capital
    cash = initial_capital
    positions: dict[int, dict] = {}  # stock_id -> {shares, cost_price}
    equity_curve = []
    monthly_returns = []
    trade_log = []

    # 基准：等权日再平衡（每日等权持有所有股票，每天调仓）
    # 首日市值
    benchmark_nav = initial_capital
    benchmark_prev_prices: dict[int, float] = {}

    last_rebalance_idx = 0
    prev_equity = initial_capital
    prev_benchmark = initial_capital

    for i, td in enumerate(trade_dates):
        day_prices = date_map.get(td, {})

        # 计算当前持仓市值
        portfolio_value = cash
        for sid, pos in positions.items():
            if sid in day_prices:
                portfolio_value += pos["shares"] * day_prices[sid].close
            else:
                portfolio_value += pos["shares"] * pos["cost_price"]

        # 基准：等权日再平衡
        if i == 0:
            benchmark_prev_prices = {sid: day_prices[sid].close for sid in stock_ids if sid in day_prices}
        else:
            daily_returns = []
            for sid in stock_ids:
                if sid in day_prices and sid in benchmark_prev_prices and benchmark_prev_prices[sid] > 0:
                    daily_returns.append(day_prices[sid].close / benchmark_prev_prices[sid] - 1)
            if daily_returns:
                benchmark_nav *= (1 + sum(daily_returns) / len(daily_returns))
            benchmark_prev_prices = {sid: day_prices[sid].close for sid in stock_ids if sid in day_prices}
        benchmark_value = benchmark_nav

        equity_curve.append({
            "date": td.isoformat(),
            "equity": round(portfolio_value, 2),
            "benchmark": round(benchmark_value, 2),
        })

        # 判断是否需要调仓
        if i - last_rebalance_idx >= rebalance_days or i == 0:
            last_rebalance_idx = i

            # 按策略条件选股（使用调仓日当天或之前最近的评分，避免前视偏差）
            scored = []
            for sid in stock_ids:
                if sid not in day_prices:
                    continue
                sc = get_score_at_date(sid, td)
                scored.append((sid, sc))

            # 获取完整评分对象用于策略过滤
            target_stocks = []
            for sid, total_sc in scored:
                # 获取最近的 StockScore 对象
                score_obj = None
                for sc in scores_by_stock.get(sid, []):
                    if sc.score_date <= td:
                        score_obj = sc
                    else:
                        break
                if score_obj and strategy_cfg["filter"](score_obj):
                    target_stocks.append((sid, total_sc))

            target_stocks.sort(key=lambda x: x[1], reverse=True)
            target_stocks = target_stocks[:strategy_cfg["top_n"]]

            if not target_stocks:
                # 降级：取总分最高的几只
                scored.sort(key=lambda x: x[1], reverse=True)
                target_stocks = scored[:5]

            # 卖出不在目标列表中的持仓
            to_sell = [sid for sid in positions if sid not in {s[0] for s in target_stocks}]
            for sid in to_sell:
                if sid in day_prices:
                    sell_price = day_prices[sid].close
                    shares = positions[sid]["shares"]
                    proceeds = shares * sell_price
                    cost = shares * positions[sid]["cost_price"]
                    pnl = proceeds - cost
                    cash += proceeds
                    trade_log.append({
                        "date": td.isoformat(),
                        "symbol": stock_map[sid].symbol,
                        "name": stock_map[sid].name,
                        "action": "SELL",
                        "price": round(sell_price, 2),
                        "shares": shares,
                        "pnl": round(pnl, 2),
                    })
                    del positions[sid]

            # 计算可用资金分配
            total_value = cash + sum(
                pos["shares"] * day_prices[sid].close
                for sid, pos in positions.items() if sid in day_prices
            )
            target_value_per = total_value / max(len(target_stocks), 1)

            # 买入/调仓
            for sid, sc in target_stocks:
                if sid not in day_prices:
                    continue
                price = day_prices[sid].close
                current_value = positions[sid]["shares"] * price if sid in positions else 0
                diff = target_value_per - current_value

                if diff > price * 10:  # 需要买入
                    shares_to_buy = int(diff / price / 100) * 100  # 整手
                    if shares_to_buy > 0 and cash >= shares_to_buy * price:
                        cost = shares_to_buy * price
                        cash -= cost
                        if sid in positions:
                            old = positions[sid]
                            total_shares = old["shares"] + shares_to_buy
                            avg_cost = (old["shares"] * old["cost_price"] + cost) / total_shares
                            positions[sid] = {"shares": total_shares, "cost_price": avg_cost}
                        else:
                            positions[sid] = {"shares": shares_to_buy, "cost_price": price}
                        trade_log.append({
                            "date": td.isoformat(),
                            "symbol": stock_map[sid].symbol,
                            "name": stock_map[sid].name,
                            "action": "BUY",
                            "price": round(price, 2),
                            "shares": shares_to_buy,
                            "pnl": 0,
                        })

        # 记录月度收益
        if i > 0:
            daily_ret = (portfolio_value - prev_equity) / prev_equity if prev_equity > 0 else 0
            daily_bench_ret = (benchmark_value - prev_benchmark) / prev_benchmark if prev_benchmark > 0 else 0
            month_label = td.strftime("%Y-%m")
            if not monthly_returns or monthly_returns[-1]["month"] != month_label:
                monthly_returns.append({
                    "month": month_label,
                    "strategy_return": round(daily_ret * 100, 2),
                    "benchmark_return": round(daily_bench_ret * 100, 2),
                    "excess_return": round((daily_ret - daily_bench_ret) * 100, 2),
                })
            else:
                sr = monthly_returns[-1]["strategy_return"]
                br = monthly_returns[-1]["benchmark_return"]
                monthly_returns[-1]["strategy_return"] = round((1 + sr / 100) * (1 + daily_ret) * 100 - 100, 2)
                monthly_returns[-1]["benchmark_return"] = round((1 + br / 100) * (1 + daily_bench_ret) * 100 - 100, 2)
                monthly_returns[-1]["excess_return"] = round(
                    monthly_returns[-1]["strategy_return"] - monthly_returns[-1]["benchmark_return"], 2
                )

        prev_equity = portfolio_value
        prev_benchmark = benchmark_value

    # 最终清算
    final_date = trade_dates[-1]
    final_prices = date_map.get(final_date, {})
    final_equity = cash
    for sid, pos in positions.items():
        if sid in final_prices:
            final_equity += pos["shares"] * final_prices[sid].close
        else:
            final_equity += pos["shares"] * pos["cost_price"]

    # 计算指标
    total_return = (final_equity - initial_capital) / initial_capital
    n_days = (trade_dates[-1] - trade_dates[0]).days
    n_years = max(n_days / 365, 0.1)
    annual_return = (1 + total_return) ** (1 / n_years) - 1

    # 基准收益
    benchmark_final = equity_curve[-1]["benchmark"] if equity_curve else initial_capital
    benchmark_total = (benchmark_final - initial_capital) / initial_capital

    # 最大回撤
    peak = initial_capital
    max_dd = 0
    for point in equity_curve:
        if point["equity"] > peak:
            peak = point["equity"]
        dd = (peak - point["equity"]) / peak
        if dd > max_dd:
            max_dd = dd

    # 夏普比率（日收益率）
    daily_returns = []
    for i in range(1, len(equity_curve)):
        prev = equity_curve[i - 1]["equity"]
        curr = equity_curve[i]["equity"]
        if prev > 0:
            daily_returns.append((curr - prev) / prev)
    if daily_returns and np.std(daily_returns) > 0:
        sharpe = (np.mean(daily_returns) * 252) / (np.std(daily_returns) * np.sqrt(252))
    else:
        sharpe = 0

    # 胜率
    win_trades = len([t for t in trade_log if t.get("pnl", 0) > 0])
    sell_trades = [t for t in trade_log if t["action"] == "SELL"]
    win_rate = win_trades / len(sell_trades) if sell_trades else 0

    return {
        "strategy": strategy,
        "strategy_name": strategy_cfg["name"],
        "total_return": round(total_return * 100, 2),
        "annual_return": round(annual_return * 100, 2),
        "benchmark_return": round(benchmark_total * 100, 2),
        "excess_return": round((total_return - benchmark_total) * 100, 2),
        "max_drawdown": round(max_dd * 100, 2),
        "sharpe_ratio": round(sharpe, 2),
        "win_rate": round(win_rate * 100, 2),
        "total_trades": len(trade_log),
        "equity_curve": equity_curve,
        "monthly_returns": monthly_returns,
        "trade_log": trade_log,
    }
