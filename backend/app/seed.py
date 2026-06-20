"""
真实数据种子脚本 - 使用东方财富 API
运行方式: python -m app.seed
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date, timedelta
from app.db.session import SessionLocal, engine
from app.db.base import Base
from app.models.stock import Stock
from app.models.daily_price import DailyPrice
from app.models.financial_metric import FinancialMetric
from app.models.technical_indicator import TechnicalIndicator
from app.models.stock_score import StockScore
from app.models.trade_signal import TradeSignal
from app.models.report import Report
from app.models.portfolio import Portfolio, PortfolioPosition
from app.data_providers import get_provider
from app.services.scoring import calculate_quality_score, calculate_valuation_score, calculate_growth_score, calculate_trend_score, calculate_risk_score, get_rating
from app.services.signal import determine_signal_type, calculate_position, calculate_prices
from app.core.constants import SignalStatus
from app.models.user import User
from app.models.setting import Setting
import bcrypt
import numpy as np

provider = get_provider()
_use_mock = type(provider).__name__ == "MockProvider"

# 核心股票池 - 涵盖 A 股和港股优质标的
CORE_STOCKS = [
    {"symbol": "600519", "name": "贵州茅台", "market": "A_SHARE", "exchange": "SH", "industry": "白酒", "sector": "消费"},
    {"symbol": "300750", "name": "宁德时代", "market": "A_SHARE", "exchange": "SZ", "industry": "电池", "sector": "新能源"},
    {"symbol": "600036", "name": "招商银行", "market": "A_SHARE", "exchange": "SH", "industry": "银行", "sector": "金融"},
    {"symbol": "601318", "name": "中国平安", "market": "A_SHARE", "exchange": "SH", "industry": "保险", "sector": "金融"},
    {"symbol": "000858", "name": "五粮液", "market": "A_SHARE", "exchange": "SZ", "industry": "白酒", "sector": "消费"},
    {"symbol": "600900", "name": "长江电力", "market": "A_SHARE", "exchange": "SH", "industry": "电力", "sector": "公用事业"},
    {"symbol": "601012", "name": "隆基绿能", "market": "A_SHARE", "exchange": "SH", "industry": "光伏", "sector": "新能源"},
    {"symbol": "000001", "name": "平安银行", "market": "A_SHARE", "exchange": "SZ", "industry": "银行", "sector": "金融"},
    {"symbol": "600276", "name": "恒瑞医药", "market": "A_SHARE", "exchange": "SH", "industry": "医药", "sector": "医药"},
    {"symbol": "603259", "name": "药明康德", "market": "A_SHARE", "exchange": "SH", "industry": "CXO", "sector": "医药"},
    {"symbol": "00700", "name": "腾讯控股", "market": "HK", "exchange": "HK", "industry": "互联网", "sector": "科技"},
    {"symbol": "09988", "name": "阿里巴巴-W", "market": "HK", "exchange": "HK", "industry": "电商", "sector": "科技"},
    {"symbol": "09618", "name": "京东集团", "market": "HK", "exchange": "HK", "industry": "电商", "sector": "科技"},
    {"symbol": "01810", "name": "小米集团-W", "market": "HK", "exchange": "HK", "industry": "消费电子", "sector": "科技"},
    {"symbol": "02318", "name": "中国平安H", "market": "HK", "exchange": "HK", "industry": "保险", "sector": "金融"},
]


def seed(force: bool = False):
    """执行数据种子 - 使用真实东方财富数据"""
    print("=" * 60)
    print("融衔 数据初始化 (东方财富真实数据)")
    print("=" * 60)

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    # 创建测试账号
    _seed_users(db)

    # 检查是否已有数据
    existing = db.query(Stock).count()
    if existing > 0 and not force:
        print(f"Database already has {existing} stocks. Skipping seed.")
        print("To re-seed: python -m app.seed --force")
        db.close()
        return

    if force:
        print("Force mode: clearing existing data...")
        _clear_data(db)

    # 1. 插入股票
    print("\n[1/8] Seeding stocks from East Money API...")
    stock_map = {}
    for s in CORE_STOCKS:
        stock = Stock(**s)
        db.add(stock)
        db.flush()
        stock_map[s["symbol"]] = stock.id
    db.commit()
    print(f"  Inserted {len(CORE_STOCKS)} stocks")

    # 2. 获取真实行情数据 (腾讯 API)
    print("\n[2/8] Fetching real daily prices...")
    import time
    today = date.today()
    start = today - timedelta(days=180)
    price_count = 0
    for symbol, stock_id in stock_map.items():
        try:
            df = provider.fetch_daily_prices(symbol, start, today)
            if df.empty:
                print(f"  WARNING: No price data for {symbol}")
                continue
            for _, row in df.iterrows():
                trade_date = row["trade_date"]
                if hasattr(trade_date, "date"):
                    trade_date = trade_date.date()
                dp = DailyPrice(
                    stock_id=stock_id,
                    trade_date=trade_date,
                    open=round(row["open"], 2),
                    high=round(row["high"], 2),
                    low=round(row["low"], 2),
                    close=round(row["close"], 2),
                    pre_close=round(row["pre_close"], 2) if row.get("pre_close") and not _is_nan(row["pre_close"]) else None,
                    volume=round(row["volume"], 0),
                    turnover=round(row["turnover"], 0),
                    turnover_rate=round(row["turnover_rate"], 2) if not _is_nan(row.get("turnover_rate")) else 0,
                    market_cap=round(row["market_cap"], 0) if row.get("market_cap") and not _is_nan(row["market_cap"]) else None,
                    pe=round(row["pe"], 2) if row.get("pe") and not _is_nan(row["pe"]) else None,
                    pb=round(row["pb"], 2) if row.get("pb") and not _is_nan(row["pb"]) else None,
                    dividend_yield=round(row["dividend_yield"], 2) if row.get("dividend_yield") and not _is_nan(row["dividend_yield"]) else None,
                )
                db.add(dp)
                price_count += 1
            db.commit()
            print(f"  {symbol}: {len(df)} days")
        except Exception as e:
            db.rollback()
            print(f"  ERROR fetching {symbol}: {e}")
    print(f"  Total: {price_count} daily prices")

    # 3. 获取真实财务数据 (Yahoo Finance)
    print("\n[3/8] Fetching real financial metrics from Yahoo Finance...")
    fin_count = 0
    for idx, (symbol, stock_id) in enumerate(stock_map.items()):
        if idx > 0 and not _use_mock:
            time.sleep(3)  # 避免 Yahoo Finance 限流
        try:
            df = provider.fetch_financial_metrics(symbol)
            if df.empty:
                print(f"  WARNING: No financial data for {symbol}")
                continue
            for _, row in df.iterrows():
                fm = FinancialMetric(
                    stock_id=stock_id,
                    report_period=row.get("report_period", ""),
                    revenue=_safe_round(row.get("revenue"), 2),
                    revenue_yoy=_safe_round(row.get("revenue_yoy"), 2),
                    net_profit=_safe_round(row.get("net_profit"), 2),
                    net_profit_yoy=_safe_round(row.get("net_profit_yoy"), 2),
                    gross_margin=_safe_round(row.get("gross_margin"), 2),
                    net_margin=_safe_round(row.get("net_margin"), 2),
                    roe=_safe_round(row.get("roe"), 2),
                    roa=_safe_round(row.get("roa"), 2),
                    debt_ratio=_safe_round(row.get("debt_ratio"), 2),
                    operating_cashflow=_safe_round(row.get("operating_cashflow"), 2),
                    free_cashflow=_safe_round(row.get("free_cashflow"), 2),
                    eps=_safe_round(row.get("eps"), 2),
                    book_value_per_share=_safe_round(row.get("book_value_per_share"), 2),
                )
                db.add(fm)
                fin_count += 1
            db.commit()
            print(f"  {symbol}: {len(df)} reports")
        except Exception as e:
            db.rollback()
            print(f"  ERROR fetching financials for {symbol}: {e}")
    print(f"  Total: {fin_count} financial reports")

    # 3.5 从已有数据计算估值 (PE/PB)
    print("\n[3.5/8] Computing valuation from price + financial data...")
    for symbol, stock_id in stock_map.items():
        latest_price = db.query(DailyPrice).filter(
            DailyPrice.stock_id == stock_id
        ).order_by(DailyPrice.trade_date.desc()).first()
        latest_fin = db.query(FinancialMetric).filter(
            FinancialMetric.stock_id == stock_id
        ).order_by(FinancialMetric.report_period.desc()).first()
        if latest_price and latest_fin:
            if latest_fin.eps and latest_fin.eps > 0:
                latest_price.pe = round(latest_price.close / latest_fin.eps, 2)
            if latest_fin.book_value_per_share and latest_fin.book_value_per_share > 0:
                latest_price.pb = round(latest_price.close / latest_fin.book_value_per_share, 2)
    db.commit()
    print("  Valuation computed from financial data")

    # 4. 计算技术指标
    print("\n[4/8] Computing technical indicators...")
    tech_count = _compute_technicals(db, stock_map)
    print(f"  Total: {tech_count} technical indicators")

    # 5. 评分
    print("\n[5/8] Scoring stocks...")
    score_count = _score_stocks(db, stock_map, today)
    print(f"  Total: {score_count} scores")

    # 5.5 生成历史评分快照（用于回测）
    print("\n[5.5/8] Generating historical score snapshots for backtest...")
    _generate_historical_scores(db, stock_map)

    # 6. 生成信号
    print("\n[6/8] Generating trading signals...")
    signal_count = _generate_signals(db, today)
    print(f"  Total: {signal_count} signals")

    # 7. 生成报告
    print("\n[7/8] Generating daily report...")
    report = generate_daily_report(db, today)
    print(f"  Report: {report.title}")

    # 8. 创建组合并生成历史净值
    print("\n[8/8] Creating portfolio and generating historical NAV...")
    _create_portfolio(db, today)
    _generate_historical_nav(db, stock_map)

    db.close()
    print("\n" + "=" * 60)
    print("Seed completed successfully!")
    print("=" * 60)
    print("Disclaimer: 本系统仅用于研究和辅助分析，不构成任何投资建议。")


def _seed_users(db):
    """创建测试账号"""
    test_accounts = [
        {"username": "admin", "password": "admin123", "display_name": "管理员", "role": "admin"},
        {"username": "demo", "password": "demo123", "display_name": "演示用户", "role": "user"},
        {"username": "analyst", "password": "analyst123", "display_name": "分析师", "role": "analyst"},
        {"username": "guest", "password": "guest123", "display_name": "访客", "role": "guest"},
    ]
    for acc in test_accounts:
        existing = db.query(User).filter(User.username == acc["username"]).first()
        if not existing:
            pw_hash = bcrypt.hashpw(acc["password"].encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
            user = User(
                username=acc["username"],
                password_hash=pw_hash,
                display_name=acc["display_name"],
                role=acc["role"],
            )
            db.add(user)
            print(f"  Created user: {acc['username']} / {acc['password']}")
        else:
            # 确保已有用户的 role 始终正确
            if existing.role != acc["role"]:
                existing.role = acc["role"]
                print(f"  Updated {acc['username']} role -> {acc['role']}")
    db.commit()

    # 创建默认通知设置
    default_settings = [
        ("email_smtp_host", "smtp.qq.com", "SMTP 服务器"),
        ("email_smtp_port", "465", "SMTP 端口"),
        ("email_sender", "", "发件邮箱 (QQ邮箱)"),
        ("email_password", "", "邮箱授权码"),
        ("email_recipient", "", "收件邮箱"),
        ("feishu_webhook", "", "飞书 Webhook URL"),
        ("feishu_enabled", "false", "启用飞书推送"),
    ]
    for key, value, desc in default_settings:
        existing = db.query(Setting).filter(Setting.key == key).first()
        if not existing:
            db.add(Setting(key=key, value=value, description=desc))
    db.commit()


def _clear_data(db):
    """清除所有数据表（保留用户）"""
    for model in [PortfolioPosition, Portfolio, Report, TradeSignal, StockScore, TechnicalIndicator, FinancialMetric, DailyPrice, Stock]:
        db.query(model).delete()
    db.commit()


def _ema(values: list, period: int) -> list:
    """计算 EMA（指数移动平均），返回与输入等长的列表"""
    alpha = 2.0 / (period + 1)
    result = [None] * len(values)
    if len(values) < period:
        return result
    # 初始值用 SMA
    result[period - 1] = sum(values[:period]) / period
    for i in range(period, len(values)):
        result[i] = alpha * values[i] + (1 - alpha) * result[i - 1]
    return result


def _rsi(closes: list, period: int = 14) -> list:
    """计算 RSI（相对强弱指数），返回与输入等长的列表"""
    result = [None] * len(closes)
    if len(closes) < period + 1:
        return result
    # 计算涨跌幅
    gains = []
    losses = []
    for i in range(1, len(closes)):
        change = closes[i] - closes[i - 1]
        gains.append(max(change, 0))
        losses.append(max(-change, 0))
    # 初始平均涨跌（SMA）
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    if avg_loss == 0:
        result[period] = 100.0
    else:
        rs = avg_gain / avg_loss
        result[period] = 100.0 - 100.0 / (1.0 + rs)
    # 后续用 EMA 平滑
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            result[i + 1] = 100.0
        else:
            rs = avg_gain / avg_loss
            result[i + 1] = 100.0 - 100.0 / (1.0 + rs)
    return result


def _compute_technicals(db, stock_map):
    """计算技术指标（MACD/RSI/布林带 均使用标准算法）"""
    count = 0
    for symbol, stock_id in stock_map.items():
        # 检查是否已有技术指标
        existing_tech = db.query(TechnicalIndicator).filter(
            TechnicalIndicator.stock_id == stock_id
        ).count()
        if existing_tech > 0:
            continue

        prices = db.query(DailyPrice).filter(DailyPrice.stock_id == stock_id).order_by(DailyPrice.trade_date).all()
        if len(prices) < 26:  # MACD 需要至少 26 天数据
            continue
        closes = [p.close for p in prices]
        volumes = [p.volume for p in prices]
        n = len(closes)

        # 预计算 EMA12 / EMA26 / MACD
        ema12 = _ema(closes, 12)
        ema26 = _ema(closes, 26)

        # MACD = EMA12 - EMA26
        macd_line = [None] * n
        for i in range(25, n):
            if ema12[i] is not None and ema26[i] is not None:
                macd_line[i] = ema12[i] - ema26[i]

        # Signal = 9日 EMA of MACD
        # 先提取有效的 MACD 值序列
        macd_valid = [v for v in macd_line if v is not None]
        macd_start = next((i for i, v in enumerate(macd_line) if v is not None), n)
        signal_line = [None] * n
        if len(macd_valid) >= 9:
            signal_ema = _ema(macd_valid, 9)
            for j, sv in enumerate(signal_ema):
                if sv is not None:
                    signal_line[macd_start + j] = sv

        # RSI14
        rsi_values = _rsi(closes, 14)

        # 预计算各均线
        ma20_arr = [None] * n
        ma60_arr = [None] * n
        ma120_arr = [None] * n
        vol_ma5_arr = [None] * n
        vol_ma20_arr = [None] * n

        for i in range(19, n):
            ma20_arr[i] = np.mean(closes[i - 19:i + 1])
        for i in range(59, n):
            ma60_arr[i] = np.mean(closes[i - 59:i + 1])
        for i in range(119, n):
            ma120_arr[i] = np.mean(closes[i - 119:i + 1])
        for i in range(4, n):
            vol_ma5_arr[i] = np.mean(volumes[i - 4:i + 1])
        for i in range(19, n):
            vol_ma20_arr[i] = np.mean(volumes[i - 19:i + 1])

        # 布林带：MA20 ± 2σ（20日标准差）
        boll_upper_arr = [None] * n
        boll_lower_arr = [None] * n
        for i in range(19, n):
            window = closes[i - 19:i + 1]
            std = np.std(window, ddof=0)  # 总体标准差
            boll_upper_arr[i] = ma20_arr[i] + 2 * std
            boll_lower_arr[i] = ma20_arr[i] - 2 * std

        for i, p in enumerate(prices):
            if i < 19:
                continue
            macd_val = macd_line[i]
            signal_val = signal_line[i]
            hist_val = (macd_val - signal_val) if macd_val is not None and signal_val is not None else None

            ti = TechnicalIndicator(
                stock_id=stock_id,
                trade_date=p.trade_date,
                ma20=round(ma20_arr[i], 2) if ma20_arr[i] is not None else None,
                ma60=round(ma60_arr[i], 2) if ma60_arr[i] is not None else None,
                ma120=round(ma120_arr[i], 2) if ma120_arr[i] is not None else None,
                macd=round(macd_val, 4) if macd_val is not None else None,
                macd_signal=round(signal_val, 4) if signal_val is not None else None,
                macd_hist=round(hist_val, 4) if hist_val is not None else None,
                rsi14=round(rsi_values[i], 2) if rsi_values[i] is not None else None,
                boll_upper=round(boll_upper_arr[i], 2) if boll_upper_arr[i] is not None else None,
                boll_middle=round(ma20_arr[i], 2) if ma20_arr[i] is not None else None,
                boll_lower=round(boll_lower_arr[i], 2) if boll_lower_arr[i] is not None else None,
                volume_ma5=round(vol_ma5_arr[i], 0) if vol_ma5_arr[i] is not None else None,
                volume_ma20=round(vol_ma20_arr[i], 0) if vol_ma20_arr[i] is not None else None,
            )
            db.add(ti)
            count += 1
    db.commit()
    return count


def _parse_report_period(period_str: str):
    """解析报告期字符串为日期，支持 '2024-12-31' 和 '2024Q4' 两种格式"""
    from datetime import datetime as _dt
    s = str(period_str)
    try:
        return _dt.strptime(s[:10], "%Y-%m-%d")
    except ValueError:
        pass
    if "Q" in s:
        try:
            year = int(s[:4])
            quarter = int(s[5])
            month = quarter * 3
            return _dt(year, month, 28)
        except (ValueError, IndexError):
            pass
    return None


def _generate_historical_scores(db, stock_map):
    """为历史日期生成评分快照，使回测可用
    每月月初生成一次评分，使用该日期之前已披露的财务数据（避免前瞻偏差）
    """
    from datetime import timedelta

    # 收集所有有价格数据的日期
    all_dates = set()
    for symbol, stock_id in stock_map.items():
        prices = db.query(DailyPrice.trade_date).filter(
            DailyPrice.stock_id == stock_id
        ).all()
        for p in prices:
            all_dates.add(p.trade_date)

    if not all_dates:
        return

    sorted_dates = sorted(all_dates)
    # 每月第一个交易日生成评分
    monthly_dates = []
    seen_months = set()
    for d in sorted_dates:
        month_key = (d.year, d.month)
        if month_key not in seen_months:
            seen_months.add(month_key)
            monthly_dates.append(d)

    # 预加载所有财务数据，按 stock_id 分组
    all_financials = db.query(FinancialMetric).all()
    financials_by_stock = {}
    for f in all_financials:
        financials_by_stock.setdefault(f.stock_id, []).append(f)
    # 每组按报告期排序（旧→新）
    for sid in financials_by_stock:
        financials_by_stock[sid].sort(key=lambda f: str(f.report_period))

    count = 0
    for score_date in monthly_dates:
        for symbol, stock_id in stock_map.items():
            # 检查是否已有该日期的评分
            existing = db.query(StockScore).filter(
                StockScore.stock_id == stock_id,
                StockScore.score_date == score_date
            ).first()
            if existing:
                continue

            # 获取该日期之前（含）的最新价格
            price = db.query(DailyPrice).filter(
                DailyPrice.stock_id == stock_id,
                DailyPrice.trade_date <= score_date
            ).order_by(DailyPrice.trade_date.desc()).first()
            if not price:
                continue

            # 获取该日期之前已披露的最新财务数据（避免前瞻偏差）
            # 中国 A 股：Q1 报告 4/30 前披露，Q2 报告 8/31 前，Q3 报告 10/31 前，Q4 报告 4/30 前
            financial = None
            for f in financials_by_stock.get(stock_id, []):
                f_date = _parse_report_period(f.report_period)
                if f_date is None:
                    continue
                # 估算披露日期：报告期 + 披露延迟
                # Q4(12月) → 次年4/30, Q1(3月) → 4/30, Q2(6月) → 8/31, Q3(9月) → 10/31
                month = f_date.month
                if month == 12:
                    disclosure_date = date(f_date.year + 1, 4, 30)
                elif month == 3:
                    disclosure_date = date(f_date.year, 4, 30)
                elif month == 6:
                    disclosure_date = date(f_date.year, 8, 31)
                elif month == 9:
                    disclosure_date = date(f_date.year, 10, 31)
                else:
                    # 年报日期格式，直接用报告期
                    disclosure_date = f_date.date() if hasattr(f_date, 'date') else f_date

                if disclosure_date <= score_date:
                    financial = f
                else:
                    break  # 后续的报告还未披露

            # 获取该日期之前（含）的最新技术指标
            tech = db.query(TechnicalIndicator).filter(
                TechnicalIndicator.stock_id == stock_id,
                TechnicalIndicator.trade_date <= score_date
            ).order_by(TechnicalIndicator.trade_date.desc()).first()

            stock = db.query(Stock).filter(Stock.id == stock_id).first()
            industry = stock.industry if stock else ""

            # 获取该日期之前的价格历史（用于回撤计算）
            price_hist = db.query(DailyPrice).filter(
                DailyPrice.stock_id == stock_id,
                DailyPrice.trade_date <= score_date
            ).order_by(DailyPrice.trade_date.desc()).limit(90).all()
            price_hist = list(reversed(price_hist))

            # 获取该日期之前的财务历史（用于 CAGR）
            fin_history = [
                f for f in financials_by_stock.get(stock_id, [])
                if _parse_report_period(f.report_period) and
                _parse_report_period(f.report_period).date() <= score_date
            ]

            # 计算评分
            if financial:
                q_score, _ = calculate_quality_score(financial, industry)
                v_score, _ = calculate_valuation_score(price, financial)
                g_score, _ = calculate_growth_score(financial, fin_history)
                r_score, _ = calculate_risk_score(financial, price, price_hist)
            else:
                q_score, v_score, g_score, r_score = 0, 0, 0, 0

            t_score, _ = calculate_trend_score(price, tech) if tech else (0, [])

            total = q_score + v_score + g_score + t_score + r_score
            rating = get_rating(total)

            score = StockScore(
                stock_id=stock_id,
                score_date=score_date,
                total_score=round(total, 1),
                quality_score=round(q_score, 1),
                valuation_score=round(v_score, 1),
                growth_score=round(g_score, 1),
                trend_score=round(t_score, 1),
                risk_score=round(r_score, 1),
                rating=rating,
                reason_summary=f"历史快照 {score_date}",
            )
            db.add(score)
            count += 1

        # 每个月提交一次
        db.commit()

    print(f"  Generated {count} historical score snapshots across {len(monthly_dates)} months")


def _score_stocks(db, stock_map, score_date):
    """对所有股票使用真实评分模型评分"""
    count = 0
    for symbol, stock_id in stock_map.items():
        stock = db.query(Stock).filter(Stock.id == stock_id).first()
        price = db.query(DailyPrice).filter(DailyPrice.stock_id == stock_id).order_by(DailyPrice.trade_date.desc()).first()
        financial = db.query(FinancialMetric).filter(FinancialMetric.stock_id == stock_id).order_by(FinancialMetric.report_period.desc()).first()
        tech = db.query(TechnicalIndicator).filter(TechnicalIndicator.stock_id == stock_id).order_by(TechnicalIndicator.trade_date.desc()).first()

        if not price:
            continue

        # 获取价格历史（用于回撤计算）
        price_history = db.query(DailyPrice).filter(
            DailyPrice.stock_id == stock_id
        ).order_by(DailyPrice.trade_date.desc()).limit(90).all()
        price_history = list(reversed(price_history))

        # 获取财务历史（用于 CAGR 计算）
        financial_history = db.query(FinancialMetric).filter(
            FinancialMetric.stock_id == stock_id
        ).order_by(FinancialMetric.report_period.desc()).limit(8).all()

        industry = stock.industry if stock else ""

        # 使用真实评分模型
        if financial:
            q_score, q_details = calculate_quality_score(financial, industry)
            v_score, v_details = calculate_valuation_score(price, financial)
            g_score, g_details = calculate_growth_score(financial, financial_history)
            r_score, r_details = calculate_risk_score(financial, price, price_history)
        else:
            q_score, v_score, g_score, r_score = 0, 0, 0, 0

        t_score, t_details = calculate_trend_score(price, tech) if tech else (0, [])

        total = q_score + v_score + g_score + t_score + r_score

        # 构建评分摘要
        all_details = (q_details if financial else []) + (v_details if financial else []) + (g_details if financial else []) + (t_details if tech else []) + (r_details if financial else [])
        strengths = [d["item"] for d in all_details if d.get("score", 0) >= d.get("max", 1) * 0.7]
        weaknesses = [d["item"] for d in all_details if d.get("score", 0) <= d.get("max", 1) * 0.3 and d.get("max", 0) > 0]
        reason = f"优势: {', '.join(strengths[:3])}" if strengths else ""
        if weaknesses:
            reason += f" | 风险: {', '.join(weaknesses[:3])}"

        rating = get_rating(total)

        score = StockScore(
            stock_id=stock_id,
            score_date=score_date,
            total_score=round(total, 1),
            quality_score=round(q_score, 1),
            valuation_score=round(v_score, 1),
            growth_score=round(g_score, 1),
            trend_score=round(t_score, 1),
            risk_score=round(r_score, 1),
            rating=rating,
            reason_summary=reason,
        )
        db.add(score)
        count += 1
    db.commit()
    return count


def _generate_signals(db, signal_date):
    """生成交易信号"""
    count = 0
    scores = db.query(StockScore).filter(StockScore.score_date == signal_date).all()
    for sc in scores:
        price = db.query(DailyPrice).filter(DailyPrice.stock_id == sc.stock_id).order_by(DailyPrice.trade_date.desc()).first()
        if not price:
            continue

        sig_type, strength, logic = determine_signal_type(sc)
        position = calculate_position(sig_type, strength)
        entry, target, stop_loss = calculate_prices(price, sig_type)

        holding_map = {"BUY": "3-6个月", "ADD": "2-4个月", "WATCH": "-", "REDUCE": "逐步减仓", "SELL": "立即"}

        signal = TradeSignal(
            stock_id=sc.stock_id,
            signal_date=signal_date,
            signal_type=sig_type,
            signal_strength=strength,
            suggested_position=position,
            entry_price=entry,
            target_price=target,
            stop_loss_price=stop_loss,
            holding_period=holding_map.get(sig_type, "-"),
            logic_json={
                "total_score": sc.total_score,
                "quality_score": sc.quality_score,
                "valuation_score": sc.valuation_score,
                "growth_score": sc.growth_score,
                "trend_score": sc.trend_score,
                "risk_score": sc.risk_score,
                "reason": logic,
            },
            risk_json={"items": ["关注宏观经济变化"] if sc.risk_score and sc.risk_score >= 5 else ["风险评分偏低", "注意仓位控制"]},
            status=SignalStatus.ACTIVE,
        )
        db.add(signal)
        count += 1
    db.commit()
    return count


def _create_portfolio(db, score_date):
    """创建模拟组合"""
    portfolio = Portfolio(
        name="基本面中长期组合",
        strategy_type="fundamental_medium_long",
        target_position=65.0,
        cash_ratio=35.0,
    )
    db.add(portfolio)
    db.commit()
    db.refresh(portfolio)

    buy_scores = db.query(StockScore).filter(
        StockScore.score_date == score_date,
        StockScore.rating.in_(["BUY", "ADD"])
    ).all()
    pos_ratio = 65.0 / max(len(buy_scores), 1)
    for sc in buy_scores:
        price = db.query(DailyPrice).filter(DailyPrice.stock_id == sc.stock_id).order_by(DailyPrice.trade_date.desc()).first()
        if price:
            # 模拟持仓收益：买入价比当前价低 5-15%
            import random
            cost_factor = random.uniform(0.85, 0.95)
            cost = round(price.close * cost_factor, 2)
            ret = round((price.close - cost) / cost * 100, 2)
            pp = PortfolioPosition(
                portfolio_id=portfolio.id,
                stock_id=sc.stock_id,
                position_ratio=round(pos_ratio, 1),
                cost_price=cost,
                current_price=price.close,
                unrealized_return=ret,
            )
            db.add(pp)
    db.commit()
    print(f"  Created portfolio with {len(buy_scores)} positions")


def _generate_historical_nav(db, stock_map):
    """为历史日期生成净值记录，使 Dashboard 从第一天就有真实指标"""
    from app.models.portfolio import Portfolio, PortfolioNAV

    portfolio = db.query(Portfolio).first()
    if not portfolio:
        return

    # 收集所有有价格数据的日期
    all_dates = set()
    for symbol, stock_id in stock_map.items():
        prices = db.query(DailyPrice.trade_date).filter(
            DailyPrice.stock_id == stock_id
        ).all()
        for p in prices:
            all_dates.add(p.trade_date)

    if not all_dates:
        return

    sorted_dates = sorted(all_dates)

    # 用等权组合模拟净值
    initial_capital = 1000000.0
    nav = initial_capital
    benchmark_nav = initial_capital
    prev_prices = {}  # stock_id -> close

    count = 0
    for nav_date in sorted_dates:
        # 获取当日所有股票价格
        daily_returns = []
        bench_returns = []
        current_prices = {}

        for symbol, stock_id in stock_map.items():
            price = db.query(DailyPrice).filter(
                DailyPrice.stock_id == stock_id,
                DailyPrice.trade_date <= nav_date,
            ).order_by(DailyPrice.trade_date.desc()).first()

            if price and price.close:
                current_prices[stock_id] = price.close
                if stock_id in prev_prices and prev_prices[stock_id] > 0:
                    daily_ret = (price.close - prev_prices[stock_id]) / prev_prices[stock_id]
                    daily_returns.append(daily_ret)
                    bench_returns.append(daily_ret)

        # 计算当日净值（等权）
        if daily_returns:
            avg_return = sum(daily_returns) / len(daily_returns)
            nav *= (1 + avg_return)
            benchmark_nav *= (1 + sum(bench_returns) / len(bench_returns))

        # 存储净值（每 5 天存一条，避免数据量过大）
        if count % 5 == 0 or nav_date == sorted_dates[-1]:
            cumulative_return = (nav - initial_capital) / initial_capital
            existing = db.query(PortfolioNAV).filter(
                PortfolioNAV.portfolio_id == portfolio.id,
                PortfolioNAV.nav_date == nav_date,
            ).first()
            if not existing:
                db.add(PortfolioNAV(
                    portfolio_id=portfolio.id,
                    nav_date=nav_date,
                    total_value=round(nav, 2),
                    position_value=round(nav * 0.6, 2),
                    cash_value=round(nav * 0.4, 2),
                    daily_return=round(avg_return * 100, 4) if daily_returns else 0,
                    cumulative_return=round(cumulative_return * 100, 4),
                    benchmark_value=round(benchmark_nav, 2),
                    benchmark_return=round(avg_return * 100, 4) if daily_returns else 0,
                ))

        prev_prices = current_prices
        count += 1

    db.commit()
    print(f"  Generated {count // 5 + 1} historical NAV records")


def _safe_round(val, decimals):
    """安全四舍五入，处理 None/NaN"""
    if val is None or _is_nan(val):
        return None
    try:
        return round(float(val), decimals)
    except (ValueError, TypeError):
        return None


def _is_nan(val):
    """判断是否为 NaN"""
    if val is None:
        return True
    try:
        import math
        return math.isnan(float(val))
    except (ValueError, TypeError):
        return True


def refresh_daily():
    """每日增量刷新 - 只更新核心股票池（避免 Yahoo Finance 限流）"""
    import time
    print(f"[{date.today()}] Daily refresh starting...")
    db = SessionLocal()

    today = date.today()
    yesterday = today - timedelta(days=1)

    # 只更新核心股票池（有完整数据的股票）
    core_symbols = [s["symbol"] for s in CORE_STOCKS]
    stocks = db.query(Stock).filter(Stock.symbol.in_(core_symbols)).all()
    if not stocks:
        print("No core stocks in database. Run seed first.")
        db.close()
        return

    stock_map = {s.symbol: s.id for s in stocks}

    # 更新行情
    for idx, (symbol, stock_id) in enumerate(stock_map.items()):
        if idx > 0 and not _use_mock:
            time.sleep(3)
        try:
            df = provider.fetch_daily_prices(symbol, yesterday, today)
            for _, row in df.iterrows():
                trade_date = row["trade_date"]
                if hasattr(trade_date, "date"):
                    trade_date = trade_date.date()
                existing = db.query(DailyPrice).filter(
                    DailyPrice.stock_id == stock_id,
                    DailyPrice.trade_date == trade_date
                ).first()
                if existing:
                    continue
                dp = DailyPrice(
                    stock_id=stock_id,
                    trade_date=trade_date,
                    open=round(row["open"], 2),
                    high=round(row["high"], 2),
                    low=round(row["low"], 2),
                    close=round(row["close"], 2),
                    pre_close=round(row["pre_close"], 2) if row.get("pre_close") and not _is_nan(row["pre_close"]) else None,
                    volume=round(row["volume"], 0),
                    turnover=round(row["turnover"], 0),
                    turnover_rate=round(row["turnover_rate"], 2) if not _is_nan(row.get("turnover_rate")) else 0,
                )
                db.add(dp)
            db.commit()
            print(f"  {symbol}: refreshed")
        except Exception as e:
            db.rollback()
            print(f"  Error refreshing {symbol}: {e}")

    # 回填估值数据
    print("  Backfilling valuation data...")
    for symbol, stock_id in stock_map.items():
        try:
            val = provider.fetch_valuation(symbol)
            if val:
                latest = db.query(DailyPrice).filter(
                    DailyPrice.stock_id == stock_id
                ).order_by(DailyPrice.trade_date.desc()).first()
                if latest:
                    if val.get("pe") is not None:
                        latest.pe = val["pe"]
                    if val.get("pb") is not None:
                        latest.pb = val["pb"]
                    if val.get("market_cap") is not None:
                        latest.market_cap = val["market_cap"]
                    if val.get("dividend_yield") is not None:
                        latest.dividend_yield = val["dividend_yield"]
        except Exception as e:
            print(f"  valuation refresh failed for {symbol}: {e}")
    db.commit()
    print("  Valuation backfill done")

    # 过期旧信号
    from app.services.signal import expire_old_signals
    expired = expire_old_signals(db, today)
    if expired > 0:
        print(f"  Expired {expired} old signals")

    # 重新评分和生成信号
    _score_stocks(db, stock_map, today)
    _generate_signals(db, today)
    generate_daily_report(db, today)

    # 更新组合持仓
    from app.services.portfolio import update_positions_from_signals, record_daily_nav
    portfolio_result = update_positions_from_signals(db, today)
    print(f"  Portfolio: +{portfolio_result['added']} -{portfolio_result['removed']} ~{portfolio_result['updated']}")

    # 记录每日净值
    nav_result = record_daily_nav(db, today)
    print(f"  NAV: {nav_result['nav']}, daily: {nav_result['daily_return']:.2f}%, cumulative: {nav_result['cumulative_return']:.2f}%")

    db.close()
    print(f"[{today}] Daily refresh completed.")


# 导入报告生成（放在最后避免循环引用）
from app.services.report import generate_daily_report


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="Force re-seed (clear existing data)")
    parser.add_argument("--refresh", action="store_true", help="Daily refresh only")
    args = parser.parse_args()

    if args.refresh:
        refresh_daily()
    else:
        seed(force=args.force)
