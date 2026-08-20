# heist_logic.py

import asyncio
import random
from datetime import datetime
from typing import Tuple, Dict, Any, Optional

from astrbot.api import logger, AstrBotConfig
from .newapi_utils import NewApiCore

class HeistLogic:
    """
    处理“打劫”功能相关逻辑。
    """
    def __init__(self, config: AstrBotConfig, core: NewApiCore):
        self.config = config
        self.core = core
        # 打劫并发锁：按 robber_qq_id 与 victim_website_id 分别加锁，串行化次数/冷却/防御校验与划转，杜绝 TOCTOU
        self._heist_locks: dict[int, asyncio.Lock] = {}
        logger.info("[HeistLogic] Initialized.")

    def _get_heist_lock(self, key: int) -> asyncio.Lock:
        """获取打劫锁（懒创建；纯同步无 await，事件循环内天然原子）。"""
        if key not in self._heist_locks:
            self._heist_locks[key] = asyncio.Lock()
        return self._heist_locks[key]

    async def execute_heist(self, robber_qq_id: int, victim_identifier: int) -> Tuple[str, Dict[str, Any]]:
        """
        执行一次“打劫”行动。
        """
        # 1. 解析参与方与结构性校验（绑定查找 / 自抢 / 功能开关），无并发竞态
        status, details = await self._resolve_heist_parties(robber_qq_id, victim_identifier)
        if status != "VALID":
            return status, details

        robber_site_id = details["robber_site_id"]
        victim_site_id = details["victim_site_id"]
        heist_conf = details["heist_conf"]

        # 2. 按 robber_qq 与 victim_site 升序加锁（同一把锁只取一次），串行化次数/冷却/防御校验与资金划转
        keys = sorted(set([robber_qq_id, victim_site_id]))
        locks = [self._get_heist_lock(k) for k in keys]
        for lk in locks:
            await lk.acquire()
        try:
            # 3. 锁内重做次数/冷却/防御校验（锁外初次解析后可能已被并发改变）
            lstatus, ldetails = await self._check_heist_limits(robber_qq_id, victim_site_id, heist_conf)
            if lstatus != "VALID":
                return lstatus, ldetails
            # 4. 结果判定 + 划转 + 日志
            outcome, amount = self._determine_heist_outcome(heist_conf)
            return await self._execute_heist_transfer(
                outcome, amount, robber_qq_id, robber_site_id, victim_site_id
            )
        finally:
            for lk in reversed(locks):
                lk.release()

    async def _resolve_heist_parties(self, robber_qq_id: int, victim_identifier: int) -> Tuple[str, Dict[str, Any]]:
        """解析打劫参与方与结构性校验（不含次数/冷却/防御等竞态敏感的计数检查）。"""
        heist_conf = self.config.get('heist_settings', {})
        if not heist_conf.get('enabled', False):
            return "DISABLED", {}

        robber_binding = await self.core.get_user_by_qq(robber_qq_id)
        if not robber_binding:
            return "ROBBER_NOT_BOUND", {}

        id_type, victim_binding = await self.core.lookup_binding(victim_identifier)
        if id_type == "NOT_FOUND":
            return "VICTIM_NOT_FOUND", {}

        robber_site_id = robber_binding['website_user_id']
        victim_site_id = victim_binding['website_user_id']

        if robber_site_id == victim_site_id:
            return "CANNOT_ROB_SELF", {}

        return "VALID", {
            "robber_site_id": robber_site_id,
            "victim_site_id": victim_site_id,
            "heist_conf": heist_conf,
        }

    async def _check_heist_limits(self, robber_qq_id: int, victim_site_id: int, heist_conf: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
        """打劫次数/冷却/受害者防御上限校验（竞态敏感，须在锁内调用）。"""
        # 冷却时间检查
        cooldown_seconds = heist_conf.get('cooldown_seconds', 3600)
        if cooldown_seconds > 0:
            last_heist_time = await self.core.get_last_heist_time_by_qq(robber_qq_id)
            if last_heist_time:
                time_since_last_heist = (datetime.utcnow() - last_heist_time).total_seconds()
                if time_since_last_heist < cooldown_seconds:
                    remaining_time = int(cooldown_seconds - time_since_last_heist)
                    return "COOLDOWN_ACTIVE", {"remaining_time": remaining_time}

        # 抢劫者每日次数上限
        max_attempts = heist_conf.get('max_attempts_per_day', 1)
        robber_attempts = await self.core.get_today_heist_counts_by_qq(robber_qq_id)
        if robber_attempts >= max_attempts:
            return "ATTEMPTS_EXCEEDED", {}

        # 受害者每日被抢（防御）上限
        max_defenses = heist_conf.get('max_defenses_per_day', 3)
        victim_defenses = await self.core.get_today_defenses_count_by_id(victim_site_id)
        if victim_defenses >= max_defenses:
            return "DEFENSES_EXCEEDED", {"victim_id": victim_site_id}

        return "VALID", {}

    def _determine_heist_outcome(self, heist_conf: Dict[str, Any]) -> Tuple[str, float]:
        """判定打劫成败、是否暴击，并计算金额。"""
        if random.random() < heist_conf.get('failure_chance', 0.5):
            penalty_display = heist_conf.get('failure_penalty', 100.0)
            return "FAILURE", penalty_display
        else:
            min_display = heist_conf.get('min_amount', 5.0)
            max_display = heist_conf.get('max_amount', 40.0)
            # 确保min_display不大于max_display
            if min_display > max_display:
                min_display, max_display = max_display, min_display
            base_display_gain = random.uniform(min_display, max_display)
            
            is_critical = random.random() < heist_conf.get('critical_chance', 0.1)
            final_display_gain = base_display_gain * 2 if is_critical else base_display_gain
            
            outcome = "CRITICAL" if is_critical else "SUCCESS"
            return outcome, final_display_gain

    async def _execute_heist_transfer(
        self, outcome: str, amount: float, robber_qq_id: int, robber_site_id: int, victim_site_id: int
    ) -> Tuple[str, Dict[str, Any]]:
        """调用核心接口划转资金并记录日志。"""
        if outcome == "FAILURE":
            transfer_success, actual_penalty, raw_penalty = await self.core.transfer_display_quota(
                from_user_id=robber_site_id,
                to_user_id=victim_site_id,
                display_amount=amount,
                allow_partial=True
            )
            if transfer_success:
                try:
                    await self.core.log_heist_attempt(robber_qq_id, victim_site_id, "FAILURE", -raw_penalty)
                except Exception as e:
                    logger.error(f"打劫失败日志写入失败（资金已划转，仅日志丢失）: {e}", exc_info=True)
                return "FAILURE", {"penalty": actual_penalty}
        else:  # SUCCESS or CRITICAL
            base_amount = amount / 2 if outcome == "CRITICAL" else amount
            transfer_success, actual_gain, raw_gain = await self.core.transfer_display_quota(
                from_user_id=victim_site_id,
                to_user_id=robber_site_id,
                display_amount=amount,
                allow_partial=True
            )
            if transfer_success:
                # 暴击时，若实际获得大于基础获得额度，才算暴劫成功
                final_outcome = "CRITICAL" if outcome == "CRITICAL" and actual_gain > base_amount else "SUCCESS"
                try:
                    await self.core.log_heist_attempt(robber_qq_id, victim_site_id, final_outcome, raw_gain)
                except Exception as e:
                    logger.error(f"打劫成功日志写入失败（资金已划转，仅日志丢失）: {e}", exc_info=True)
                return final_outcome, {"gain": actual_gain}

        return "API_ERROR", {}
