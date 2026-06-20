"""
股票列表同步服务 - 从新浪/腾讯拉取全部A股+港股代码入库
研报同步服务 - 从东方财富拉取研报入库
"""
import json
import re
import time
import urllib.request
from datetime import datetime
from sqlalchemy.orm import Session
from app.models.stock import Stock
from app.models.daily_price import DailyPrice
from app.models.research_report import ResearchReport
from app.data_providers import get_provider


def _fetch_sina_stock_list(node: str, max_count: int = 6000) -> list:
    """从新浪财经获取A股列表
    node: sh_a (沪A) / sz_a (深A)
    """
    url = (
        f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
        f"Market_Center.getHQNodeDataSimple?page=1&num={max_count}&sort=symbol&asc=1&node={node}"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    resp = urllib.request.urlopen(req, timeout=30)
    raw = resp.read()
    text = raw.decode("gbk", errors="replace")
    data = json.loads(text)

    stocks = []
    for item in data:
        symbol_full = item.get("symbol", "")  # e.g. "sh600000" or "sz000001"
        code = item.get("code", "")  # e.g. "600000"
        name = item.get("name", "")
        if not code or not name:
            continue
        exchange = "SH" if symbol_full.startswith("sh") else "SZ"
        stocks.append({
            "symbol": code,
            "name": name,
            "exchange": exchange,
        })
    return stocks


def _fetch_hk_stock_list() -> list:
    """从腾讯行情接口获取港股列表（通过批量查询代码范围）"""
    stocks = []
    # 港股代码范围: 00001-09999 (主板), 01000-01999 (创业板部分)
    # 分批查询，每批100个
    for start in range(1, 10000, 100):
        end = min(start + 100, 10000)
        codes = [f"hk{str(i).zfill(5)}" for i in range(start, end)]
        url = f"https://qt.gtimg.cn/q={','.join(codes)}"

        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            resp = urllib.request.urlopen(req, timeout=15)
            text = resp.read().decode("gbk", errors="replace")

            pattern = r'v_hk(\d+)="([^"]*)"'
            matches = re.findall(pattern, text)
            for code, data_str in matches:
                fields = data_str.split("~")
                if len(fields) > 3 and fields[1] and fields[1].strip():
                    stocks.append({
                        "symbol": code,
                        "name": fields[1].strip(),
                        "exchange": "HK",
                    })
        except Exception:
            continue

        # 每批间隔一下，避免请求过快
        time.sleep(0.3)

    return stocks


def sync_stock_list(db: Session, market: str = "ALL") -> dict:
    """同步股票列表到数据库
    market: A_SHARE / HK / ALL
    返回: {"added": int, "updated": int, "total": int}
    """
    added = 0
    updated = 0
    total = 0

    if market in ("A_SHARE", "ALL"):
        # 同步A股
        for node, mkt in [("sh_a", "A_SHARE"), ("sz_a", "A_SHARE")]:
            try:
                stocks = _fetch_sina_stock_list(node)
                for s in stocks:
                    existing = db.query(Stock).filter(Stock.symbol == s["symbol"]).first()
                    if existing:
                        if existing.name != s["name"]:
                            existing.name = s["name"]
                        updated += 1
                    else:
                        db.add(Stock(
                            symbol=s["symbol"],
                            name=s["name"],
                            market=mkt,
                            exchange=s["exchange"],
                            currency="CNY",
                            status="ACTIVE",
                        ))
                        added += 1
                    total += 1
                db.commit()
            except Exception as e:
                print(f"Failed to sync {node}: {e}")
                db.rollback()

    if market in ("HK", "ALL"):
        # 同步港股
        try:
            stocks = _fetch_hk_stock_list()
            for s in stocks:
                existing = db.query(Stock).filter(Stock.symbol == s["symbol"]).first()
                if existing:
                    if existing.name != s["name"]:
                        existing.name = s["name"]
                    updated += 1
                else:
                    db.add(Stock(
                        symbol=s["symbol"],
                        name=s["name"],
                        market="HK",
                        exchange="HK",
                        currency="HKD",
                        status="ACTIVE",
                    ))
                    added += 1
                total += 1
            db.commit()
        except Exception as e:
            print(f"Failed to sync HK stocks: {e}")
            db.rollback()

    return {"added": added, "updated": updated, "total": total}


def sync_research_reports(db: Session, symbol: str = None, max_pages: int = 3) -> dict:
    """从东方财富同步研报到数据库"""
    provider = get_provider()
    added = 0
    skipped = 0

    for page in range(1, max_pages + 1):
        result = provider.fetch_reports(symbol=symbol, page=page, page_size=50)
        reports = result.get("reports", [])
        if not reports:
            break

        for r in reports:
            info_code = r.get("info_code", "")
            if not info_code:
                skipped += 1
                continue

            existing = db.query(ResearchReport).filter(
                ResearchReport.info_code == info_code
            ).first()
            if existing:
                skipped += 1
                continue

            pub_date = None
            pd_str = r.get("publish_date", "")
            if pd_str:
                try:
                    pub_date = datetime.strptime(pd_str[:10], "%Y-%m-%d").date()
                except ValueError:
                    pub_date = None

            db.add(ResearchReport(
                info_code=info_code,
                title=r.get("title", ""),
                stock_code=r.get("stock_code", ""),
                stock_name=r.get("stock_name", ""),
                org_name=r.get("org_name", ""),
                publish_date=pub_date,
                rating=r.get("rating", ""),
                industry=r.get("industry", ""),
                researcher=r.get("researcher", ""),
                predict_this_year_eps=r.get("predict_this_year_eps"),
                predict_this_year_pe=r.get("predict_this_year_pe"),
                predict_next_year_eps=r.get("predict_next_year_eps"),
                predict_next_year_pe=r.get("predict_next_year_pe"),
                predict_next_two_year_eps=r.get("predict_next_two_year_eps"),
                predict_next_two_year_pe=r.get("predict_next_two_year_pe"),
                url=r.get("url", ""),
            ))
            added += 1

        db.commit()
        time.sleep(1)

    return {"added": added, "skipped": skipped}


def sync_valuation(db: Session, market: str = "ALL") -> dict:
    """为所有活跃股票回填估值数据（PE/PB/市值/股息率）到最新价格行
    调用 provider.fetch_valuation() 获取当前估值，写入 DailyPrice 表最新行。
    """
    import time as _time

    provider = get_provider()
    stocks = db.query(Stock).filter(Stock.status == "ACTIVE").all()
    if market != "ALL":
        stocks = [s for s in stocks if s.market == market]

    updated = 0
    failed = 0

    for stock in stocks:
        try:
            val = provider.fetch_valuation(stock.symbol)
            if not val:
                failed += 1
                continue

            latest_price = (
                db.query(DailyPrice)
                .filter(DailyPrice.stock_id == stock.id)
                .order_by(DailyPrice.trade_date.desc())
                .first()
            )
            if not latest_price:
                failed += 1
                continue

            if val.get("pe") is not None:
                latest_price.pe = val["pe"]
            if val.get("pb") is not None:
                latest_price.pb = val["pb"]
            if val.get("market_cap") is not None:
                latest_price.market_cap = val["market_cap"]
            if val.get("dividend_yield") is not None:
                latest_price.dividend_yield = val["dividend_yield"]

            updated += 1

            # 每 50 只提交一次，避免大事务
            if updated % 50 == 0:
                db.commit()
                _time.sleep(0.5)

        except Exception as e:
            print(f"  valuation sync failed for {stock.symbol}: {e}")
            failed += 1
            continue

    db.commit()
    return {"updated": updated, "failed": failed, "total": len(stocks)}
