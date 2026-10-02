# -*- coding: utf-8 -*-
"""模拟合约（逐仓多空）行情与业务逻辑。

设计要点：
- 行情：真实交易所公开接口（Binance → OKX → Gate 依次降级），无需 API Key；
  全部失败时返回 None，由调用方跳过本轮结算（不清算、不使用陈旧价格强平）。
- 逐仓：保证金独立，最大亏损即该仓位保证金；名义价值 = 保证金 × 杠杆。
- 结算：后台轮询逐仓判定「强平 → 止损 → 止盈」，亦可用户手动平仓。
"""

import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import httpx

from astrbot.api import logger


# 各行情源：{占位符} 换成对应交易所的币对写法，返回 (价格, 24h 涨跌幅%)
_PROVIDERS: Dict[str, Dict[str, str]] = {
    "binance": {
        "tpl": "https://api.binance.com/api/v3/ticker/24hr?symbol={s}",
        "style": "BTCUSDT",
    },
    "okx": {
        "tpl": "https://www.okx.com/api/v5/market/ticker?instId={s}",
        "style": "BTC-USDT",
    },
    "gate": {
        "tpl": "https://api.gateio.ws/api/v4/spot/tickers?currency_pair={s}",
        "style": "BTC_USDT",
    },
}
_DEFAULT_PROVIDERS = ["binance", "okx", "gate"]


def _pair(symbol: str, style: str) -> str:
    """把 BTC 这类币种切成交易所要求的币对写法。"""
    base = str(symbol or "").strip().upper()
    # 允许用户直接写 BTCUSDT / BTC-USDT / BTC_USDT
    for sep in ("/", "-", "_"):
        if sep in base:
            base = base.split(sep)[0]
    if base.endswith("USDT"):
        base = base[:-4]
    quote = style.replace("{s}", "").upper()
    if "-USDT" in style:
        return f"{base}-USDT"
    if "_USDT" in style:
        return f"{base}_USDT"
    return f"{base}USDT"


class PriceFeed:
    """带降级与缓存的行情获取器。"""

    def __init__(self, config):
        self.config = config
        self._cache: Dict[str, Dict[str, Any]] = {}

    def _providers(self) -> List[str]:
        conf = self.config.get('futures_settings', {}) or {}
        names = conf.get('price_sources') or _DEFAULT_PROVIDERS
        return [n for n in names if n in _PROVIDERS] or _DEFAULT_PROVIDERS

    @staticmethod
    def _parse(provider: str, payload) -> Tuple[Optional[float], Optional[float]]:
        """解析各交易所返回，取出 (价格, 24h 涨跌幅)。"""
        try:
            if provider == "binance":
                price = float(payload.get("lastPrice"))
                chg = float(payload.get("priceChangePercent")) if payload.get("priceChangePercent") else None
                return price, chg
            if provider == "okx":
                row = (payload.get("data") or [{}])[0]
                price = float(row.get("last"))
                open24 = row.get("open24h")
                chg = (price / float(open24) - 1) * 100 if open24 and float(open24) > 0 else None
                return price, chg
            if provider == "gate":
                row = (payload or [{}])[0]
                price = float(row.get("last"))
                chg = float(row.get("change_percentage")) if row.get("change_percentage") else None
                return price, chg
        except (TypeError, ValueError, AttributeError, IndexError):
            return None, None
        return None, None

    async def get_quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        """取实时行情；所有源失败返回 None（不返回陈旧价格，避免误强平）。"""
        sym = str(symbol or "").strip().upper()
        if not sym:
            return None
        for provider in self._providers():
            spec = _PROVIDERS[provider]
            url = spec["tpl"].format(s=_pair(sym, spec["style"]))
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.get(url, timeout=8.0)
                if not resp.is_success:
                    logger.warning(f"[模拟合约] 行情源 {provider} 返回 HTTP {resp.status_code}: {sym}")
                    continue
                price, chg = self._parse(provider, resp.json())
                if price and price > 0:
                    quote = {"symbol": sym, "price": price, "change_pct": chg,
                             "source": provider, "ts": time.time()}
                    self._cache[sym] = quote
                    return quote
                logger.warning(f"[模拟合约] 行情源 {provider} 解析不出价格: {sym}")
            except Exception as e:
                logger.warning(f"[模拟合约] 行情源 {provider} 请求失败: {sym} -> {e}")
        logger.error(f"[模拟合约] 全部行情源均失败，跳过本轮取价: {sym}")
        return None

    async def get_prices(self, symbols) -> Dict[str, float]:
        """批量取价，返回 {币种: 价格}（取不到的币种不在结果里）。"""
        out: Dict[str, float] = {}
        for sym in {str(s).strip().upper() for s in symbols if str(s).strip()}:
            quote = await self.get_quote(sym)
            if quote:
                out[quote["symbol"]] = quote["price"]
        return out

    def cached(self, symbol: str) -> Optional[Dict[str, Any]]:
        """最近一次成功取到的行情（仅供展示参考）。"""
        return self._cache.get(str(symbol or "").strip().upper())


