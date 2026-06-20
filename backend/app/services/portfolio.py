"""
组合管理服务
根据交易信号自动更新持仓，维护组合状态，跟踪每日净值
"""
from datetime import date, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.portfolio import Portfolio, PortfolioPosition, PortfolioNAV
from app.models.stock import Stock
from app.models.trade_signal import TradeSignal
from app.models.daily_price import DailyPrice
from app.core.constants import SignalType

INITIAL_CAPITAL = 1000000.0


def get_or_create_portfolio(db: Session, name: str = "融衔一号") -> Portfolio:
    """获取或创建默认组合"""
    portfolio = db.query(Portfolio).filter(Portfolio.name == name).first()
    if not portfolio:
        portfolio = Portfolio(
            name=name,
            strategy_type="fundamental_medium_long",
            target_position=60.0,
            cash_ratio=40.0,
        )
        db.add(portfolio)
        db.commit()
        db.refresh(portfolio)
    return portfolio


def update_positions_from_signals(db: Session, signal_date: date) -> dict:
    """根据当天的 BUY/SELL 信号更新组合持仓
    - BUY/ADD 信号：加入或加仓
    - SELL/REDUCE 信号：减仓或清仓
    - 同时更新所有持仓的现价
    Returns: {"added": int, "removed": int, "updated": int}
    """
    portfolio = get_or_create_portfolio(db)
    signals = db.query(TradeSignal).filter(TradeSignal.signal_date == signal_date).all()

    added = 0
    removed = 0

    for sig in signals:
        stock = db.query(Stock).filter(Stock.id == sig.stock_id).first()
        if not stock:
            continue

        existing = db.query(PortfolioPosition).filter(
            PortfolioPosition.portfolio_id == portfolio.id,
            PortfolioPosition.stock_id == sig.stock_id,
        ).first()

        if sig.signal_type in (SignalType.BUY, SignalType.ADD):
            if not existing:
                # 新建持仓
                latest_price = (
                    db.query(DailyPrice)
                    .filter(DailyPrice.stock_id == sig.stock_id)
                    .order_by(DailyPrice.trade_date.desc())
                    .first()
                )
                cost = latest_price.close if latest_price else (sig.entry_price or 0)
                pos = PortfolioPosition(
                    portfolio_id=portfolio.id,
                    stock_id=sig.stock_id,
                    position_ratio=sig.suggested_position or 5.0,
                    cost_price=cost,
                    current_price=cost,
                    unrealized_return=0.0,
                )
                db.add(pos)
                added += 1
            else:
                # 加仓：更新持仓比例和成本价
                old_ratio = existing.position_ratio or 5.0
                add_ratio = sig.suggested_position or 3.0
                new_ratio = min(old_ratio + add_ratio, 15.0)  # 单只上限 15%

                latest_price = (
                    db.query(DailyPrice)
                    .filter(DailyPrice.stock_id == sig.stock_id)
                    .order_by(DailyPrice.trade_date.desc())
                    .first()
                )
                new_cost = latest_price.close if latest_price else (sig.entry_price or existing.cost_price or 0)

                # 成本价更新：用金额加权平均
                # 旧持仓金额 = ratio × cost_price（比例代表相对金额）
                # 新增持仓金额 = add_ratio × new_cost
                if old_ratio > 0 and existing.cost_price and new_cost > 0:
                    old_value = existing.cost_price * old_ratio
                    new_value = new_cost * add_ratio
                    existing.cost_price = round((old_value + new_value) / new_ratio, 2)

                existing.position_ratio = new_ratio

        elif sig.signal_type in (SignalType.SELL, SignalType.REDUCE):
            if existing:
                if sig.signal_type == SignalType.SELL:
                    db.delete(existing)
                    removed += 1
                else:
                    # 减仓：降低持仓比例
                    existing.position_ratio = max(
                        (existing.position_ratio or 5.0) - 3.0,
                        0.0
                    )
                    if existing.position_ratio <= 0:
                        db.delete(existing)
                        removed += 1

    db.commit()

    # 更新所有持仓的现价和收益率
    updated = update_portfolio_prices(db, portfolio.id)

    return {"added": added, "removed": removed, "updated": updated}


def update_portfolio_prices(db: Session, portfolio_id: int) -> int:
    """更新组合内所有持仓的现价和未实现收益率"""
    positions = db.query(PortfolioPosition).filter(
        PortfolioPosition.portfolio_id == portfolio_id
    ).all()

    updated = 0
    for pos in positions:
        latest = (
            db.query(DailyPrice)
            .filter(DailyPrice.stock_id == pos.stock_id)
            .order_by(DailyPrice.trade_date.desc())
            .first()
        )
        if latest and latest.close:
            pos.current_price = latest.close
            if pos.cost_price and pos.cost_price > 0:
                pos.unrealized_return = round(
                    (latest.close - pos.cost_price) / pos.cost_price * 100, 2
                )
            updated += 1

    db.commit()
    return updated


