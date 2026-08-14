import os
import asyncio
import httpx
import aiomysql
import random
from datetime import datetime, timedelta
from typing import Optional, Any, Dict, Tuple
from dotenv import load_dotenv, find_dotenv

from astrbot.api import logger, AstrBotConfig

class NewApiCore:
    """
    NewAPI 核心工具类 (插件配置 + .env 双源混合模式架构)。
    """
    def __init__(self, config: AstrBotConfig):
        self.config = config
        self.db_pool: Optional[aiomysql.Pool] = None
        self.api_base_url = None
        self.api_access_token = None
        self.api_admin_user_id = None
        logger.info("[NewAPI Utils] 核心工具类已实例化，等待异步初始化...")

    @staticmethod
    def _resolve(config_val, env_val):
        """解析配置值：插件配置优先，若为空(空字符串/0/None)则回退到 .env 环境变量。"""
        if isinstance(config_val, str):
            config_val = config_val.strip()
        if config_val not in (None, "", 0, False):
            return config_val
        return env_val

    async def initialize(self) -> bool:
        """异步初始化：同时支持插件配置与 .env，插件配置优先，缺失项回退到 .env，随后连接数据库并自动建表。"""
        logger.info("[NewAPI Utils] 开始执行异步初始化...")

        # 加载 .env 环境变量（作为插件配置的回退来源）
        load_dotenv()

        # API 配置：插件配置 > .env
        api_conf = self.config.get('api_settings', {})
        self.api_base_url = self._resolve(api_conf.get('api_base_url'), os.getenv("API_BASE_URL"))
        raw_token = self._resolve(api_conf.get('api_access_token'), os.getenv("API_ACCESS_TOKEN", ""))

        # 自动补全 Bearer 前缀（兼容两种写法）
        if raw_token and not str(raw_token).lower().startswith("bearer "):
            raw_token = f"Bearer {raw_token}"
        self.api_access_token = raw_token

        # 管理员操作用户 ID（预留，供后续管理员操作使用）
        self.api_admin_user_id = self._resolve(api_conf.get('api_admin_user_id'), os.getenv("API_ADMIN_USER_ID"))

        if not self.api_base_url or not self.api_access_token:
            logger.error("[NewAPI Utils] API 配置不完整（插件配置与 .env 均未提供）！初始化失败。")
            return False

        # 数据库配置：插件配置 > .env
        db_conf = self.config.get('database_settings', {})
        db_host = self._resolve(db_conf.get('host'), os.getenv("DB_HOST"))
        db_port = self._resolve(db_conf.get('port'), os.getenv("DB_PORT"))
        db_user = self._resolve(db_conf.get('user'), os.getenv("DB_USER"))
        db_pass = self._resolve(db_conf.get('password'), os.getenv("DB_PASS"))
        db_name = self._resolve(db_conf.get('name'), os.getenv("DB_NAME"))

        if not all([db_host, db_port, db_user, db_name]):
            logger.error("[NewAPI Utils] 数据库配置不完整（插件配置与 .env 均未提供）！初始化失败。")
            return False
            
        try:
            self.db_pool = await aiomysql.create_pool(
                host=db_host, port=int(db_port),
                user=db_user, password=db_pass,
                db=db_name, autocommit=True
            )
            logger.info("[NewAPI Utils] 数据库连接池已成功建立。")

            # 【修改】召唤数据库管家，执行建表仪式
            if not await self._ensure_tables_exist():
                return False

            return True
        except Exception as e:
            logger.error(f"[NewAPI Utils] 数据库初始化失败: {e}", exc_info=True)
            self.db_pool = None
            return False

    # 【新增】数据库自动建表管家
    async def _ensure_tables_exist(self):
        """在初始化时检查并确保核心数据表存在。"""
        logger.info("[NewAPI Utils] 数据库管家开始检查并创建数据表...")
        try:
            # 1. 用户绑定信息表
            bindings_sql = """
            CREATE TABLE IF NOT EXISTS `newapi_bindings` (
              `id` int(11) NOT NULL AUTO_INCREMENT,
              `qq_id` bigint(20) NOT NULL,
              `website_user_id` int(11) NOT NULL,
              `binding_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
              `last_check_in_time` timestamp NULL DEFAULT NULL,
              PRIMARY KEY (`id`),
              UNIQUE KEY `qq_id` (`qq_id`),
              UNIQUE KEY `website_user_id` (`website_user_id`)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """
            await self.execute_query(bindings_sql)
            
            # 2. 每日打劫日志表
            heist_log_sql = """
            CREATE TABLE IF NOT EXISTS `daily_heist_log` (
              `id` int(11) NOT NULL AUTO_INCREMENT,
              `robber_qq_id` bigint(20) NOT NULL,
              `victim_website_id` int(11) NOT NULL,
              `heist_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
              `outcome` varchar(10) NOT NULL COMMENT 'SUCCESS, CRITICAL, FAILURE',
              `amount` int(11) NOT NULL COMMENT '涉及的原始 quota 数额',
              PRIMARY KEY (`id`)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """
            await self.execute_query(heist_log_sql)
            
            logger.info("✅ [NewAPI Utils] 数据表结构已确认就绪。")
            return True
        except Exception as e:
            logger.error(f"❌ [NewAPI Utils] 自动创建数据表时发生严重错误: {e}", exc_info=True)
            return False

    async def execute_query(self, query: str, args: Optional[Tuple] = None, fetch: Optional[str] = None) -> Any:
        if self.db_pool is None:
            logger.error("[NewAPI Utils] 数据库未连接，无法执行查询。")
            return None
        async with self.db_pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor if fetch else aiomysql.Cursor) as cur:
                await cur.execute(query, args)
                if fetch == 'one':
                    return await cur.fetchone()
                elif fetch == 'all':
                    return await cur.fetchall()
                return cur.rowcount

    async def api_request(self, method: str, endpoint: str, json_data: Optional[Dict] = None) -> Optional[Dict]:
        if not self.api_base_url or not self.api_access_token:
            logger.error("[NewAPI Utils] API 配置未在初始化时成功加载，请求中止。")
            return None

        # 确保 URL 正确拼接（避免双斜杠）
        base = self.api_base_url.rstrip("/")
        url = f"{base}{endpoint}"
        headers = {"Authorization": self.api_access_token}

        logger.info(f"[NewAPI Utils] API 请求: {method} {url}")
        if json_data:
            logger.info(f"[NewAPI Utils] 请求体: {json_data}")
        try:
            async with httpx.AsyncClient() as client:
                response = await client.request(method, url, headers=headers, json=json_data, timeout=10.0)
                logger.info(f"[NewAPI Utils] 响应 HTTP {response.status_code}: {response.text[:500]}")
                if not response.is_success:
                    logger.error(
                        f"[NewAPI Utils] API 返回错误 {method} {endpoint}: "
                        f"HTTP {response.status_code} -> {response.text[:500]}"
                    )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"[NewAPI Utils] API 请求异常 {method} {endpoint}: {e}", exc_info=True)
            return None

    async def check_api_connection(self) -> bool:
        """检测 New API 网站连接状态（查询管理员用户余额，查得即成功）。"""
        admin_id = self.api_admin_user_id
        if admin_id in (None, 0, "0", ""):
            logger.error("[NewAPI Utils] 未配置管理员用户 ID，无法检测 New API 连接。")
            return False
        try:
            admin_id = int(admin_id)
        except (TypeError, ValueError):
            logger.error(f"[NewAPI Utils] 管理员用户 ID 无效: {admin_id}，无法检测 New API 连接。")
            return False
        api_user_data = await self.get_api_user_data(admin_id)
        return api_user_data is not None

    # --- 以下所有高级助手方法保持不变 ---
    async def get_user_by_qq(self, qq_id: int) -> Optional[Dict]: return await self.execute_query("SELECT * FROM newapi_bindings WHERE qq_id = %s", (qq_id,), fetch='one')
    async def get_user_by_website_id(self, website_user_id: int) -> Optional[Dict]: return await self.execute_query("SELECT * FROM newapi_bindings WHERE website_user_id = %s", (website_user_id,), fetch='one')
    async def get_api_user_data(self, user_id: int) -> Optional[Dict]:
        response = await self.api_request("GET", f"/api/user/{user_id}")
        if response and response.get("success"): return response.get("data")
        return None
    async def update_api_user(self, user_profile: Dict) -> bool:
        """仅用于更新用户分组等非额度字段（PUT /api/user/ 不支持更新 quota）。"""
        logger.info(f"[DEBUG] update_api_user payload: {user_profile}")
        response = await self.api_request("PUT", "/api/user/", json_data=user_profile)
        logger.info(f"[DEBUG] update_api_user response: {response}")
        return response and response.get("success", False)

    async def manage_user_quota(self, user_id: int, action: str, value: int) -> bool:
        """通过 POST /api/user/manage 操作用户额度。action: add_quota, mode: add/subtract/override。"""
        payload = {"id": user_id, "action": "add_quota", "mode": action, "value": value}
        response = await self.api_request("POST", "/api/user/manage", json_data=payload)
        return response and response.get("success", False)
    async def insert_binding(self, qq_id: int, website_user_id: int) -> int: return await self.execute_query("INSERT INTO newapi_bindings (qq_id, website_user_id) VALUES (%s, %s)", (qq_id, website_user_id))
    async def delete_binding(self, *, qq_id: Optional[int] = None, website_user_id: Optional[int] = None) -> int:
        if qq_id: return await self.execute_query("DELETE FROM newapi_bindings WHERE qq_id = %s", (qq_id,))
        if website_user_id: return await self.execute_query("DELETE FROM newapi_bindings WHERE website_user_id = %s", (website_user_id,))
        return 0
    async def set_check_in_time(self, qq_id: int) -> int:
        query = "UPDATE newapi_bindings SET last_check_in_time = %s WHERE qq_id = %s"
        return await self.execute_query(query, (datetime.utcnow(), qq_id))
    async def revert_user_group(self, website_user_id: int) -> bool:
        api_user_data = await self.get_api_user_data(website_user_id)
        if not api_user_data:
            logger.warning(f"无法获取网站ID {website_user_id} 的用户数据，跳过用户组恢复操作。")
            return False
        leave_conf = self.config.get('group_leave_settings', {})
        revert_group = leave_conf.get('revert_group_on_leave', 'default')
        if api_user_data.get('group') != revert_group:
            api_user_data['group'] = revert_group
            update_success = await self.update_api_user(api_user_data)
            if update_success:
                logger.info(f"成功将网站用户 {website_user_id} 恢复至用户组: {revert_group}")
            else:
                logger.error(f"尝试恢复网站用户 {website_user_id} 至用户组 {revert_group} 时失败。")
            return update_success
        logger.info(f"网站用户 {website_user_id} 已在目标恢复组 {revert_group} 中，无需操作。")
        return True
    async def perform_check_in(self, qq_id: int, binding: Optional[Dict] = None) -> Tuple[str, Dict[str, Any]]:
        check_in_conf = self.config.get('check_in_settings', {})
        if not check_in_conf.get('enabled', False):
            return "DISABLED", {}

        if not binding:
            binding = await self.get_user_by_qq(qq_id)
        if not binding:
            return "NOT_BOUND", {}

        # --- 缓存配置值 ---
        offset_hours = check_in_conf.get('timezone_offset_hours', 0)
        first_bonus_enabled = check_in_conf.get('first_check_in_bonus_enabled', False)
        first_bonus_display_quota = check_in_conf.get('first_check_in_bonus_display_quota', 0)
        double_chance = check_in_conf.get('double_chance', 0.0)
        min_display_q = check_in_conf.get('min_display_quota', 0)
        max_display_q = check_in_conf.get('max_display_quota', 0)
        ratio = self.config.get('binding_settings.quota_display_ratio', 500000)
        # --- 缓存结束 ---

        time_delta = timedelta(hours=offset_hours)
        local_today = (datetime.utcnow() + time_delta).date()
        last_check_in_time = binding.get('last_check_in_time')
        is_first_check_in = last_check_in_time is None

        if not is_first_check_in:
            local_last_check_in_date = (last_check_in_time + time_delta).date()
            if local_last_check_in_date == local_today:
                return "ALREADY_CHECKED_IN", {}

        bonus_quota = 0
        is_doubled = False
        if is_first_check_in and first_bonus_enabled:
            bonus_quota = int(first_bonus_display_quota * ratio)
        else:
            is_doubled = random.random() < double_chance
        
        base_display_quota = random.uniform(min_display_q, max_display_q)
        base_quota = int(base_display_quota * ratio)
        regular_quota = base_quota * 2 if is_doubled else base_quota
        final_quota = regular_quota + bonus_quota

        website_user_id = binding['website_user_id']
        api_user_data = await self.get_api_user_data(website_user_id)
        if not api_user_data:
            return "API_USER_NOT_FOUND", {}

        current_quota = api_user_data.get("quota", 0)

        if not await self.manage_user_quota(website_user_id, "add", final_quota):
            return "API_UPDATE_FAILED", {}
            
        await self.set_check_in_time(qq_id)
        
        display_added = final_quota / ratio
        display_total = (current_quota + final_quota) / ratio

        return "SUCCESS", {
            "is_first": is_first_check_in,
            "is_doubled": is_doubled,
            "display_added": display_added,
            "display_total": display_total,
            "user_qq": qq_id,
            "site_id": website_user_id
        }
    async def purge_user_binding(self, website_user_id: int) -> Tuple[bool, Optional[Dict]]:
        binding_info = await self.get_user_by_website_id(website_user_id)
        if not binding_info:
            logger.warning(f"净化请求失败：未找到网站ID {website_user_id} 的绑定记录。")
            return False, None
        try:
            logger.info(f"开始净化网站ID {website_user_id} (QQ: {binding_info['qq_id']})...")
            await self.revert_user_group(website_user_id)
            rows_affected = await self.delete_binding(website_user_id=website_user_id)
            if rows_affected > 0:
                logger.info(f"净化成功：已删除网站ID {website_user_id} 的绑定记录。")
                return True, binding_info
            else:
                logger.error(f"净化异常：记录存在但删除失败，数据库影响行数为0。")
                return False, binding_info
        except Exception as e:
            logger.error(f"执行净化网站ID {website_user_id} 的过程中发生未知错误: {e}", exc_info=True)
            return False, binding_info
    async def lookup_binding(self, identifier: int) -> Tuple[str, Optional[Dict]]:
        binding = await self.get_user_by_website_id(identifier)
        if binding:
            return "WEBSITE_ID", binding
        binding = await self.get_user_by_qq(identifier)
        if binding:
            return "QQ_ID", binding
        return "NOT_FOUND", None
    async def adjust_balance_by_identifier(self, identifier: int, display_adjustment: float) -> Tuple[str, Optional[Dict]]:
        id_type, binding = await self.lookup_binding(identifier)
        if id_type == "NOT_FOUND":
            return "USER_NOT_FOUND", None
        website_user_id = binding['website_user_id']
        api_user_data = await self.get_api_user_data(website_user_id)
        if not api_user_data:
            return "API_FETCH_FAILED", {"website_user_id": website_user_id}
        ratio = self.config.get('binding_settings.quota_display_ratio', 500000)
        raw_quota_adjustment = int(display_adjustment * ratio)
        if raw_quota_adjustment >= 0:
            if not await self.manage_user_quota(website_user_id, "add", raw_quota_adjustment):
                return "API_UPDATE_FAILED", {"website_user_id": website_user_id}
        else:
            if not await self.manage_user_quota(website_user_id, "subtract", abs(raw_quota_adjustment)):
                return "API_UPDATE_FAILED", {"website_user_id": website_user_id}
        # 重新获取最新额度
        updated_user = await self.get_api_user_data(website_user_id)
        if not updated_user:
            return "API_FETCH_FAILED", {"website_user_id": website_user_id}
        new_total_raw_quota = updated_user.get("quota", 0)
        new_display_quota = new_total_raw_quota / ratio
        return "SUCCESS", {"website_user_id": website_user_id, "new_display_quota": new_display_quota}
    async def get_today_heist_counts_by_qq(self, robber_qq_id: int) -> int:
        query = "SELECT COUNT(*) as count FROM daily_heist_log WHERE robber_qq_id = %s AND DATE(heist_time) = CURDATE()"
        result = await self.execute_query(query, (robber_qq_id,), fetch='one')
        return result['count'] if result else 0
    async def get_today_defenses_count_by_id(self, victim_website_id: int) -> int:
        query = "SELECT COUNT(*) as count FROM daily_heist_log WHERE victim_website_id = %s AND DATE(heist_time) = CURDATE() AND outcome IN ('SUCCESS', 'CRITICAL')"
        result = await self.execute_query(query, (victim_website_id,), fetch='one')
        return result['count'] if result else 0

    async def get_last_heist_time_by_qq(self, robber_qq_id: int) -> Optional[datetime]:
        """获取指定用户最近一次打劫的时间。"""
        query = "SELECT MAX(heist_time) as last_time FROM daily_heist_log WHERE robber_qq_id = %s"
        result = await self.execute_query(query, (robber_qq_id,), fetch='one')
        return result['last_time'] if result and result['last_time'] else None
    async def log_heist_attempt(self, robber_qq_id: int, victim_website_id: int, outcome: str, amount: int) -> int:
        query = "INSERT INTO daily_heist_log (robber_qq_id, victim_website_id, heist_time, outcome, amount) VALUES (%s, %s, %s, %s, %s)"
        return await self.execute_query(query, (robber_qq_id, victim_website_id, datetime.utcnow(), outcome, amount))
    async def transfer_display_quota(self, from_user_id: int, to_user_id: int, display_amount: float, allow_partial: bool = False) -> Tuple[bool, float, int]:
        ratio = self.config.get('binding_settings.quota_display_ratio', 500000)
        raw_amount = int(display_amount * ratio)
        transfer_success, actual_raw_amount = await self._transfer_quota(from_user_id=from_user_id, to_user_id=to_user_id, raw_amount=raw_amount, allow_partial=allow_partial)
        actual_display_amount = actual_raw_amount / ratio
        return transfer_success, actual_display_amount, actual_raw_amount
    async def _transfer_quota(self, from_user_id: int, to_user_id: int, raw_amount: int, allow_partial: bool = False) -> Tuple[bool, int]:
        from_user = await self.get_api_user_data(from_user_id)
        to_user = await self.get_api_user_data(to_user_id)
        if not from_user or not to_user:
            return False, 0
        from_balance = from_user.get("quota", 0)
        actual_amount = raw_amount
        if from_balance < raw_amount:
            if allow_partial:
                actual_amount = from_balance
            else:
                return False, 0
        if actual_amount <= 0:
            return True, 0

        # 从付款方扣款
        if not await self.manage_user_quota(from_user_id, "subtract", actual_amount):
            return False, 0

        # 向收款方加款
        if not await self.manage_user_quota(to_user_id, "add", actual_amount):
            logger.error(
                f"Quota transfer failed at receiving end (to_user_id: {to_user_id}). "
                f"Attempting to roll back deduction for from_user_id: {from_user_id}."
            )
            if not await self.manage_user_quota(from_user_id, "add", actual_amount):
                logger.critical(
                    f"CRITICAL FAILURE: Rollback for from_user_id {from_user_id} FAILED. "
                    f"User has lost {actual_amount} quota. Manual intervention required."
                )
            return False, 0
        return True, actual_amount
