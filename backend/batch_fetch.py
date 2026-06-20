"""
批量数据拉取脚本
为数据库中的股票批量拉取：价格、财务、估值、技术指标、评分
"""
import os
os.environ["MOCK_DATA"] = "false"

import time
import json
import urllib.request
from datetime import date, timedelta
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.stock import Stock
from app.models.daily_price import DailyPrice
from app.models.financial_metric import FinancialMetric
from app.models.technical_indicator import TechnicalIndicator
from app.models.stock_score import StockScore
from app.data_providers.eastmoney_provider import EastMoneyProvider
from app.services.scoring import score_stock
from app.seed import _compute_technicals


def fetch_sina_kline(symbol: str, days: int = 150) -> list:
    """新浪财经 K线 API"""
    if len(symbol) == 5 and symbol.isdigit():
        tc = f"hk{symbol}"
    elif symbol.startswith(("6", "5")):
        tc = f"sh{symbol}"
    else:
        tc = f"sz{symbol}"

    url = (
        f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
        f"CN_MarketData.getKLineData?symbol={tc}&scale=240&ma=no&datalen={days}"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=15)
        text = resp.read().decode("utf-8")
        return json.loads(text)
    except Exception:
        return []


def batch_fetch_prices(db: Session, stocks: list) -> dict:
    """批量拉取价格数据"""
    success = 0
    failed = 0
    total = len(stocks)

    for i, stock in enumerate(stocks):
        symbol = stock.symbol
        print(f"  [{i+1}/{total}] {symbol} {stock.name}...", end=" ", flush=True)

        # 检查是否已有足够数据
        existing_count = db.query(DailyPrice).filter(
            DailyPrice.stock_id == stock.id
        ).count()
        if existing_count >= 60:
            print(f"已有{existing_count}天，跳过")
            success += 1
            continue

        # 拉取 K线数据
        klines = fetch_sina_kline(symbol, days=150)
        if not klines:
            print("失败")
            failed += 1
            continue

        added = 0
        prev_close = None
        for item in klines:
            trade_date = item.get("day", "")
            if not trade_date:
                continue

            from datetime import datetime
            try:
                td = datetime.strptime(trade_date[:10], "%Y-%m-%d").date()
            except ValueError:
                continue

            existing = db.query(DailyPrice).filter(
                DailyPrice.stock_id == stock.id,
                DailyPrice.trade_date == td
            ).first()
            if existing:
                prev_close = float(item["close"])
                continue

            close = float(item["close"])
            dp = DailyPrice(
                stock_id=stock.id,
                trade_date=td,
                open=float(item["open"]),
                high=float(item["high"]),
                low=float(item["low"]),
                close=close,
                pre_close=prev_close,
                volume=float(item["volume"]),
                turnover=0,
                turnover_rate=0,
            )
            db.add(dp)
            prev_close = close
            added += 1

        if added > 0:
            db.commit()

        print(f"新增{added}天")
        success += 1
        time.sleep(0.3)  # 限速

    return {"success": success, "failed": failed}


def batch_fetch_financials(db: Session, stocks: list, provider: EastMoneyProvider) -> dict:
    """批量拉取财务数据"""
    success = 0
    failed = 0
    total = len(stocks)

    for i, stock in enumerate(stocks):
        if stock.market == "HK":
            continue  # 港股暂不支持东方财富财务数据

        symbol = stock.symbol
        print(f"  [{i+1}/{total}] {symbol} {stock.name}...", end=" ", flush=True)

        # 检查是否已有数据
        existing_count = db.query(FinancialMetric).filter(
            FinancialMetric.stock_id == stock.id
        ).count()
        if existing_count >= 4:
            print(f"已有{existing_count}期，跳过")
            success += 1
            continue

        df = provider.fetch_financial_metrics(symbol)
        if df.empty:
            print("失败")
            failed += 1
            continue

        added = 0
        for _, row in df.iterrows():
            period = row.get("report_period", "")
            if not period:
                continue

            existing = db.query(FinancialMetric).filter(
                FinancialMetric.stock_id == stock.id,
                FinancialMetric.report_period == period
            ).first()
            if existing:
                continue

            fm = FinancialMetric(
                stock_id=stock.id,
                report_period=period,
                revenue=row.get("revenue"),
                revenue_yoy=row.get("revenue_yoy"),
                net_profit=row.get("net_profit"),
                net_profit_yoy=row.get("net_profit_yoy"),
                gross_margin=row.get("gross_margin"),
                net_margin=row.get("net_margin"),
                roe=row.get("roe"),
                roa=row.get("roa"),
                debt_ratio=row.get("debt_ratio"),
                operating_cashflow=row.get("operating_cashflow"),
                free_cashflow=row.get("free_cashflow"),
                eps=row.get("eps"),
                book_value_per_share=row.get("book_value_per_share"),
            )
            db.add(fm)
            added += 1

        if added > 0:
            db.commit()

        print(f"新增{added}期")
        success += 1
        time.sleep(0.5)  # 限速

    return {"success": success, "failed": failed}