def get_portfolio_summary(db: Session) -> dict:
    """获取组合概览"""
    portfolio = get_or_create_portfolio(db)
    positions = db.query(PortfolioPosition).filter(
        PortfolioPosition.portfolio_id == portfolio.id
    ).all()

    total_return = 0.0
    position_count = 0
    position_list = []

    for pos in positions:
        stock = db.query(Stock).filter(Stock.id == pos.stock_id).first()
        if pos.cost_price and pos.current_price and pos.cost_price > 0:
            ret = round((pos.current_price - pos.cost_price) / pos.cost_price * 100, 2)
            total_return += ret
            position_count += 1
        else:
            ret = 0.0

        position_list.append({
            "symbol": stock.symbol if stock else "",
            "name": stock.name if stock else "",
            "market": stock.market if stock else "",
            "position_ratio": pos.position_ratio,
            "cost_price": pos.cost_price,
            "current_price": pos.current_price,
            "unrealized_return": ret,
        })

    avg_return = round(total_return / position_count, 2) if position_count > 0 else 0

    return {
        "name": portfolio.name,
        "strategy_type": portfolio.strategy_type,
        "target_position": portfolio.target_position,
        "cash_ratio": portfolio.cash_ratio,
        "position_count": position_count,
        "avg_return": avg_return,
        "positions": position_list,
    }


def record_daily_nav(db: Session, nav_date: date) -> dict:
    """记录当日组合净值
    计算逻辑：
    - 用持仓加权收益率推算当日净值
    - 同时计算等权基准净值
    Returns: {"nav": float, "daily_return": float, "cumulative_return": float}
    """
    portfolio = get_or_create_portfolio(db)
    positions = db.query(PortfolioPosition).filter(
        PortfolioPosition.portfolio_id == portfolio.id
    ).all()

    # 获取前一日净值
    prev_nav = db.query(PortfolioNAV).filter(
        PortfolioNAV.portfolio_id == portfolio.id
    ).order_by(PortfolioNAV.nav_date.desc()).first()

    prev_total = prev_nav.total_value if prev_nav else INITIAL_CAPITAL

    # 计算当日加权收益率
    # 每只股票的日收益率 × 持仓比例
    weighted_return = 0.0
    total_ratio = 0.0
    position_value = 0.0

    for pos in positions:
        # 获取今日价格
        today_price = db.query(DailyPrice).filter(
            DailyPrice.stock_id == pos.stock_id,
            DailyPrice.trade_date <= nav_date,
        ).order_by(DailyPrice.trade_date.desc()).first()

        # 获取昨日价格
        yesterday_price = db.query(DailyPrice).filter(
            DailyPrice.stock_id == pos.stock_id,
            DailyPrice.trade_date < nav_date,
        ).order_by(DailyPrice.trade_date.desc()).first()

        if today_price and yesterday_price and yesterday_price.close and yesterday_price.close > 0:
            daily_ret = (today_price.close - yesterday_price.close) / yesterday_price.close
            ratio = (pos.position_ratio or 0) / 100
            weighted_return += daily_ret * ratio
            total_ratio += ratio

            # 更新持仓现价
            pos.current_price = today_price.close
            if pos.cost_price and pos.cost_price > 0:
                pos.unrealized_return = round(
                    (today_price.close - pos.cost_price) / pos.cost_price * 100, 2
                )

    # 计算当日净值
    cash_ratio = (portfolio.cash_ratio or 0) / 100
    # 现金部分收益率为 0，所以总收益率 = 持仓加权收益率 × (1 - 现金比例)
    portfolio_return = weighted_return * (1 - cash_ratio)
    current_total = prev_total * (1 + portfolio_return)

    # 计算累计收益率
    cumulative_return = (current_total - INITIAL_CAPITAL) / INITIAL_CAPITAL

    # 计算基准净值（等权持有所有 A 股）
    benchmark_value = None
    benchmark_return = None
    if prev_nav and prev_nav.benchmark_value:
        # 简化基准：用所有 ACTIVE 股票的平均日收益率
        all_stocks = db.query(Stock).filter(Stock.market == "A_SHARE", Stock.status == "ACTIVE").all()
        bench_returns = []
        for s in all_stocks[:50]:  # 取前 50 只避免太慢
            tp = db.query(DailyPrice).filter(
                DailyPrice.stock_id == s.id, DailyPrice.trade_date <= nav_date
            ).order_by(DailyPrice.trade_date.desc()).first()
            yp = db.query(DailyPrice).filter(
                DailyPrice.stock_id == s.id, DailyPrice.trade_date < nav_date
            ).order_by(DailyPrice.trade_date.desc()).first()
            if tp and yp and yp.close and yp.close > 0:
                bench_returns.append((tp.close - yp.close) / yp.close)
        if bench_returns:
            avg_bench_ret = sum(bench_returns) / len(bench_returns)
            benchmark_value = prev_nav.benchmark_value * (1 + avg_bench_ret)
            benchmark_return = avg_bench_ret

    # 存储净值记录
    existing = db.query(PortfolioNAV).filter(
        PortfolioNAV.portfolio_id == portfolio.id,
        PortfolioNAV.nav_date == nav_date,
    ).first()

    if existing:
        existing.total_value = round(current_total, 2)
        existing.position_value = round(current_total * (1 - cash_ratio), 2)
        existing.cash_value = round(current_total * cash_ratio, 2)
        existing.daily_return = round(portfolio_return * 100, 4)
        existing.cumulative_return = round(cumulative_return * 100, 4)
        existing.benchmark_value = round(benchmark_value, 2) if benchmark_value else None
        existing.benchmark_return = round(benchmark_return * 100, 4) if benchmark_return else None
    else:
        nav = PortfolioNAV(
            portfolio_id=portfolio.id,
            nav_date=nav_date,
            total_value=round(current_total, 2),
            position_value=round(current_total * (1 - cash_ratio), 2),
            cash_value=round(current_total * cash_ratio, 2),
            daily_return=round(portfolio_return * 100, 4),
            cumulative_return=round(cumulative_return * 100, 4),
            benchmark_value=round(benchmark_value, 2) if benchmark_value else None,
            benchmark_return=round(benchmark_return * 100, 4) if benchmark_return else None,
        )
        db.add(nav)

    db.commit()

    return {
        "nav": round(current_total, 2),
        "daily_return": round(portfolio_return * 100, 4),
        "cumulative_return": round(cumulative_return * 100, 4),
    }


