# heist_logic.py

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
        logger.info("[HeistLogic] Initialized.")

    async def execute_heist(self, robber_qq_id: int, victim_identifier: int) -> Tuple[str, Dict[str, Any]]:
        """
        执行一次“打劫”行动。
        """
        # 1. 条件校验
        validation_status, details = await self._validate_heist_conditions(robber_qq_id, victim_identifier)
        if validation_status != "VALID":
            return validation_status, details

        robber_site_id = details["robber_site_id"]
        victim_site_id = details["victim_site_id"]
        heist_conf = details["heist_conf"]

        # 2. 结果判定
        outcome, amount = self._determine_heist_outcome(heist_conf)

        # 3. 执行划转和记录
        return await self._execute_heist_transfer(
            outcome, amount, robber_qq_id, robber_site_id, victim_site_id
        )

    async def _validate_heist_conditions(self, robber_qq_id: int, victim_identifier: int) -> Tuple[str, Dict[str, Any]]:
        """打劫行动的前置检查。"""
        heist_conf = self.config.get('heist_settings', {})
        if not heist_conf.get('enabled', False):
            return "DISABLED", {}

        robber_binding = await self.core.get_user_by_qq(robber_qq_id)
        if not robber_binding:
            return "ROBBER_NOT_BOUND", {}

        # 新增：冷却时间检查
        cooldown_seconds = heist_conf.get('cooldown_seconds', 3600)
        if cooldown_seconds > 0:
            last_heist_time = await self.core.get_last_heist_time_by_qq(robber_qq_id)
            if last_heist_time:
                time_since_last_heist = (datetime.utcnow() - last_heist_time).total_seconds()
                if time_since_last_heist < cooldown_seconds:
                    remaining_time = int(cooldown_seconds - time_since_last_heist)
                    return "COOLDOWN_ACTIVE", {"remaining_time": remaining_time}

        id_type, victim_binding = await self.core.lookup_binding(victim_identifier)
        if id_type == "NOT_FOUND":
            return "VICTIM_NOT_FOUND", {}

        robber_site_id = robber_binding['website_user_id']
        victim_site_id = victim_binding['website_user_id']

        if robber_site_id == victim_site_id:
            return "CANNOT_ROB_SELF", {}

        max_attempts = heist_conf.get('max_attempts_per_day', 1)
        robber_attempts = await self.core.get_today_heist_counts_by_qq(robber_qq_id)
        if robber_attempts >= max_attempts:
            return "ATTEMPTS_EXCEEDED", {}

        max_defenses = heist_conf.get('max_defenses_per_day', 3)
        victim_defenses = await self.core.get_today_defenses_count_by_id(victim_site_id)
        if victim_defenses >= max_defenses:
            return "DEFENSES_EXCEEDED", {"victim_id": victim_site_id}
        
        return "VALID", {"robber_site_id": robber_site_id, "victim_site_id": victim_site_id, "heist_conf": heist_conf}

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
                await self.core.log_heist_attempt(robber_qq_id, victim_site_id, "FAILURE", -raw_penalty)
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
                await self.core.log_heist_attempt(robber_qq_id, victim_site_id, final_outcome, raw_gain)
                return final_outcome, {"gain": actual_gain}

        return "API_ERROR", {}
