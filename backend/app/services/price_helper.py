"""
价格查询辅助函数 - 批量获取最新价格，避免 N+1 查询
"""
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.daily_price import DailyPrice


def get_latest_prices(db: Session, stock_ids: list[int]) -> dict[int, DailyPrice]:
    """批量获取每只股票的最新价格行
    Returns: {stock_id: DailyPrice}
    """
    if not stock_ids:
        return {}

    # 子查询：每只股票的最大 trade_date
    subq = (
        db.query(
            DailyPrice.stock_id,
            func.max(DailyPrice.trade_date).label("max_date"),
        )
        .filter(DailyPrice.stock_id.in_(stock_ids))
        .group_by(DailyPrice.stock_id)
        .subquery()
    )

    # 主查询：JOIN 取完整行
    rows = (
        db.query(DailyPrice)
        .join(
            subq,
            (DailyPrice.stock_id == subq.c.stock_id)
            & (DailyPrice.trade_date == subq.c.max_date),
        )
        .all()
    )

    return {r.stock_id: r for r in rows}


def get_latest_price(db: Session, stock_id: int) -> Optional[DailyPrice]:
    """获取单只股票的最新价格（便捷方法）"""
    result = get_latest_prices(db, [stock_id])
    return result.get(stock_id)
