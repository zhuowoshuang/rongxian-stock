"""
混合数据源 - 东方财富 + 腾讯 API
东方财富: 股票列表、财务数据
腾讯: 日线行情、实时行情、市场指数
"""
import re
import json
import subprocess
import threading
import pandas as pd
import httpx
from datetime import date, datetime, timedelta
from typing import Optional
from urllib.parse import urlencode
from app.data_providers.base import DataProviderBase

# 线程安全的 httpx 客户端（每个线程独立实例）
_thread_local = threading.local()


def _get_client() -> httpx.Client:
    """获取当前线程的 httpx 客户端（懒初始化，避免跨线程共享连接池）"""
    if not hasattr(_thread_local, "client"):
        _thread_local.client = httpx.Client(
            proxy=None,
            follow_redirects=True,
            timeout=15,
            trust_env=False,  # 不读取环境变量中的代理设置
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
        )
    return _thread_local.client


import time as _time
import logging as _logging

_logger = _logging.getLogger(__name__)


def _retry(func, *args, retries=2, delay=1.0, **kwargs):
    """重试包装器：失败后等待再重试"""
    last_exc = None
    for attempt in range(retries + 1):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            last_exc = e
            if attempt < retries:
                _logger.warning(f"Retry {attempt+1}/{retries} after {delay}s: {e}")
                _time.sleep(delay)
    raise last_exc


def _curl_get(url: str, timeout: int = 15) -> dict:
    """使用 curl 子进程发送请求（push2 API 被 httpx TLS 指纹拦截，需用 curl）"""
    result = subprocess.run(
        ["curl", "-s", "--noproxy", "*", "--max-time", str(timeout), url],
        capture_output=True, text=True, timeout=timeout + 5,
        encoding="utf-8", errors="replace",
    )
    if result.returncode != 0:
        raise ConnectionError(f"curl failed: {result.stderr[:200]}")
    return json.loads(result.stdout)


