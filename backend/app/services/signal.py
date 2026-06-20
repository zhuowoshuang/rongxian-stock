"""
信号生成服务
根据评分结果生成交易信号
"""
from typing import Optional
from datetime import date
from sqlalchemy.orm import Session

from app.models.stock import Stock
from app.models.stock_score import StockScore
from app.models.daily_price import DailyPrice
from app.models.technical_indicator import TechnicalIndicator
from app.models.trade_signal import TradeSignal
from app.core.constants import SignalType, SignalStatus


def determine_signal_type(score: StockScore) -> tuple[str, int, str]:
    """
    根据评分确定信号类型、强度和逻辑说明
    信号类型与 get_rating() 的阈值保持一致，避免不一致
    Returns: (signal_type, signal_strength, logic_text)
    """
    from app.services.scoring import get_rating
    signal_type = get_rating(score.total_score)

    # 根据信号类型确定强度和逻辑
    if signal_type == SignalType.BUY:
        # 强度由子分数决定：子分数越高，信号越强
        sub_score_count = sum([
            score.quality_score >= 24,
            score.valuation_score >= 14,
            score.trend_score >= 14,
            score.risk_score >= 7,
        ])
        strength = min(5, 2 + sub_score_count)
        reasons = []
        if score.quality_score >= 24:
            reasons.append("基本面优秀")
        if score.valuation_score >= 14:
            reasons.append("估值合理")
        if score.trend_score >= 14:
            reasons.append("趋势确认")
        logic = "，".join(reasons) if reasons else "综合评分优秀"
        return SignalType.BUY, strength, f"{logic}，建议买入"

    if signal_type == SignalType.ADD:
        sub_score_count = sum([
            score.trend_score >= 12,
            score.risk_score >= 7,
            score.quality_score >= 20,
        ])
        strength = min(4, 1 + sub_score_count)
        return SignalType.ADD, strength, "基本面良好，趋势向好，可适当加仓"

    if signal_type == SignalType.WATCH:
        strength = min(3, int((score.total_score - 60) / 5) + 1)
        reasons = []
        if score.quality_score >= 20:
            reasons.append("基本面良好")
        if score.trend_score < 12:
            reasons.append("趋势待确认")
        if score.valuation_score < 14:
            reasons.append("估值偏高")
        logic = "，".join(reasons) if reasons else "综合评分中等"
        return SignalType.WATCH, strength, f"{logic}，建议观望"

    if signal_type == SignalType.REDUCE:
        reasons = []
        if score.valuation_score < 10:
            reasons.append("估值过高")
        if score.trend_score < 10:
            reasons.append("趋势转弱")
        if score.risk_score < 5:
            reasons.append("风险升高")
        logic = "，".join(reasons) if reasons else "综合评分偏低"
        return SignalType.REDUCE, 2, f"{logic}，建议减仓"

    # SELL: 基本面恶化、评分很低
    return SignalType.SELL, 1, "基本面恶化或评分极低，建议卖出"


def calculate_position(signal_type: str, signal_strength: int) -> float:
    """根据信号类型和强度计算建议仓位"""
    position_map = {
        SignalType.BUY: {5: 8, 4: 6, 3: 5},
        SignalType.ADD: {4: 5, 3: 4, 2: 3},
        SignalType.WATCH: {3: 0, 2: 0, 1: 0},
        SignalType.REDUCE: {2: 0, 1: 0},
        SignalType.SELL: {1: 0},
    }
    return position_map.get(signal_type, {}).get(signal_strength, 0)


def calculate_prices(price: DailyPrice, signal_type: str, price_history: list = None) -> tuple[Optional[float], Optional[float], Optional[float]]:
    """计算入场价、目标价、止损价（基于波动率）
    使用近 20 日 ATR（平均真实波幅）来设定动态目标和止损
    """
    if not price.close:
        return None, None, None

    entry = price.close

    # 计算 ATR（Average True Range）
    atr_pct = 0.02  # 默认 2% 日波动率
    if price_history and len(price_history) >= 5:
        true_ranges = []
        for i in range(1, min(len(price_history), 21)):
            h = price_history[i].high or price_history[i].close or 0
            l = price_history[i].low or price_history[i].close or 0
            prev_c = price_history[i-1].close or price_history[i].close or 0
            if h > 0 and l > 0 and prev_c > 0:
                tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
                true_ranges.append(tr / prev_c)
        if true_ranges:
            atr_pct = sum(true_ranges) / len(true_ranges)

    if signal_type in (SignalType.BUY, SignalType.ADD):
        # 目标: 3倍 ATR（约 1-3 个月的波动），止损: 1.5倍 ATR
        target_mult = max(0.10, min(0.30, atr_pct * 3))  # 限制在 10%-30%
        stop_mult = max(0.04, min(0.12, atr_pct * 1.5))  # 限制在 4%-12%
        target = round(entry * (1 + target_mult), 2)
        stop_loss = round(entry * (1 - stop_mult), 2)
    elif signal_type == SignalType.REDUCE:
        target = None
        stop_loss = round(entry * (1 - atr_pct * 2), 2)
    else:
        target = None
        stop_loss = None

    return entry, target, stop_loss


