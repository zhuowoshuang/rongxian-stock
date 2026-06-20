from sqlalchemy import Column, Integer, String, Date, Float, ForeignKey, DateTime, func, UniqueConstraint, Index
from app.db.base import Base


class Portfolio(Base):
    """投资组合表"""
    __tablename__ = "portfolios"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, comment="组合名称")
    strategy_type = Column(String(50), comment="策略类型")
    target_position = Column(Float, comment="目标仓位百分比")
    cash_ratio = Column(Float, comment="现金比例")
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("name", name="uq_portfolio_name"),
    )


class PortfolioPosition(Base):
    """组合持仓表"""
    __tablename__ = "portfolio_positions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    portfolio_id = Column(Integer, ForeignKey("portfolios.id"), nullable=False, index=True)
    stock_id = Column(Integer, ForeignKey("stocks.id"), nullable=False, index=True)
    position_ratio = Column(Float, comment="持仓比例")
    cost_price = Column(Float, comment="成本价")
    current_price = Column(Float, comment="现价")
    unrealized_return = Column(Float, comment="未实现收益率")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class PortfolioNAV(Base):
    """组合每日净值记录 - 用于计算 Sharpe/回撤/月度收益"""
    __tablename__ = "portfolio_nav"

    id = Column(Integer, primary_key=True, autoincrement=True)
    portfolio_id = Column(Integer, ForeignKey("portfolios.id"), nullable=False, index=True)
    nav_date = Column(Date, nullable=False, comment="净值日期")
    total_value = Column(Float, nullable=False, comment="组合总市值(元)")
    cash_value = Column(Float, comment="现金(元)")
    position_value = Column(Float, comment="持仓市值(元)")
    daily_return = Column(Float, comment="日收益率")
    cumulative_return = Column(Float, comment="累计收益率")
    benchmark_value = Column(Float, comment="基准市值(元)")
    benchmark_return = Column(Float, comment="基准日收益率")
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("idx_nav_portfolio_date", "portfolio_id", "nav_date", unique=True),
    )