def _http_get(url: str, timeout: int = 15) -> dict:
    """发送 HTTP GET 请求并返回 JSON"""
    resp = _get_client().get(url, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def _http_get_text(url: str, timeout: int = 15) -> str:
    """发送 HTTP GET 请求并返回文本"""
    resp = _get_client().get(url, timeout=timeout)
    resp.raise_for_status()
    return resp.text


class EastMoneyProvider(DataProviderBase):
    """混合数据源：东方财富 + 腾讯（全部通过 curl）"""

    # ==================== 股票列表 (东方财富) ====================

    def fetch_stock_list(self, market: str) -> pd.DataFrame:
        if market == "A_SHARE":
            return self._fetch_a_share_list()
        else:
            return self._fetch_hk_list()

    def _fetch_a_share_list(self) -> pd.DataFrame:
        url = "https://82.push2.eastmoney.com/api/qt/clist/get"
        params = urlencode({
            "pn": 1, "pz": 5000, "po": 1, "np": 1,
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "fltt": 2, "invt": 2, "fid": "f12",
            "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048",
            "fields": "f12,f14,f2,f3,f9,f23,f115,f116,f117",
        })
        data = _http_get(f"{url}?{params}")
        items = data.get("data", {}).get("diff", [])
        rows = []
        for item in items:
            code = item.get("f12", "")
            name = item.get("f14", "")
            if not code or not name:
                continue
            exchange = "SH" if code.startswith(("6", "5")) else "SZ"
            rows.append({
                "symbol": code, "name": name, "market": "A_SHARE",
                "exchange": exchange, "industry": "", "sector": "",
            })
        return pd.DataFrame(rows)

    def _fetch_hk_list(self) -> pd.DataFrame:
        url = "https://82.push2.eastmoney.com/api/qt/clist/get"
        params = urlencode({
            "pn": 1, "pz": 3000, "po": 1, "np": 1,
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "fltt": 2, "invt": 2, "fid": "f12",
            "fs": "m:128+t:3,m:128+t:4,m:128+t:1,m:128+t:2",
            "fields": "f12,f14,f2,f3",
        })
        data = _http_get(f"{url}?{params}")
        items = data.get("data", {}).get("diff", [])
        rows = []
        for item in items:
            code = item.get("f12", "")
            name = item.get("f14", "")
            if not code or not name:
                continue
            rows.append({
                "symbol": code, "name": name, "market": "HK",
                "exchange": "HK", "industry": "", "sector": "",
            })
        return pd.DataFrame(rows)

    # ==================== 日线行情 (腾讯) ====================

    def fetch_daily_prices(self, symbol: str, start_date: date, end_date: date) -> pd.DataFrame:
        if len(symbol) == 5 and symbol.isdigit():
            return self._fetch_hk_daily(symbol, start_date, end_date)
        else:
            return self._fetch_a_daily(symbol, start_date, end_date)

    def _tencent_code(self, symbol: str) -> str:
        if len(symbol) == 5 and symbol.isdigit():
            return f"hk{symbol}"
        elif symbol.startswith(("6", "5")):
            return f"sh{symbol}"
        else:
            return f"sz{symbol}"

    def _fetch_a_daily(self, symbol: str, start_date: date, end_date: date) -> pd.DataFrame:
        # 优先用腾讯 API，失败则用东方财富 K线 API，再失败用新浪
        tc = self._tencent_code(symbol)
        url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={tc},day,{start_date},{end_date},500,qfq"
        try:
            data = _retry(_http_get, url)
            stock_data = data.get("data", {}).get(tc, {})
            klines = stock_data.get("qfqday", stock_data.get("day", []))
            if klines:
                return self._parse_klines(klines)
        except Exception:
            pass

        # fallback: 东方财富 K线 API
        df = self._fetch_eastmoney_kline(symbol, start_date, end_date)
        if not df.empty:
            return df

        # fallback: 新浪财经 K线 API
        return self._fetch_sina_kline(symbol, start_date, end_date)

    def _fetch_hk_daily(self, symbol: str, start_date: date, end_date: date) -> pd.DataFrame:
        tc = f"hk{symbol}"
        url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={tc},day,{start_date},{end_date},500,"
        try:
            data = _http_get(url)
            stock_data = data.get("data", {}).get(tc, {})
            klines = stock_data.get("day", stock_data.get("qfqday", []))
            if klines:
                return self._parse_klines(klines)
        except Exception:
            pass

        # fallback: 东方财富 K线 API (港股用 116 前缀)
        df = self._fetch_eastmoney_kline(symbol, start_date, end_date, market="HK")
        if not df.empty:
            return df

        # fallback: 新浪财经 K线 API
        return self._fetch_sina_kline(symbol, start_date, end_date)

    def _fetch_sina_kline(self, symbol: str, start_date: date, end_date: date) -> pd.DataFrame:
        """新浪财经 K线 API（备用数据源，不走代理）"""
        tc = self._tencent_code(symbol)
        # 计算需要的数据天数
        days = max(30, (end_date - start_date).days + 10)
        url = (
            f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
            f"CN_MarketData.getKLineData?symbol={tc}&scale=240&ma=no&datalen={days}"
        )
        try:
            req = __import__('urllib.request', fromlist=['Request']).Request(
                url, headers={"User-Agent": "Mozilla/5.0"}
            )
            resp = __import__('urllib.request', fromlist=['urlopen']).urlopen(req, timeout=15)
            text = resp.read().decode("utf-8")
            data = json.loads(text)
            if not data:
                return pd.DataFrame()

            rows = []
            prev_close = None
            for item in data:
                trade_date = pd.to_datetime(item["day"]).date()
                if trade_date < start_date or trade_date > end_date:
                    continue
                close = float(item["close"])
                rows.append({
                    "trade_date": trade_date,
                    "open": float(item["open"]),
                    "close": close,
                    "high": float(item["high"]),
                    "low": float(item["low"]),
                    "volume": float(item["volume"]),
                    "turnover": 0,
                    "turnover_rate": 0,
                    "pre_close": prev_close,
                    "market_cap": None,
                    "pe": None,
                    "pb": None,
                    "dividend_yield": None,
                })
                prev_close = close
            return pd.DataFrame(rows)
        except Exception:
            return pd.DataFrame()

    def _fetch_eastmoney_kline(self, symbol: str, start_date: date, end_date: date, market: str = "A_SHARE") -> pd.DataFrame:
        """东方财富 K线 API（备用数据源，push2his 被 httpx TLS 拦截，用 curl）"""
        if market == "HK":
            secid = f"116.{symbol}"
        elif symbol.startswith(("6", "5")):
            secid = f"1.{symbol}"
        else:
            secid = f"0.{symbol}"

        beg = start_date.strftime("%Y%m%d")
        end = end_date.strftime("%Y%m%d")
        url = (
            f"https://push2his.eastmoney.com/api/qt/stock/kline/get?"
            f"secid={secid}&fields1=f1,f2,f3,f4,f5,f6"
            f"&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
            f"&klt=101&fqt=1&beg={beg}&end={end}"
        )
        try:
            data = _retry(_curl_get, url, retries=2, delay=2.0)
            klines_str = data.get("data", {}).get("klines", [])
            if not klines_str:
                return pd.DataFrame()

            rows = []
            prev_close = None
            for line in klines_str:
                parts = line.split(",")
                if len(parts) < 7:
                    continue
                close = float(parts[2])
                rows.append({
                    "trade_date": pd.to_datetime(parts[0]).date(),
                    "open": float(parts[1]),
                    "close": close,
                    "high": float(parts[3]),
                    "low": float(parts[4]),
                    "volume": float(parts[5]),
                    "turnover": float(parts[6]) if len(parts) > 6 else 0,
                    "turnover_rate": float(parts[10]) if len(parts) > 10 else 0,
                    "pre_close": prev_close,
                    "market_cap": None,
                    "pe": None,
                    "pb": None,
                    "dividend_yield": None,
                })
                prev_close = close
            return pd.DataFrame(rows)
        except Exception:
            return pd.DataFrame()

    def _parse_klines(self, klines: list) -> pd.DataFrame:
        rows = []
        prev_close = None
        for line in klines:
            if len(line) < 6:
                continue
            close = float(line[2])
            rows.append({
                "trade_date": pd.to_datetime(line[0]).date(),
                "open": float(line[1]),
                "close": close,
                "high": float(line[3]),
                "low": float(line[4]),
                "volume": float(line[5]),
                "turnover": 0,
                "turnover_rate": 0,
                "pre_close": prev_close,
                "market_cap": None,
                "pe": None,
                "pb": None,
                "dividend_yield": None,
            })
            prev_close = close
        return pd.DataFrame(rows)

    # ==================== 实时行情 (腾讯) ====================

    def fetch_realtime_quote(self, symbol: str) -> dict:
        tc = self._tencent_code(symbol)
        url = f"https://qt.gtimg.cn/q={tc}"
        text = _http_get_text(url)

        match = re.search(r'"([^"]*)"', text)
        if not match:
            return {}
        fields = match.group(1).split("~")
        if len(fields) < 50:
            return {}

        def _safe_field(idx):
            """安全提取浮点字段（港股某些字段是文本如 'TENCENT'）"""
            if idx < len(fields) and fields[idx]:
                try:
                    return float(fields[idx])
                except (ValueError, TypeError):
                    return None
            return None

        try:
            return {
                "close": _safe_field(3),
                "high": _safe_field(33),
                "low": _safe_field(34),
                "open": _safe_field(5),
                "volume": _safe_field(6),
                "turnover": None,
                "pe": _safe_field(39),
                "pb": _safe_field(46) if len(fields) > 46 else None,
                "market_cap": _safe_field(45),
                "change_pct": _safe_field(32),
            }
        except (ValueError, IndexError):
            return {}

    # ==================== 财务数据 (东方财富) ====================

    def fetch_financial_metrics(self, symbol: str) -> pd.DataFrame:
        if len(symbol) == 5 and symbol.isdigit():
            return pd.DataFrame()
        return self._fetch_a_financial(symbol)

    def _fetch_a_financial(self, symbol: str) -> pd.DataFrame:
        code = f"SH{symbol}" if symbol.startswith(("6", "5")) else f"SZ{symbol}"
        url = f"https://emweb.securities.eastmoney.com/PC_HSF10/NewFinanceAnalysis/ZYZBAjaxNew?type=0&code={code}"
        try:
            data = _retry(_http_get, url, retries=2, delay=1.0)
        except Exception:
            return pd.DataFrame()

        reports = data.get("data", [])
        rows = []
        for r in reports[:8]:
            # 将每股经营现金流转换为总值（亿）
            # 通过 净利润 / EPS 推算总股本，再乘以每股现金流
            mgjyxjje = self._safe_float(r.get("MGJYXJJE"))  # 每股经营现金流(元)
            net_profit = self._safe_float(r.get("PARENTNETPROFIT"))  # 净利润(元)
            eps = self._safe_float(r.get("EPSJB"))  # 每股收益(元)
            if mgjyxjje is not None and net_profit and eps and eps != 0:
                total_shares = net_profit / eps  # 总股本
                operating_cashflow_yi = round(mgjyxjje * total_shares / 1e8, 2)  # 转换为亿
            else:
                operating_cashflow_yi = None

            rows.append({
                "report_period": r.get("REPORT_DATE_NAME", ""),
                "revenue": self._safe_div(r.get("TOTALOPERATEREVE"), 1e8),
                "revenue_yoy": self._safe_float(r.get("TOTALOPERATEREVETZ")),
                "net_profit": self._safe_div(r.get("PARENTNETPROFIT"), 1e8),
                "net_profit_yoy": self._safe_float(r.get("PARENTNETPROFITTZ")),
                "gross_margin": self._safe_float(r.get("XSMLL")),
                "net_margin": self._safe_float(r.get("XSJLL")),
                "roe": self._safe_float(r.get("ROEJQ")),
                "roa": self._safe_float(r.get("ROA")),
                "debt_ratio": self._safe_float(r.get("ZCFZL")),
                "operating_cashflow": operating_cashflow_yi,
                "free_cashflow": None,
                "eps": self._safe_float(r.get("EPSJB")),
                "book_value_per_share": self._safe_float(r.get("BPS")),
            })
        return pd.DataFrame(rows)

    def _safe_float(self, val) -> Optional[float]:
        if val is None or val == "-" or val == "":
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None

    def _safe_div(self, val, divisor) -> Optional[float]:
        f = self._safe_float(val)
        if f is None:
            return None
        return f / divisor

    # ==================== 市场指数 (腾讯) ====================

    # 指数数据缓存（避免每次都请求慢速 API）
    _index_cache: dict = {}
    _index_cache_time: float = 0

    def fetch_market_index(self, market: str) -> list:
        import time as _time
        now = _time.time()

        # 缓存 60 秒
        if market in self._index_cache and now - self._index_cache_time < 60:
            return self._index_cache[market]

        if market == "A_SHARE":
            codes = [
                ("sh000001", "上证指数", "000001.SH"),
                ("sz399001", "深证成指", "399001.SZ"),
                ("sz399006", "创业板指", "399006.SZ"),
            ]
        else:
            codes = [
                ("hkHSI", "恒生指数", "HSI"),
                ("hkHSTECH", "恒生科技", "HSTECH"),
            ]

        tc_codes = ",".join(c[0] for c in codes)
        url = f"https://qt.gtimg.cn/q={tc_codes}"
        try:
            text = _http_get_text(url, timeout=5)  # 指数用短超时
        except Exception:
            # fallback: 用东方财富 API 获取指数
            return self._fetch_index_from_eastmoney(codes)

        indices = []
        for tc, name, code in codes:
            pattern = f'v_{tc}="([^"]*)"'
            match = re.search(pattern, text)
            if not match:
                indices.append({"name": name, "code": code, "current": 0, "change": 0, "change_pct": 0})
                continue
            fields = match.group(1).split("~")
            try:
                current = float(fields[3]) if fields[3] else 0
                pre_close = float(fields[4]) if fields[4] else 0
                change = current - pre_close
                change_pct = float(fields[32]) if len(fields) > 32 and fields[32] else 0
                indices.append({
                    "name": name,
                    "code": code,
                    "current": current,
                    "change": round(change, 2),
                    "change_pct": round(change_pct, 2),
                })
            except (ValueError, IndexError):
                indices.append({"name": name, "code": code, "current": 0, "change": 0, "change_pct": 0})

        # 更新缓存
        self._index_cache[market] = indices
        self._index_cache_time = _time.time()
        return indices

    def _fetch_index_from_eastmoney(self, codes: list) -> list:
        """东方财富指数 API（fallback）"""
        indices = []
        for tc, name, code in codes:
            # 东方财富指数代码
            if code.startswith("000001"):
                secid = "1.000001"
            elif code.startswith("399001"):
                secid = "0.399001"
            elif code.startswith("399006"):
                secid = "0.399006"
            elif code == "HSI":
                secid = "100.HSI"
            elif code == "HSTECH":
                secid = "100.HSTECH"
            else:
                indices.append({"name": name, "code": code, "current": 0, "change": 0, "change_pct": 0})
                continue

            url = f"https://push2.eastmoney.com/api/qt/stock/get?secid={secid}&fields=f43,f44,f45,f46,f47,f48,f57,f58,f169,f170"
            try:
                data = _curl_get(url, timeout=5)
                d = data.get("data", {})
                if d:
                    current = self._safe_float(d.get("f43"))
                    change = self._safe_float(d.get("f169"))
                    change_pct = self._safe_float(d.get("f170"))
                    indices.append({
                        "name": name,
                        "code": code,
                        "current": round(current / 100, 2) if current else 0,
                        "change": round(change / 100, 2) if change else 0,
                        "change_pct": round(change_pct / 100, 2) if change_pct else 0,
                    })
                else:
                    indices.append({"name": name, "code": code, "current": 0, "change": 0, "change_pct": 0})
            except Exception:
                indices.append({"name": name, "code": code, "current": 0, "change": 0, "change_pct": 0})
        return indices

    # ==================== 估值数据 (东方财富) ====================

    def fetch_valuation(self, symbol: str) -> dict:
        """获取单只股票的 PE/PB/市值等估值数据"""
        if len(symbol) == 5 and symbol.isdigit():
            return self._fetch_hk_valuation(symbol)
        return self._fetch_a_valuation(symbol)

    def _fetch_a_valuation(self, symbol: str) -> dict:
        """A股估值数据（优先 push2 API，失败则用腾讯实时行情）"""
        if symbol.startswith(("6", "5")):
            secid = f"1.{symbol}"
        else:
            secid = f"0.{symbol}"
        url = (
            f"https://push2.eastmoney.com/api/qt/stock/get?"
            f"secid={secid}&fields=f57,f58,f43,f162,f167,f116,f117,f173"
        )
        try:
            data = _curl_get(url)
            d = data.get("data", {})
            if d:
                pe_raw = self._safe_float(d.get("f162"))
                pb_raw = self._safe_float(d.get("f167"))
                return {
                    "pe": round(pe_raw / 100, 2) if pe_raw is not None else None,
                    "pb": round(pb_raw / 100, 2) if pb_raw is not None else None,
                    "market_cap": self._safe_div(d.get("f116"), 1e8),
                    "float_market_cap": self._safe_div(d.get("f117"), 1e8),
                    "dividend_yield": self._safe_float(d.get("f173")),
                }
        except Exception:
            pass

        # fallback: 用腾讯实时行情获取 PE/PB/市值
        quote = self.fetch_realtime_quote(symbol)
        if quote:
            return {
                "pe": quote.get("pe"),
                "pb": quote.get("pb"),
                "market_cap": quote.get("market_cap"),
                "float_market_cap": None,
                "dividend_yield": None,
            }
        return {}

    def _fetch_hk_valuation(self, symbol: str) -> dict:
        """港股估值数据（优先 push2 API，失败则用腾讯实时行情）"""
        secid = f"116.{symbol}"
        url = (
            f"https://push2.eastmoney.com/api/qt/stock/get?"
            f"secid={secid}&fields=f57,f58,f43,f162,f167,f116,f117,f173"
        )
        try:
            data = _curl_get(url)
            d = data.get("data", {})
            if d:
                pe_raw = self._safe_float(d.get("f162"))
                pb_raw = self._safe_float(d.get("f167"))
                return {
                    "pe": round(pe_raw / 100, 2) if pe_raw is not None else None,
                    "pb": round(pb_raw / 100, 2) if pb_raw is not None else None,
                    "market_cap": self._safe_div(d.get("f116"), 1e8),
                    "float_market_cap": self._safe_div(d.get("f117"), 1e8),
                    "dividend_yield": self._safe_float(d.get("f173")),
                }
        except Exception:
            pass

        # fallback: 用腾讯实时行情获取 PE/PB/市值
        quote = self.fetch_realtime_quote(symbol)
        if quote:
            return {
                "pe": quote.get("pe"),
                "pb": quote.get("pb"),
                "market_cap": quote.get("market_cap"),
                "float_market_cap": None,
                "dividend_yield": None,
            }
        return {}

    # ==================== 研究报告 (东方财富) ====================

    def fetch_reports(self, symbol: str = None, page: int = 1, page_size: int = 20) -> dict:
        """
        获取券商研究报告列表
        symbol: 股票代码（None 则获取全市场最新报告）
        返回: {"total": int, "reports": [...]}
        """
        from datetime import datetime, timedelta
        end_time = datetime.now().strftime("%Y-%m-%d")
        start_time = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")

        params = {
            "industryCode": "*",
            "pageNo": page,
            "pageSize": page_size,
            "beginTime": start_time,
            "endTime": end_time,
            "qType": 0,
        }
        if symbol:
            params["code"] = symbol

        param_str = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"https://reportapi.eastmoney.com/report/list?{param_str}"

        try:
            data = _http_get(url)
        except Exception as e:
            return {"total": 0, "reports": [], "error": str(e)}

        reports = []
        for r in data.get("data", []):
            reports.append({
                "title": r.get("title", ""),
                "stock_name": r.get("stockName", ""),
                "stock_code": r.get("stockCode", ""),
                "org_name": r.get("orgSName", ""),
                "publish_date": r.get("publishDate", "")[:10],
                "rating": r.get("emRatingName", ""),
                "industry": r.get("indvInduName", ""),
                "researcher": r.get("researcher", ""),
                "info_code": r.get("infoCode", ""),
                "predict_this_year_eps": self._safe_float(r.get("predictThisYearEps")),
                "predict_this_year_pe": self._safe_float(r.get("predictThisYearPe")),
                "predict_next_year_eps": self._safe_float(r.get("predictNextYearEps")),
                "predict_next_year_pe": self._safe_float(r.get("predictNextYearPe")),
                "predict_next_two_year_eps": self._safe_float(r.get("predictNextTwoYearEps")),
                "predict_next_two_year_pe": self._safe_float(r.get("predictNextTwoYearPe")),
                "url": f"https://data.eastmoney.com/report/info/{r.get('infoCode', '')}.html",
            })

        return {
            "total": data.get("hits", 0),
            "reports": reports,
        }

    # ==================== 新闻 ====================

    def fetch_news(self, symbol: str, limit: int = 10) -> list:
        return []