def compute_portfolio_metrics(db: Session) -> dict:
    """从 NAV 历史计算 Sharpe/最大回撤/月度收益
    Returns: {"sharpe": float, "max_drawdown": float, "monthly_returns": list}
    """
    portfolio = get_or_create_portfolio(db)
    nav_records = db.query(PortfolioNAV).filter(
        PortfolioNAV.portfolio_id == portfolio.id
    ).order_by(PortfolioNAV.nav_date).all()

    if len(nav_records) < 2:
        return {"sharpe": 0, "max_drawdown": 0, "monthly_returns": []}

    # 日收益率序列
    daily_returns = [r.daily_return / 100 for r in nav_records if r.daily_return is not None]

    # Sharpe 比率（年化，无风险利率假设 0）
    if daily_returns and len(daily_returns) > 1:
        import numpy as np
        mean_ret = np.mean(daily_returns)
        std_ret = np.std(daily_returns)
        sharpe = round((mean_ret * 252) / (std_ret * (252 ** 0.5)), 2) if std_ret > 0 else 0
    else:
        sharpe = 0

    # 最大回撤
    values = [r.total_value for r in nav_records]
    peak = values[0]
    max_dd = 0
    for v in values:
        if v > peak:
            peak = v
        dd = (peak - v) / peak
        if dd > max_dd:
            max_dd = dd
    max_drawdown = round(max_dd * 100, 2)

    # 月度收益
    monthly_returns = []
    current_month = None
    month_start_value = None
    month_start_bench = None

    for nav in nav_records:
        month_key = (nav.nav_date.year, nav.nav_date.month)
        if month_key != current_month:
            # 上一个月的结束
            if current_month is not None and month_start_value is not None:
                month_ret = round((prev_value - month_start_value) / month_start_value * 100, 2)
                bench_ret = round((prev_bench - month_start_bench) / month_start_bench * 100, 2) if month_start_bench and prev_bench else 0
                monthly_returns.append({
                    "month": f"{current_month[0]}-{current_month[1]:02d}",
                    "strategy_return": month_ret,
                    "benchmark_return": bench_ret,
                    "excess_return": round(month_ret - bench_ret, 2),
                })
            current_month = month_key
            month_start_value = nav.total_value
            month_start_bench = nav.benchmark_value

        prev_value = nav.total_value
        prev_bench = nav.benchmark_value

    # 最后一个月
    if current_month is not None and month_start_value is not None:
        month_ret = round((prev_value - month_start_value) / month_start_value * 100, 2)
        bench_ret = round((prev_bench - month_start_bench) / month_start_bench * 100, 2) if month_start_bench and prev_bench else 0
        monthly_returns.append({
            "month": f"{current_month[0]}-{current_month[1]:02d}",
            "strategy_return": month_ret,
            "benchmark_return": bench_ret,
            "excess_return": round(month_ret - bench_ret, 2),
        })

    return {
        "sharpe": sharpe,
        "max_drawdown": max_drawdown,
        "monthly_returns": monthly_returns,
    }