class FuturesEngine:
    """逐仓合约业务逻辑：开仓 / 平仓 / 强平 / 止盈止损 / 盈亏榜。"""

    def __init__(self, config, core, feed: PriceFeed):
        self.config = config
        self.core = core
        self.feed = feed

    # ---------------- 配置读取 ---------------- #

    def conf(self) -> Dict[str, Any]:
        return self.config.get('futures_settings', {}) or {}

    def enabled(self) -> bool:
        return bool(self.conf().get('enabled', False))

    def ratio(self) -> int:
        return self.config.get('binding_settings.quota_display_ratio', 500000) or 500000

    def max_leverage(self) -> int:
        try:
            return max(1, int(self.conf().get('max_leverage', 10)))
        except (TypeError, ValueError):
            return 10

    def fee_rate(self) -> float:
        try:
            return max(0.0, float(self.conf().get('fee_rate', 0.0005)))
        except (TypeError, ValueError):
            return 0.0005

    def mmr(self) -> float:
        try:
            return max(0.0, float(self.conf().get('maintenance_margin_rate', 0.005)))
        except (TypeError, ValueError):
            return 0.005

    def max_positions(self) -> int:
        try:
            return max(1, int(self.conf().get('max_positions_per_user', 3)))
        except (TypeError, ValueError):
            return 3

    def min_margin_raw(self) -> int:
        try:
            display = float(self.conf().get('min_margin_display', 1))
        except (TypeError, ValueError):
            display = 1.0
        return max(1, int(display * self.ratio()))

    def symbols(self) -> List[str]:
        raw = self.conf().get('symbols') or ["BTC", "ETH", "SOL", "DOGE"]
        return [str(s).strip().upper() for s in raw if str(s).strip()]

    # ---------------- 纯计算 ---------------- #

    @staticmethod
    def liquidation_price(entry: float, leverage: int, side: str, mmr: float = 0.005) -> float:
        """逐仓强平价（近似，未计手续费；实际结算以仓位净值为准）。"""
        try:
            entry = float(entry)
            lev = max(1, int(leverage))
        except (TypeError, ValueError):
            return 0.0
        if str(side).upper() == "LONG":
            return max(0.0, entry * (1 - 1.0 / lev + mmr))
        return entry * (1 + 1.0 / lev - mmr)

    @staticmethod
    def pnl_raw(entry: float, price: float, notional_raw: int, side: str) -> int:
        """未计手续费的盈亏（原始额度）。多：涨则盈；空：跌则盈。

        用四舍五入而非截断：浮点误差（如 100×(1-0.9)=9.999999999999998）会让 int() 截断
        成 9，长期累积会悄悄吞掉用户额度。
        """
        try:
            entry = float(entry)
            price = float(price)
            notional = float(notional_raw)
        except (TypeError, ValueError):
            return 0
        if entry <= 0 or price <= 0:
            return 0
        if str(side).upper() == "LONG":
            raw = notional * (price / entry - 1)
        else:
            raw = notional * (1 - price / entry)
        return int(round(raw))

    @staticmethod
    def _fee_raw(notional_raw: int, rate: float) -> int:
        """手续费：同样四舍五入，避免截断导致的手续费偏漏。"""
        try:
            return int(round(float(notional_raw) * float(rate)))
        except (TypeError, ValueError):
            return 0

    def settle_amounts(self, position: Dict[str, Any], price: float) -> Dict[str, int]:
        """按现价结清某仓位：返回毛盈亏、平仓手续费、应退金额（逐仓下限为 0）。"""
        notional = int(position['notional_raw'])
        margin = int(position['margin_raw'])
        pnl = self.pnl_raw(position['entry_price'], price, notional, position['side'])
        close_fee = self._fee_raw(notional, self.fee_rate())
        payout = margin + pnl - close_fee
        if payout < 0:
            payout = 0
        return {"pnl_raw": pnl, "close_fee_raw": close_fee, "payout_raw": payout}

    @staticmethod
    def hit_stop(position: Dict[str, Any], price: float) -> Optional[str]:
        """判定该仓位是否触发强平/止损/止盈，返回原因或 None。"""
        side = str(position['side']).upper()
        try:
            price = float(price)
            entry = float(position['entry_price'])
        except (TypeError, ValueError):
            return None
        liq = float(position.get('liq_price') or 0)
        if liq > 0:
            if side == "LONG" and price <= liq:
                return "LIQUIDATED"
            if side == "SHORT" and price >= liq:
                return "LIQUIDATED"
        sl = position.get('sl_price')
        if sl:
            sl = float(sl)
            if side == "LONG" and price <= sl:
                return "SL"
            if side == "SHORT" and price >= sl:
                return "SL"
        tp = position.get('tp_price')
        if tp:
            tp = float(tp)
            if side == "LONG" and price >= tp:
                return "TP"
            if side == "SHORT" and price <= tp:
                return "TP"
        return None

    # ---------------- 数据库 ---------------- #

    @staticmethod
    def _fmt(dt: datetime) -> str:
        return dt.strftime("%Y-%m-%d %H:%M:%S")

    async def open_count(self, website_user_id: int) -> int:
        row = await self.core.execute_query(
            "SELECT COUNT(*) AS c FROM newapi_futures_positions "
            "WHERE website_user_id = %s AND status = 'OPEN'",
            (website_user_id,), fetch='one'
        )
        return int((row or {}).get('c') or 0)

    async def list_positions(self, website_user_id: int, status: str = 'OPEN') -> List[Dict]:
        rows = await self.core.execute_query(
            "SELECT * FROM newapi_futures_positions WHERE website_user_id = %s AND status = %s "
            "ORDER BY id ASC",
            (website_user_id, status), fetch='all'
        )
        return list(rows or [])

    async def get_position(self, position_id: int) -> Optional[Dict]:
        return await self.core.execute_query(
            "SELECT * FROM newapi_futures_positions WHERE id = %s", (position_id,), fetch='one'
        )

    async def all_open_positions(self) -> List[Dict]:
        rows = await self.core.execute_query(
            "SELECT * FROM newapi_futures_positions WHERE status = 'OPEN' ORDER BY id ASC", fetch='all'
        )
        return list(rows or [])

    # ---------------- 开仓 ---------------- #

    async def open_position(self, *, website_user_id: int, identity: str, symbol: str,
                            side: str, margin_raw: int, leverage: int,
                            tp_price: Optional[float] = None, sl_price: Optional[float] = None,
                            umo: str = "") -> Tuple[str, Dict[str, Any]]:
        """开逐仓。status: OK / DISABLED / SYMBOL_INVALID / PRICE_UNAVAILABLE / LEVERAGE_INVALID
        / MARGIN_TOO_SMALL / TOO_MANY_POSITIONS / INSUFFICIENT / DEDUCT_FAILED / DB_ERROR
        """
        if not self.enabled():
            return "DISABLED", {}
        symbol = str(symbol or "").strip().upper()
        if symbol not in self.symbols():
            return "SYMBOL_INVALID", {"symbols": self.symbols()}
        side = "LONG" if str(side).upper() == "LONG" else "SHORT"
        leverage = int(leverage)
        if leverage < 1 or leverage > self.max_leverage():
            return "LEVERAGE_INVALID", {"max": self.max_leverage()}
        margin_raw = int(margin_raw)
        if margin_raw < self.min_margin_raw():
            return "MARGIN_TOO_SMALL", {"min_display": self.min_margin_raw() / self.ratio()}

        if await self.open_count(website_user_id) >= self.max_positions():
            return "TOO_MANY_POSITIONS", {"max": self.max_positions()}

        quote = await self.feed.get_quote(symbol)
        if not quote:
            return "PRICE_UNAVAILABLE", {"symbol": symbol}
        entry = float(quote["price"])

        fee = self._fee_raw(margin_raw * leverage, self.fee_rate())
        need = margin_raw + fee
        api_user = await self.core.get_api_user_data(website_user_id)
        if not api_user:
            return "INSUFFICIENT", {"balance_display": 0.0}
        balance_raw = int(api_user.get("quota", 0) or 0)
        if balance_raw < need:
            return "INSUFFICIENT", {"balance_display": balance_raw / self.ratio(),
                                    "need_display": need / self.ratio()}

        if not await self.core.manage_user_quota(website_user_id, "subtract", need):
            return "DEDUCT_FAILED", {}

        notional = margin_raw * leverage
        qty = notional / entry
        liq = self.liquidation_price(entry, leverage, side, self.mmr())
        now = self._fmt(datetime.utcnow())
        try:
            pid = await self.core.execute_query(
                "INSERT INTO newapi_futures_positions (website_user_id, identity, symbol, side, leverage, "
                "margin_raw, notional_raw, entry_price, qty, tp_price, sl_price, liq_price, status, "
                "open_fee_raw, open_at, umo) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'OPEN', %s, %s, %s)",
                (website_user_id, identity, symbol, side, leverage, margin_raw, notional,
                 entry, qty, tp_price, sl_price, liq, fee, now, umo or ""),
                return_lastrowid=True
            )
        except Exception as e:
            logger.error(f"[模拟合约] 开仓写库失败，退回扣款: {e}")
            await self.core.manage_user_quota(website_user_id, "add", need)
            return "DB_ERROR", {}
        pid = int(pid or 0)
        if not pid:
            await self.core.manage_user_quota(website_user_id, "add", need)
            return "DB_ERROR", {}
        logger.info(
            f"[模拟合约] 用户 {identity} 开{side} {symbol} {leverage}x 保证金={margin_raw} "
            f"入场={entry} 强平={liq:.6f} #{pid}"
        )
        return "OK", {"id": pid, "symbol": symbol, "side": side, "leverage": leverage,
                      "entry": entry, "margin_raw": margin_raw, "notional_raw": notional,
                      "fee_raw": fee, "liq_price": liq, "qty": qty,
                      "balance_raw": balance_raw - need,
                      "change_pct": quote.get("change_pct"), "source": quote.get("source")}

    # ---------------- 平仓 ---------------- #

    async def close_position(self, position: Dict[str, Any], price: float,
                             reason: str = "MANUAL") -> Tuple[str, Dict[str, Any]]:
        """按给定价格结清仓位并入账。

        顺序为「先占位（条件更新状态）→ 复核 → 再入账」，任一步失败都不会产生
        「状态未变却已入账」的重复入账风险；入账失败时把占位退回 OPEN 以便稍后重试。
        status: OK / NOT_OPEN / DB_ERROR
        """
        if str(position.get('status')) != 'OPEN':
            return "NOT_OPEN", {}
        pid = int(position['id'])
        amounts = self.settle_amounts(position, price)
        liquidated = reason == 'LIQUIDATED' or amounts['payout_raw'] <= 0
        payout = 0 if liquidated else amounts['payout_raw']
        new_status = 'LIQUIDATED' if liquidated else 'CLOSED'
        now = self._fmt(datetime.utcnow())
        net = payout - int(position['margin_raw']) - int(position.get('open_fee_raw') or 0)

        # ① 占位：条件更新（WHERE status='OPEN'），并用 rowcount 判定「是否由本次抢到」
        #    并发场景下只有第一个协程能让该行从 OPEN 变为已平仓，其余 rowcount 必为 0 → 不入账。
        affected = await self.core.execute_query(
            "UPDATE newapi_futures_positions SET status = %s, close_price = %s, close_at = %s, "
            "pnl_raw = %s, close_fee_raw = %s, payout_raw = %s, pnl_net_raw = %s, close_reason = %s "
            "WHERE id = %s AND status = 'OPEN'",
            (new_status, price, now, amounts['pnl_raw'], amounts['close_fee_raw'],
             payout, net, reason, pid)
        )
        # rowcount 为 None 表示 SQL 执行失败（execute_query 吞掉异常返回 None），需与「0 行匹配」区分
        if affected is None or int(affected) <= 0:
            latest = await self.get_position(pid)
            if latest and str(latest.get('status')) != 'OPEN':
                # 已被并发/先前操作平掉：对调用方而言就是「已平仓」，不算错误
                logger.info(f"[模拟合约] 仓位 #{pid} 已被平仓，跳过重复平仓。")
                return "NOT_OPEN", {}
            logger.error(f"[模拟合约] 仓位 #{pid} 平仓占位失败（affected={affected}），本次不入账。")
            return "DB_ERROR", {"reason": "claim_failed", "id": pid}

        # ② 复核：状态必须已是本次写入的终态
        fresh = await self.get_position(pid)
        if not fresh or str(fresh.get('status')) == 'OPEN':
            logger.error(f"[模拟合约] 仓位 #{pid} 占位后状态异常，本次不入账。")
            return "DB_ERROR", {"reason": "claim_verify_failed", "id": pid}

        # ③ 入账；失败则把占位退回 OPEN，交由后续重试
        if payout > 0:
            credited = await self.core.manage_user_quota(
                int(position['website_user_id']), "add", payout
            )
            if not credited:
                logger.error(
                    f"[模拟合约] 仓位 #{pid} 已占位但入账失败，退回 OPEN 以便重试："
                    f"site={position['website_user_id']} payout={payout}"
                )
                await self.core.execute_query(
                    "UPDATE newapi_futures_positions SET status = 'OPEN', close_at = NULL, "
                    "close_price = NULL, payout_raw = NULL, pnl_raw = NULL, pnl_net_raw = NULL, "
                    "close_fee_raw = NULL, close_reason = NULL WHERE id = %s",
                    (pid,)
                )
                return "DB_ERROR", {"reason": "credit_failed", "id": pid}

        logger.info(
            f"[模拟合约] 仓位 #{pid} 平仓({reason}) 平仓价={price} 毛盈亏={amounts['pnl_raw']} "
            f"退还={payout} 净={net}"
        )
        return "OK", {"id": pid, "reason": reason, "exit": price, "liquidated": liquidated,
                      "pnl_raw": amounts['pnl_raw'], "close_fee_raw": amounts['close_fee_raw'],
                      "payout_raw": payout, "net_raw": net, "margin_raw": int(position['margin_raw']),
                      "symbol": position['symbol'], "side": position['side'],
                      "leverage": position['leverage'], "entry": position['entry_price']}

    # ---------------- 轮询结算 ---------------- #

    async def settle_tick(self) -> List[Dict[str, Any]]:
        """后台一轮结算：对每个 OPEN 仓位取价并判定强平/止损/止盈。

        返回本次被自动平掉的仓位结果列表（供群播报）。
        """
        if not self.enabled():
            return []
        positions = await self.all_open_positions()
        if not positions:
            return []
        prices = await self.feed.get_prices([p['symbol'] for p in positions])
        results = []
        for pos in positions:
            price = prices.get(str(pos['symbol']).upper())
            if not price:
                continue                      # 本轮取不到价 → 跳过，绝不按陈旧价格强平
            reason = self.hit_stop(pos, price)
            if not reason:
                continue
            status, details = await self.close_position(pos, price, reason)
            if status == "OK":
                results.append({**details, "umo": pos.get('umo') or "",
                                "identity": pos.get('identity') or "",
                                "website_user_id": pos.get('website_user_id')})
        return results

    # ---------------- 盈亏榜 ---------------- #

    async def today_pnl(self, limit: int = 10) -> List[Dict[str, Any]]:
        """今日已平仓仓位的净盈亏排行（含强平）。

        注意时区：`close_at` 统一按 UTC 存字符串，故不能直接比「本地日期」字符串，
        需把「本地零点」换算回 UTC 再比较，否则本地已跨日而 UTC 未跨日时会查不到数据。
        """
        offset = float(self.config.get('check_in_settings.timezone_offset_hours', 0) or 0)
        local_now = datetime.utcnow() + timedelta(hours=offset)
        local_midnight = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        cutoff_utc = local_midnight - timedelta(hours=offset)
        rows = await self.core.execute_query(
            "SELECT identity, SUM(pnl_net_raw) AS net, COUNT(*) AS trades, "
            "SUM(CASE WHEN status = 'LIQUIDATED' THEN 1 ELSE 0 END) AS liquidations "
            "FROM newapi_futures_positions WHERE status IN ('CLOSED','LIQUIDATED') "
            "AND close_at >= %s GROUP BY identity ORDER BY net DESC LIMIT %s",
            (self._fmt(cutoff_utc), int(limit)), fetch='all'
        )
        return [{"identity": r['identity'], "net_raw": int(r['net'] or 0),
                 "trades": int(r['trades'] or 0),
                 "liquidations": int(r['liquidations'] or 0)} for r in (rows or [])]