def generate_signal_for_stock(
    db: Session,
    stock_id: int,
    signal_date: date,
) -> Optional[TradeSignal]:
    """为单只股票生成交易信号"""
    score = (
        db.query(StockScore)
        .filter(StockScore.stock_id == stock_id, StockScore.score_date == signal_date)
        .first()
    )
    if not score:
        return None

    price = (
        db.query(DailyPrice)
        .filter(DailyPrice.stock_id == stock_id)
        .order_by(DailyPrice.trade_date.desc())
        .first()
    )
    if not price:
        return None

    # 获取近 20 日价格历史（用于计算波动率）
    price_history = (
        db.query(DailyPrice)
        .filter(DailyPrice.stock_id == stock_id)
        .order_by(DailyPrice.trade_date.desc())
        .limit(21)
        .all()
    )
    price_history = list(reversed(price_history))

    signal_type, strength, logic = determine_signal_type(score)
    position = calculate_position(signal_type, strength)
    entry, target, stop_loss = calculate_prices(price, signal_type, price_history)

    # 持有期建议
    holding_map = {
        SignalType.BUY: "3-6个月",
        SignalType.ADD: "2-4个月",
        SignalType.WATCH: "-",
        SignalType.REDUCE: "逐步减仓",
        SignalType.SELL: "立即",
    }

    # 风险提示
    risk_items = []
    if score.risk_score < 5:
        risk_items.append("风险评分较低")
    if score.valuation_score < 10:
        risk_items.append("估值偏高")
    if score.trend_score < 10:
        risk_items.append("趋势偏弱")

    logic_json = {
        "total_score": score.total_score,
        "quality_score": score.quality_score,
        "valuation_score": score.valuation_score,
        "growth_score": score.growth_score,
        "trend_score": score.trend_score,
        "risk_score": score.risk_score,
        "reason": logic,
    }
    risk_json = {"items": risk_items if risk_items else ["暂无重大风险"]}

    # 更新或创建信号
    existing = (
        db.query(TradeSignal)
        .filter(TradeSignal.stock_id == stock_id, TradeSignal.signal_date == signal_date)
        .first()
    )
    if existing:
        existing.signal_type = signal_type
        existing.signal_strength = strength
        existing.suggested_position = position
        existing.entry_price = entry
        existing.status = SignalStatus.ACTIVE
        existing.target_price = target
        existing.stop_loss_price = stop_loss
        existing.holding_period = holding_map.get(signal_type, "-")
        existing.logic_json = logic_json
        existing.risk_json = risk_json
        signal = existing
    else:
        signal = TradeSignal(
            stock_id=stock_id,
            signal_date=signal_date,
            signal_type=signal_type,
            signal_strength=strength,
            suggested_position=position,
            entry_price=entry,
            target_price=target,
            stop_loss_price=stop_loss,
            holding_period=holding_map.get(signal_type, "-"),
            logic_json=logic_json,
            risk_json=risk_json,
            status=SignalStatus.ACTIVE,
        )
        db.add(signal)

    db.commit()
    db.refresh(signal)
    return signal


def generate_all_signals(db: Session, signal_date: date) -> list[TradeSignal]:
    """为所有已评分股票生成信号"""
    scores = db.query(StockScore).filter(StockScore.score_date == signal_date).all()
    results = []
    for s in scores:
        sig = generate_signal_for_stock(db, s.stock_id, signal_date)
        if sig:
            results.append(sig)
    return results


def get_signal_distribution(db: Session, signal_date: date) -> dict:
    """获取信号分布统计"""
    signals = db.query(TradeSignal).filter(TradeSignal.signal_date == signal_date).all()
    dist = {"BUY": 0, "ADD": 0, "WATCH": 0, "REDUCE": 0, "SELL": 0}
    for s in signals:
        if s.signal_type in dist:
            dist[s.signal_type] += 1
    return dist


# 信号有效期（天）
SIGNAL_EXPIRY_DAYS = {
    SignalType.BUY: 60,     # 买入信号 60 天有效
    SignalType.ADD: 45,     # 加仓信号 45 天有效
    SignalType.WATCH: 30,   # 观望信号 30 天有效
    SignalType.REDUCE: 14,  # 减仓信号 14 天有效
    SignalType.SELL: 7,     # 卖出信号 7 天有效
}


def expire_old_signals(db: Session, reference_date: date = None) -> int:
    """将超过有效期的 ACTIVE 信号标记为 EXPIRED（数据库级 UPDATE，不加载到内存）
    Returns: 过期的信号数量
    """
    from sqlalchemy import update, and_

    if reference_date is None:
        reference_date = date.today()

    total_expired = 0

    for signal_type, expiry_days in SIGNAL_EXPIRY_DAYS.items():
        cutoff_date = date(reference_date.year, reference_date.month, reference_date.day)
        # 手动减去天数
        from datetime import timedelta
        cutoff_date = cutoff_date - timedelta(days=expiry_days)

        result = db.execute(
            update(TradeSignal)
            .where(and_(
                TradeSignal.status == SignalStatus.ACTIVE,
                TradeSignal.signal_type == signal_type,
                TradeSignal.signal_date < cutoff_date,
            ))
            .values(status=SignalStatus.EXPIRED)
        )
        total_expired += result.rowcount

    if total_expired > 0:
        db.commit()

    return total_expired