def batch_fetch_valuations(db: Session, stocks: list, provider: EastMoneyProvider) -> dict:
    """批量回填估值数据到最新价格行"""
    success = 0
    failed = 0
    total = len(stocks)

    for i, stock in enumerate(stocks):
        symbol = stock.symbol
        print(f"  [{i+1}/{total}] {symbol} {stock.name}...", end=" ", flush=True)

        latest = db.query(DailyPrice).filter(
            DailyPrice.stock_id == stock.id
        ).order_by(DailyPrice.trade_date.desc()).first()

        if not latest:
            print("无价格数据")
            failed += 1
            continue

        # 如果已有估值数据，跳过
        if latest.pe is not None and latest.pb is not None:
            print("已有估值")
            success += 1
            continue

        try:
            val = provider.fetch_valuation(symbol)
            if val.get("pe") is not None:
                latest.pe = val["pe"]
            if val.get("pb") is not None:
                latest.pb = val["pb"]
            if val.get("market_cap") is not None:
                latest.market_cap = val["market_cap"]
            if val.get("dividend_yield") is not None:
                latest.dividend_yield = val["dividend_yield"]
            db.commit()
            print(f"PE={val.get('pe')} PB={val.get('pb')}")
            success += 1
        except Exception as e:
            print(f"失败: {e}")
            failed += 1

        time.sleep(0.3)

    return {"success": success, "failed": failed}


def batch_compute_technicals(db: Session, stock_map: dict) -> int:
    """批量计算技术指标"""
    print("  计算技术指标...")
    count = _compute_technicals(db, stock_map)
    return count


def batch_score(db: Session, stocks: list, score_date: date) -> dict:
    """批量评分"""
    success = 0
    failed = 0
    total = len(stocks)

    for i, stock in enumerate(stocks):
        print(f"  [{i+1}/{total}] {stock.symbol} {stock.name}...", end=" ", flush=True)
        score = score_stock(db, stock.id, score_date)
        if score:
            print(f"{score.total_score}({score.rating})")
            success += 1
        else:
            print("失败")
            failed += 1

    return {"success": success, "failed": failed}


def main():
    db = SessionLocal()
    provider = EastMoneyProvider()

    # 获取所有活跃股票（A股优先）
    stocks = db.query(Stock).filter(Stock.status == "ACTIVE").all()

    # 按重要性排序：有行业信息的优先，然后按代码排序
    def stock_priority(s):
        has_industry = 1 if s.industry else 0
        is_a_share = 1 if s.market == "A_SHARE" else 0
        return (-is_a_share, -has_industry, s.symbol)

    stocks.sort(key=stock_priority)

    print(f"=" * 60)
    print(f"批量数据拉取 - 共 {len(stocks)} 只股票")
    print(f"=" * 60)

    # 1. 价格数据
    print(f"\n[1/4] 拉取价格数据 (新浪财经)...")
    price_result = batch_fetch_prices(db, stocks)
    print(f"  完成: 成功 {price_result['success']}, 失败 {price_result['failed']}")

    # 2. 财务数据
    print(f"\n[2/4] 拉取财务数据 (东方财富)...")
    fin_result = batch_fetch_financials(db, stocks, provider)
    print(f"  完成: 成功 {fin_result['success']}, 失败 {fin_result['failed']}")

    # 3. 估值数据
    print(f"\n[3/4] 回填估值数据 (腾讯实时)...")
    val_result = batch_fetch_valuations(db, stocks, provider)
    print(f"  完成: 成功 {val_result['success']}, 失败 {val_result['failed']}")

    # 4. 技术指标 + 评分
    print(f"\n[4/4] 计算技术指标和评分...")
    stock_map = {s.symbol: s.id for s in stocks}
    tech_count = batch_compute_technicals(db, stock_map)
    print(f"  技术指标: {tech_count} 个")

    # 只对有完整数据的股票评分
    stocks_to_score = []
    for s in stocks:
        has_price = db.query(DailyPrice).filter(DailyPrice.stock_id == s.id).count() >= 20
        has_fin = db.query(FinancialMetric).filter(FinancialMetric.stock_id == s.id).count() >= 1
        if has_price and has_fin:
            stocks_to_score.append(s)

    score_result = batch_score(db, stocks_to_score, date.today())
    print(f"  评分: 成功 {score_result['success']}, 失败 {score_result['failed']}")

    # 总结
    print(f"\n{'=' * 60}")
    print(f"数据拉取完成!")
    print(f"  价格: {price_result['success']}/{len(stocks)} 只股票")
    print(f"  财务: {fin_result['success']}/{len(stocks)} 只股票")
    print(f"  估值: {val_result['success']}/{len(stocks)} 只股票")
    print(f"  技术: {tech_count} 个指标")
    print(f"  评分: {score_result['success']}/{len(stocks_to_score)} 只股票")
    print(f"{'=' * 60}")

    db.close()


if __name__ == "__main__":
    main()
