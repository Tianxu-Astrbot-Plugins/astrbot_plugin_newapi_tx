import os
import asyncio
import httpx
import aiomysql
import aiosqlite
import random
from datetime import datetime, timedelta
from typing import Optional, Any, Dict, Tuple

from dotenv import load_dotenv, find_dotenv

from astrbot.api import logger, AstrBotConfig


class NewApiCore:
    """
    NewAPI 核心工具类。
    支持双数据引擎：
      - MySQL 模式（默认）：使用 aiomysql 连接池存储绑定和打劫日志
      - SQLite 模式：使用 aiosqlite 单文件数据库，存储在 AstrBot 数据目录下
    """
    def __init__(self, config: AstrBotConfig):
        self.config = config
        # MySQL 模式
        self.db_pool: Optional[aiomysql.Pool] = None
        # SQLite 模式
        self.db_conn: Optional[aiosqlite.Connection] = None
        # 当前引擎：'mysql' 或 'sqlite'
        self.db_mode: str = "mysql"
        # API 配置
        self.api_base_url: Optional[str] = None
        self.api_access_token: Optional[str] = None
        self.api_admin_user_id: Optional[str] = None
        logger.info("[NewAPI Utils] 核心工具类已实例化，等待异步初始化...")

    @staticmethod
    def _resolve(config_val, env_val):
        """解析配置值：插件配置优先，若为空(空字符串/0/None)则回退到 .env 环境变量。"""
        if isinstance(config_val, str):
            config_val = config_val.strip()
        if config_val not in (None, "", 0, False):
            return config_val
        return env_val

    # ------------------------------------------------------------------ #
    #  初始化                                                         #
    # ------------------------------------------------------------------ #

    async def initialize(self) -> bool:
        """异步初始化：插件配置优先，缺失项回退到 .env。"""
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

        self.api_admin_user_id = self._resolve(api_conf.get('api_admin_user_id'), os.getenv("API_ADMIN_USER_ID"))

        if not self.api_base_url or not self.api_access_token:
            logger.error("[NewAPI Utils] API 配置不完整（插件配置与 .env 均未提供）！初始化失败。")
            return False

        # 数据库配置：插件配置 > .env
        db_conf = self.config.get('database_settings', {})
        sqlite_conf = self.config.get('sqlite_settings', {})
        # 兼容旧版：旧配置将开关存在 database_settings 下，新版统一读取 sqlite_settings
        use_sqlite = bool(sqlite_conf.get('use_sqlite_mode', db_conf.get('use_sqlite_mode', False)))
        self.db_mode = "sqlite" if use_sqlite else "mysql"

        if use_sqlite:
            return await self._init_sqlite()
        return await self._init_mysql(db_conf)

    async def _init_mysql(self, db_conf: Dict) -> bool:
        """初始化 MySQL 数据库连接池。"""
        db_host  = self._resolve(db_conf.get('host'),     os.getenv("DB_HOST"))
        db_port  = self._resolve(db_conf.get('port'),     os.getenv("DB_PORT"))
        db_user  = self._resolve(db_conf.get('user'),     os.getenv("DB_USER"))
        db_pass  = self._resolve(db_conf.get('password'), os.getenv("DB_PASS"))
        db_name  = self._resolve(db_conf.get('name'),    os.getenv("DB_NAME"))

        if not all([db_host, db_port, db_user, db_name]):
            logger.error("[NewAPI Utils] 数据库配置不完整（插件配置与 .env 均未提供）！初始化失败。")
            return False

        try:
            self.db_pool = await aiomysql.create_pool(
                host=db_host, port=int(db_port),
                user=db_user, password=db_pass,
                db=db_name, autocommit=True
            )
            logger.info("[NewAPI Utils] MySQL 连接池已成功建立。")
            if not await self._ensure_tables_exist_mysql():
                return False
            return True
        except Exception as e:
            logger.error(f"[NewAPI Utils] MySQL 数据库初始化失败: {e}", exc_info=True)
            self.db_pool = None
            return False

    async def _init_sqlite(self) -> bool:
        """初始化 SQLite 单文件数据库。"""
        try:
            # 尝试获取 AstrBot 数据目录（插件数据存储在 plugin_data/<plugin_name>/ 下）
            try:
                from astrbot.core.utils.io import get_astrbot_data_path
            except ImportError:
                from astrbot.api.provider import get_astrbot_data_path

            data_path = get_astrbot_data_path()
            plugin_dir = os.path.join(data_path, "plugin_data", "astrbot_plugin_newapi_tx")
            os.makedirs(plugin_dir, exist_ok=True)
            db_path = os.path.join(plugin_dir, "newapi.db")

            self.db_conn = await aiosqlite.connect(db_path, isolation_level=None)
            self.db_conn.row_factory = aiosqlite.Row
            # WAL 模式提升并发读写性能
            await self.db_conn.execute("PRAGMA journal_mode=WAL;")
            # 确保外键约束（虽然当前表间无外键，但养成好习惯）
            await self.db_conn.execute("PRAGMA foreign_keys=ON;")

            logger.info(f"[NewAPI Utils] SQLite 数据库已连接: {db_path}")
            if not await self._ensure_tables_exist_sqlite():
                return False
            return True
        except Exception as e:
            logger.error(f"[NewAPI Utils] SQLite 数据库初始化失败: {e}", exc_info=True)
            self.db_conn = None
            return False

    def is_db_ready(self) -> bool:
        """返回数据库是否已就绪。兼容 MySQL / SQLite 两种模式。"""
        if self.db_mode == "sqlite":
            return self.db_conn is not None
        return self.db_pool is not None

    # ------------------------------------------------------------------ #
    #  建表                                                           #
    # ------------------------------------------------------------------ #

    async def _ensure_tables_exist_mysql(self):
        """MySQL 模式：创建必要的数据表。"""
        logger.info("[NewAPI Utils] MySQL 建表检查中...")
        try:
            await self.execute_query("""
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
            """)
            await self.execute_query("""
            CREATE TABLE IF NOT EXISTS `daily_heist_log` (
              `id` int(11) NOT NULL AUTO_INCREMENT,
              `robber_qq_id` bigint(20) NOT NULL,
              `victim_website_id` int(11) NOT NULL,
              `heist_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
              `outcome` varchar(10) NOT NULL COMMENT 'SUCCESS, CRITICAL, FAILURE',
              `amount` int(11) NOT NULL,
              PRIMARY KEY (`id`)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)
            await self.execute_query("""
            CREATE TABLE IF NOT EXISTS `newapi_check_in_state` (
              `id` int(11) NOT NULL AUTO_INCREMENT,
              `qq_id` bigint(20) NOT NULL,
              `last_check_in_time` timestamp NULL DEFAULT NULL,
              PRIMARY KEY (`id`),
              UNIQUE KEY `qq_id` (`qq_id`)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)
            logger.info("[NewAPI Utils] MySQL 数据表结构已确认就绪。")
            return True
        except Exception as e:
            logger.error(f"[NewAPI Utils] MySQL 建表失败: {e}", exc_info=True)
            return False

    async def _ensure_tables_exist_sqlite(self):
        """SQLite 模式：创建必要的数据表。"""
        logger.info("[NewAPI Utils] SQLite 建表检查中...")
        try:
            await self._execute_sqlite("""
            CREATE TABLE IF NOT EXISTS newapi_bindings (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              qq_id INTEGER NOT NULL UNIQUE,
              website_user_id INTEGER NOT NULL UNIQUE,
              binding_time TEXT NOT NULL DEFAULT (datetime('now')),
              last_check_in_time TEXT
            );
            """)
            await self._execute_sqlite("""
            CREATE TABLE IF NOT EXISTS daily_heist_log (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              robber_qq_id INTEGER NOT NULL,
              victim_website_id INTEGER NOT NULL,
              heist_time TEXT NOT NULL DEFAULT (datetime('now')),
              outcome TEXT NOT NULL,
              amount INTEGER NOT NULL
            );
            """)
            await self._execute_sqlite("""
            CREATE TABLE IF NOT EXISTS newapi_check_in_state (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              qq_id INTEGER NOT NULL UNIQUE,
              last_check_in_time TEXT
            );
            """)
            logger.info("[NewAPI Utils] SQLite 数据表结构已确认就绪。")
            return True
        except Exception as e:
            logger.error(f"[NewAPI Utils] SQLite 建表失败: {e}", exc_info=True)
            return False

    # ------------------------------------------------------------------ #
    #  查询执行                                                       #
    # ------------------------------------------------------------------ #

    async def execute_query(self, query: str, args: Optional[Tuple] = None,
                            fetch: Optional[str] = None) -> Any:
        """
        统一的查询入口。根据当前引擎类型自动路由到 MySQL 或 SQLite 实现。
        占位符由子类实现决定（MySQL 用 %s，SQLite 用 ?）。
        """
        if self.db_mode == "sqlite":
            return await self._execute_sqlite(query, args, fetch)
        return await self._execute_mysql(query, args, fetch)

    async def _execute_mysql(self, query: str, args: Optional[Tuple] = None,
                             fetch: Optional[str] = None) -> Any:
        """执行 MySQL 查询。"""
        if self.db_pool is None:
            logger.error("[NewAPI Utils] MySQL 连接池未建立，无法执行查询。")
            return None
        async with self.db_pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor if fetch else aiomysql.Cursor) as cur:
                await cur.execute(query, args)
                if fetch == 'one':
                    return await cur.fetchone()
                elif fetch == 'all':
                    return await cur.fetchall()
                return cur.rowcount

    async def _execute_sqlite(self, query: str, args: Optional[Tuple] = None,
                              fetch: Optional[str] = None) -> Any:
        """执行 SQLite 查询，自动处理占位符转换和行格式转换。"""
        if self.db_conn is None:
            logger.error("[NewAPI Utils] SQLite 连接未建立，无法执行查询。")
            return None

        # MySQL %s 占位符 → SQLite ? 占位符
        q = query.replace("%s", "?")
        # MySQL CURDATE() → SQLite date('now')
        q = q.replace("CURDATE()", "date('now')")

        async with self.db_conn.execute(q, args or None) as cur:
            if fetch == 'one':
                row = await cur.fetchone()
                return self._sqlite_row_to_dict(row)
            elif fetch == 'all':
                rows = await cur.fetchall()
                return [self._sqlite_row_to_dict(r) for r in rows] if rows else []
            await self.db_conn.commit()
            return cur.rowcount

    @staticmethod
    def _sqlite_row_to_dict(row) -> Optional[Dict]:
        """
        将 aiosqlite.Row 转换为普通字典，并处理时间戳字段。
        MySQL DictCursor 直接返回 dict，时间戳字段为 datetime 对象；
        SQLite aiosqlite.Row 返回的字段值为字符串（除非用了 CAST），需手动转换以保持接口兼容。
        """
        if row is None:
            return None
        d = dict(row)
        # 将已知的时间戳字段字符串解析为 datetime 对象，保持与 MySQL 模式一致的接口
        for col in ("binding_time", "last_check_in_time", "heist_time"):
            val = d.get(col)
            if isinstance(val, str):
                try:
                    # 格式：2024-01-01 12:00:00
                    d[col] = datetime.strptime(val[:19], "%Y-%m-%d %H:%M:%S")
                except (ValueError, TypeError):
                    pass
        return d

    @staticmethod
    def _format_datetime_for_sqlite(val: Any) -> str:
        """将 Python datetime 对象转换为 SQLite 可接受的文本格式。"""
        if isinstance(val, datetime):
            return val.strftime("%Y-%m-%d %H:%M:%S")
        return str(val)

    # ------------------------------------------------------------------ #
    #  API 请求                                                       #
    # ------------------------------------------------------------------ #

    async def api_request(self, method: str, endpoint: str,
                          json_data: Optional[Dict] = None) -> Optional[Dict]:
        if not self.api_base_url or not self.api_access_token:
            logger.error("[NewAPI Utils] API 配置未在初始化时成功加载，请求中止。")
            return None

        base = self.api_base_url.rstrip("/")
        url = f"{base}{endpoint}"
        headers = {"Authorization": self.api_access_token}

        logger.info(f"[NewAPI Utils] API 请求: {method} {url}")
        if json_data:
            logger.info(f"[NewAPI Utils] 请求体: {json_data}")
        try:
            async with httpx.AsyncClient() as client:
                response = await client.request(
                    method, url, headers=headers, json=json_data, timeout=10.0
                )
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

    # ------------------------------------------------------------------ #
    #  业务方法                                                       #
    # ------------------------------------------------------------------ #

    async def get_user_by_qq(self, qq_id: int) -> Optional[Dict]:
        return await self.execute_query(
            "SELECT * FROM newapi_bindings WHERE qq_id = %s", (qq_id,), fetch='one'
        )

    async def get_user_by_website_id(self, website_user_id: int) -> Optional[Dict]:
        return await self.execute_query(
            "SELECT * FROM newapi_bindings WHERE website_user_id = %s", (website_user_id,), fetch='one'
        )

    async def get_api_user_data(self, user_id: int) -> Optional[Dict]:
        response = await self.api_request("GET", f"/api/user/{user_id}")
        if response and response.get("success"):
            return response.get("data")
        return None

    async def update_api_user(self, user_profile: Dict) -> bool:
        logger.info(f"[DEBUG] update_api_user payload: {user_profile}")
        response = await self.api_request("PUT", "/api/user/", json_data=user_profile)
        logger.info(f"[DEBUG] update_api_user response: {response}")
        return response and response.get("success", False)

    async def manage_user_quota(self, user_id: int, action: str, value: int) -> bool:
        """通过 POST /api/user/manage 操作用户额度。action: add_quota, mode: add/subtract/override。"""
        payload = {"id": user_id, "action": "add_quota", "mode": action, "value": value}
        response = await self.api_request("POST", "/api/user/manage", json_data=payload)
        return response and response.get("success", False)

    async def insert_binding(self, qq_id: int, website_user_id: int) -> int:
        return await self.execute_query(
            "INSERT INTO newapi_bindings (qq_id, website_user_id) VALUES (%s, %s)",
            (qq_id, website_user_id)
        )

    async def delete_binding(self, *, qq_id: Optional[int] = None,
                              website_user_id: Optional[int] = None) -> int:
        if qq_id:
            return await self.execute_query(
                "DELETE FROM newapi_bindings WHERE qq_id = %s", (qq_id,)
            )
        if website_user_id:
            return await self.execute_query(
                "DELETE FROM newapi_bindings WHERE website_user_id = %s", (website_user_id,)
            )
        return 0

    async def get_check_in_state(self, qq_id: int) -> Optional[Dict]:
        """获取指定 QQ 的持久化签到状态（退群/解绑不会清除，防止刷新人礼包与重复签到）。"""
        return await self.execute_query(
            "SELECT * FROM newapi_check_in_state WHERE qq_id = %s", (qq_id,), fetch='one'
        )

    async def set_check_in_time(self, qq_id: int) -> int:
        """写入/更新指定 QQ 的签到时间到独立状态表（跨引擎 upsert）。"""
        # datetime.utcnow() 存储为字符串以兼容 SQLite
        now_str = self._format_datetime_for_sqlite(datetime.utcnow())
        existing = await self.get_check_in_state(qq_id)
        if existing:
            return await self.execute_query(
                "UPDATE newapi_check_in_state SET last_check_in_time = %s WHERE qq_id = %s",
                (now_str, qq_id)
            )
        return await self.execute_query(
            "INSERT INTO newapi_check_in_state (qq_id, last_check_in_time) VALUES (%s, %s)",
            (qq_id, now_str)
        )

    async def revert_user_group(self, website_user_id: int) -> bool:
        api_user_data = await self.get_api_user_data(website_user_id)
        if not api_user_data:
            logger.warning(f"无法获取网站ID {website_user_id} 的用户数据，跳过用户组恢复操作。")
            return False
        leave_conf = self.config.get('group_leave_settings', {})
        revert_group = leave_conf.get('revert_group_on_leave', 'default')
        if api_user_data.get('group') == revert_group:
            logger.info(f"网站用户 {website_user_id} 已在目标恢复组 {revert_group} 中，无需操作。")
            return True
        # 【修复】与绑定仪式一致，只发送后端允许修改的字段，避免全量对象 PUT 被拒绝 (Invalid parameters)
        update_payload = {
            "id": website_user_id,
            "username": api_user_data.get("username"),
            "display_name": api_user_data.get("display_name"),
            "role": api_user_data.get("role"),
            "status": api_user_data.get("status"),
            "group": revert_group
        }
        update_success = await self.update_api_user(update_payload)
        if update_success:
            logger.info(f"成功将网站用户 {website_user_id} 恢复至用户组: {revert_group}")
        else:
            logger.error(f"尝试恢复网站用户 {website_user_id} 至用户组 {revert_group} 时失败。")
        return update_success

    async def perform_check_in(self, qq_id: int, binding: Optional[Dict] = None) -> Tuple[str, Dict[str, Any]]:
        check_in_conf = self.config.get('check_in_settings', {})
        if not check_in_conf.get('enabled', False):
            return "DISABLED", {}

        if not binding:
            binding = await self.get_user_by_qq(qq_id)
        if not binding:
            return "NOT_BOUND", {}

        offset_hours = check_in_conf.get('timezone_offset_hours', 0)
        first_bonus_enabled = check_in_conf.get('first_check_in_bonus_enabled', False)
        first_bonus_display_quota = check_in_conf.get('first_check_in_bonus_display_quota', 0)
        double_chance = check_in_conf.get('double_chance', 0.0)
        min_display_q = check_in_conf.get('min_display_quota', 0)
        max_display_q = check_in_conf.get('max_display_quota', 0)
        diminish_enabled = check_in_conf.get('diminish_enabled', False)
        diminish_threshold = check_in_conf.get('diminish_threshold', 0)
        ratio = self.config.get('binding_settings.quota_display_ratio', 500000)

        time_delta = timedelta(hours=offset_hours)
        local_today = (datetime.utcnow() + time_delta).date()
        # 【修复】签到时间从持久化状态表读取（退群/解绑不会清除）。
        # 兼容旧数据：状态表无记录时回退到绑定记录上的 last_check_in_time，实现一次性迁移。
        state = await self.get_check_in_state(qq_id)
        last_check_in_time = state.get('last_check_in_time') if state else binding.get('last_check_in_time')
        is_first_check_in = last_check_in_time is None

        if not is_first_check_in:
            local_last_check_in_date = (last_check_in_time + time_delta).date()
            if local_last_check_in_date == local_today:
                return "ALREADY_CHECKED_IN", {}

        website_user_id = binding['website_user_id']
        api_user_data = await self.get_api_user_data(website_user_id)
        if not api_user_data:
            return "API_USER_NOT_FOUND", {}

        current_quota = api_user_data.get("quota", 0)

        if diminish_enabled and diminish_threshold > 0:
            current_display = current_quota / ratio
            if current_display > diminish_threshold:
                tier = int(current_display / diminish_threshold)
                shrunk_max = max_display_q / (2 ** tier)
                max_display_q = max(shrunk_max, min_display_q)

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

    async def adjust_balance_by_identifier(self, identifier: int,
                                           display_adjustment: float) -> Tuple[str, Optional[Dict]]:
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
        updated_user = await self.get_api_user_data(website_user_id)
        if not updated_user:
            return "API_FETCH_FAILED", {"website_user_id": website_user_id}
        new_total_raw_quota = updated_user.get("quota", 0)
        new_display_quota = new_total_raw_quota / ratio
        return "SUCCESS", {"website_user_id": website_user_id, "new_display_quota": new_display_quota}

    async def get_today_heist_counts_by_qq(self, robber_qq_id: int) -> int:
        query = (
            "SELECT COUNT(*) as count FROM daily_heist_log "
            "WHERE robber_qq_id = %s AND DATE(heist_time) = CURDATE()"
        )
        result = await self.execute_query(query, (robber_qq_id,), fetch='one')
        return result['count'] if result else 0

    async def get_today_defenses_count_by_id(self, victim_website_id: int) -> int:
        query = (
            "SELECT COUNT(*) as count FROM daily_heist_log "
            "WHERE victim_website_id = %s AND DATE(heist_time) = CURDATE() "
            "AND outcome IN ('SUCCESS', 'CRITICAL')"
        )
        result = await self.execute_query(query, (victim_website_id,), fetch='one')
        return result['count'] if result else 0

    async def get_last_heist_time_by_qq(self, robber_qq_id: int) -> Optional[datetime]:
        query = (
            "SELECT MAX(heist_time) as last_time FROM daily_heist_log WHERE robber_qq_id = %s"
        )
        result = await self.execute_query(query, (robber_qq_id,), fetch='one')
        return result['last_time'] if result and result['last_time'] else None

    async def log_heist_attempt(self, robber_qq_id: int, victim_website_id: int,
                                outcome: str, amount: int) -> int:
        # amount 可能是负数（失败惩罚），SQLite 直接存整数即可
        heist_time_str = self._format_datetime_for_sqlite(datetime.utcnow())
        query = (
            "INSERT INTO daily_heist_log "
            "(robber_qq_id, victim_website_id, heist_time, outcome, amount) "
            "VALUES (%s, %s, %s, %s, %s)"
        )
        return await self.execute_query(
            query, (robber_qq_id, victim_website_id, heist_time_str, outcome, amount)
        )

    async def transfer_display_quota(self, from_user_id: int, to_user_id: int,
                                     display_amount: float,
                                     allow_partial: bool = False) -> Tuple[bool, float, int]:
        ratio = self.config.get('binding_settings.quota_display_ratio', 500000)
        raw_amount = int(display_amount * ratio)
        transfer_success, actual_raw_amount = await self._transfer_quota(
            from_user_id=from_user_id, to_user_id=to_user_id,
            raw_amount=raw_amount, allow_partial=allow_partial
        )
        actual_display_amount = actual_raw_amount / ratio
        return transfer_success, actual_display_amount, actual_raw_amount

    async def _transfer_quota(self, from_user_id: int, to_user_id: int,
                              raw_amount: int, allow_partial: bool = False) -> Tuple[bool, int]:
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

        if not await self.manage_user_quota(from_user_id, "subtract", actual_amount):
            return False, 0

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
