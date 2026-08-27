import os
import json
import asyncio
import time
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
        # 签到并发锁：按 website_user_id 串行化，防止同一账号并发签到绕过「今日已签到」检查（TOCTOU 重复领奖）
        self._check_in_locks: dict[int, asyncio.Lock] = {}
        # 红包并发锁：按红包 ID 串行化领取动作，防止并发超抢/重复领取
        self._red_packet_locks: dict[int, asyncio.Lock] = {}
        # 个人红包按网站账号加锁：串行化「查余额→扣款→建包」，防并发双花
        self._user_rp_locks: dict[str, asyncio.Lock] = {}
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

    def _resolve_plugin_data_dir(self) -> str:
        """解析插件数据目录 {AstrBot数据目录}/plugin_data/astrbot_plugin_newapi_tx。

        多版本 AstrBot 兼容：依次尝试各官方 API → StarTools → 由插件安装位置推导。
        """
        # 1) 各版本提供的数据目录 API
        candidates = (
            ("astrbot.core.utils.io", "get_astrbot_data_path"),
            ("astrbot.core.utils.astrbot_path", "get_astrbot_data_path"),
            ("astrbot.api.provider", "get_astrbot_data_path"),
            ("astrbot.api", "get_astrbot_data_path"),
        )
        for mod_name, attr in candidates:
            try:
                mod = __import__(mod_name, fromlist=[attr])
                fn = getattr(mod, attr, None)
                if callable(fn):
                    return os.path.join(str(fn()), "plugin_data", "astrbot_plugin_newapi_tx")
            except Exception:
                continue
        # 2) 新版 StarTools.get_data_dir
        try:
            from astrbot.core.star.star_tools import StarTools
            path = str(StarTools.get_data_dir("astrbot_plugin_newapi_tx"))
            os.makedirs(path, exist_ok=True)
            return path
        except Exception:
            pass
        # 3) 兜底：由插件文件位置推导（插件安装在 {数据目录}/plugins/<插件名>/ 下）
        plugin_root = os.path.dirname(os.path.abspath(__file__))
        data_dir = os.path.dirname(os.path.dirname(plugin_root))
        return os.path.join(data_dir, "plugin_data", "astrbot_plugin_newapi_tx")

    async def _init_sqlite(self) -> bool:
        """初始化 SQLite 单文件数据库。"""
        try:
            plugin_dir = self._resolve_plugin_data_dir()
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

    async def _ensure_column_mysql(self, table: str, column: str, ddl: str):
        """MySQL 缺列补列（老库平滑迁移 rp_code / grabber_name 等新字段）。

        直接对真实表执行 SHOW COLUMNS 探测，避免 information_schema 在部分
        部署下的作用域/权限差异导致「列实际缺失却被判为已存在」。
        补列后二次复核；仍失败则抛错让初始化显式失败（涉及资金安全）。
        """
        def _rows_have_col(rs):
            # aiomysql 默认游标返回元组行，DictCursor 返回字典；两种都兼容
            for r in rs or []:
                vals = r.values() if isinstance(r, dict) else r
                if column in {str(v).lower() for v in vals}:
                    return True
            return False

        show_sql = f"SHOW COLUMNS FROM `{table}`"
        try:
            async with self.db_pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(show_sql)
                    rs = await cur.fetchall()
                    if not _rows_have_col(rs):
                        logger.warning(f"[NewAPI Utils] MySQL 缺少列 {table}.{column}，执行补列: ADD {ddl}")
                        await cur.execute(f"ALTER TABLE `{table}` ADD COLUMN {ddl}")
                        await conn.commit()
                    else:
                        return
                    # 二次复核
                    await cur.execute(show_sql)
                    rs2 = await cur.fetchall()
                    if not _rows_have_col(rs2):
                        raise RuntimeError(
                            f"MySQL 补列后仍未找到 {table}.{column}，请人工检查数据库账号权限"
                        )
                    logger.info(f"[NewAPI Utils] MySQL 已为 {table} 补充新列: {column}")
        except Exception as e:
            logger.error(f"[NewAPI Utils] MySQL 补列失败 {table}.{column}: {e}", exc_info=True)
            raise

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
              `website_user_id` int(11) NOT NULL,
              `last_check_in_time` timestamp NULL DEFAULT NULL,
              PRIMARY KEY (`id`),
              UNIQUE KEY `website_user_id` (`website_user_id`)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)
            # 【迁移】兼容 1.0.17 按 qq_id 建的表，自动重建为按 website_user_id
            cols = await self.execute_query("SHOW COLUMNS FROM `newapi_check_in_state`", fetch='all')
            col_names = {c['Field'] for c in cols} if cols else set()
            if col_names and 'website_user_id' not in col_names:
                logger.warning("[NewAPI Utils] 检测到旧版签到状态表(以 qq_id 为键)，自动重建为 website_user_id。")
                await self.execute_query("DROP TABLE `newapi_check_in_state`")
                await self.execute_query("""
                CREATE TABLE IF NOT EXISTS `newapi_check_in_state` (
                  `id` int(11) NOT NULL AUTO_INCREMENT,
                  `website_user_id` int(11) NOT NULL,
                  `last_check_in_time` timestamp NULL DEFAULT NULL,
                  PRIMARY KEY (`id`),
                  UNIQUE KEY `website_user_id` (`website_user_id`)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
                """)
            # OpenID 绑定表（独立于 QQ 绑定，用于官机 openid 场景）
            await self.execute_query("""
            CREATE TABLE IF NOT EXISTS `newapi_openid_bindings` (
              `id` int(11) NOT NULL AUTO_INCREMENT,
              `openid` varchar(64) NOT NULL COMMENT '官方机器人 OpenID',
              `website_user_id` int(11) NOT NULL,
              `binding_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
              PRIMARY KEY (`id`),
              UNIQUE KEY `openid` (`openid`),
              UNIQUE KEY `website_user_id` (`website_user_id`)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)
            # 红包主表 + 领取记录表
            await self.execute_query("""
            CREATE TABLE IF NOT EXISTS `newapi_red_packets` (
              `id` int(11) NOT NULL AUTO_INCREMENT,
              `creator_identity` varchar(64) NOT NULL COMMENT '发起人身份(QQ或OpenID)',
              `total_raw` bigint(20) NOT NULL COMMENT '总原始额度',
              `total_display` double NOT NULL,
              `display_ratio` int(11) NOT NULL,
              `grab_count` int(11) NOT NULL,
              `remain_count` int(11) NOT NULL,
              `shares_json` text NOT NULL COMMENT '预拆分份额(原始额度整数)',
              `status` varchar(12) NOT NULL DEFAULT 'ACTIVE',
              `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
              `expire_at` timestamp NULL DEFAULT NULL,
              `rp_code` varchar(24) NULL DEFAULT NULL COMMENT '对外红包代码(字母数字,可复用)',
              PRIMARY KEY (`id`)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)
            await self._ensure_column_mysql("newapi_red_packets", "rp_code",
                                            "varchar(24) NULL DEFAULT NULL")
            await self.execute_query("""
            CREATE TABLE IF NOT EXISTS `newapi_red_packet_records` (
              `id` int(11) NOT NULL AUTO_INCREMENT,
              `packet_id` int(11) NOT NULL,
              `identity` varchar(64) NOT NULL COMMENT '领取人身份(QQ或OpenID)',
              `website_user_id` int(11) NOT NULL,
              `amount_raw` bigint(20) NOT NULL,
              `grabbed_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
              `grabber_name` varchar(128) NULL DEFAULT NULL COMMENT '领取人昵称',
              PRIMARY KEY (`id`),
              UNIQUE KEY `packet_identity` (`packet_id`,`identity`),
              KEY `idx_packet` (`packet_id`)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)
            await self._ensure_column_mysql("newapi_red_packet_records", "grabber_name",
                                            "varchar(128) NULL DEFAULT NULL")
            logger.info("[NewAPI Utils] MySQL 数据表结构已确认就绪。")
            return True
        except Exception as e:
            logger.error(f"[NewAPI Utils] MySQL 建表失败: {e}", exc_info=True)
            return False

    async def _ensure_column_sqlite(self, table: str, column: str, ddl: str):
        """SQLite 缺列补列（PRAGMA 检查后 ALTER）。"""
        try:
            cur = await self.db_conn.execute(f"PRAGMA table_info({table})")
            cols = await cur.fetchall()
            if not any((c[1] if not isinstance(c, dict) else c.get("name")) == column for c in cols):
                await self.execute_query(f"ALTER TABLE {table} ADD COLUMN {ddl}")
                logger.info(f"[NewAPI Utils] SQLite 已为 {table} 补充新列: {column}")
        except Exception as e:
            logger.warning(f"[NewAPI Utils] SQLite 检查/补充列 {table}.{column} 失败: {e}")

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
              website_user_id INTEGER NOT NULL UNIQUE,
              last_check_in_time TEXT
            );
            """)
            # 【迁移】兼容 1.0.17 按 qq_id 建的表，自动重建为按 website_user_id
            cols = await self._execute_sqlite("PRAGMA table_info(newapi_check_in_state)", fetch='all')
            col_names = {c['name'] for c in cols} if cols else set()
            if col_names and 'website_user_id' not in col_names:
                logger.warning("[NewAPI Utils] 检测到旧版签到状态表(以 qq_id 为键)，自动重建为 website_user_id。")
                await self._execute_sqlite("DROP TABLE newapi_check_in_state")
                await self._execute_sqlite("""
                CREATE TABLE IF NOT EXISTS newapi_check_in_state (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  website_user_id INTEGER NOT NULL UNIQUE,
                  last_check_in_time TEXT
                );
                """)
            # OpenID 绑定表（独立于 QQ 绑定，用于官机 openid 场景）
            await self._execute_sqlite("""
            CREATE TABLE IF NOT EXISTS newapi_openid_bindings (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              openid TEXT NOT NULL UNIQUE,
              website_user_id INTEGER NOT NULL UNIQUE,
              binding_time TEXT NOT NULL DEFAULT (datetime('now'))
            );
            """)
            # 红包主表 + 领取记录表
            await self._execute_sqlite("""
            CREATE TABLE IF NOT EXISTS newapi_red_packets (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              creator_identity TEXT NOT NULL,
              total_raw INTEGER NOT NULL,
              total_display REAL NOT NULL,
              display_ratio INTEGER NOT NULL,
              grab_count INTEGER NOT NULL,
              remain_count INTEGER NOT NULL,
              shares_json TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'ACTIVE',
              created_at TEXT NOT NULL DEFAULT (datetime('now')),
              expire_at TEXT,
              rp_code TEXT
            );
            """)
            await self._ensure_column_sqlite("newapi_red_packets", "rp_code", "TEXT")
            await self._execute_sqlite("""
            CREATE TABLE IF NOT EXISTS newapi_red_packet_records (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              packet_id INTEGER NOT NULL,
              identity TEXT NOT NULL,
              website_user_id INTEGER NOT NULL,
              amount_raw INTEGER NOT NULL,
              grabbed_at TEXT NOT NULL DEFAULT (datetime('now')),
              grabber_name TEXT,
              UNIQUE (packet_id, identity)
            );
            """)
            await self._ensure_column_sqlite("newapi_red_packet_records", "grabber_name", "TEXT")
            logger.info("[NewAPI Utils] SQLite 数据表结构已确认就绪。")
            return True
        except Exception as e:
            logger.error(f"[NewAPI Utils] SQLite 建表失败: {e}", exc_info=True)
            return False

    # ------------------------------------------------------------------ #
    #  查询执行                                                       #
    # ------------------------------------------------------------------ #

    async def execute_query(self, query: str, args: Optional[Tuple] = None,
                            fetch: Optional[str] = None,
                            return_lastrowid: bool = False) -> Any:
        """
        统一的查询入口。根据当前引擎类型自动路由到 MySQL 或 SQLite 实现。
        占位符由子类实现决定（MySQL 用 %s，SQLite 用 ?）。
        内置一次重试，应对瞬时连接断开等短暂故障。
        return_lastrowid=True 时返回自增主键（用于 INSERT 后取 ID）。
        """
        for attempt in (1, 2):
            try:
                if self.db_mode == "sqlite":
                    return await self._execute_sqlite(query, args, fetch, return_lastrowid)
                return await self._execute_mysql(query, args, fetch, return_lastrowid)
            except Exception as e:
                logger.warning(f"[NewAPI Utils] 数据库查询失败 (第{attempt}次): {e}")
                if attempt == 2:
                    logger.error(f"[NewAPI Utils] 数据库查询重试均失败，返回 None: {e}")
                    return None
                await asyncio.sleep(0.5)

    async def _execute_mysql(self, query: str, args: Optional[Tuple] = None,
                             fetch: Optional[str] = None,
                             return_lastrowid: bool = False) -> Any:
        """执行 MySQL 查询。"""
        if self.db_pool is None:
            raise RuntimeError("MySQL 连接池未建立")
        async with self.db_pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor if fetch else aiomysql.Cursor) as cur:
                await cur.execute(query, args)
                if return_lastrowid:
                    return cur.lastrowid
                if fetch == 'one':
                    return await cur.fetchone()
                elif fetch == 'all':
                    return await cur.fetchall()
                return cur.rowcount

    async def _execute_sqlite(self, query: str, args: Optional[Tuple] = None,
                              fetch: Optional[str] = None,
                              return_lastrowid: bool = False) -> Any:
        """执行 SQLite 查询，自动处理占位符转换和行格式转换。"""
        if self.db_conn is None:
            raise RuntimeError("SQLite 连接未建立")

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
            if return_lastrowid:
                lid = cur.lastrowid
                await self.db_conn.commit()
                return lid
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
    #  数据库导入导出（经 transfer.db 迁移文件在双引擎间搬运）          #
    # ------------------------------------------------------------------ #

    # 参与迁移的表（顺序即处理顺序）
    _TRANSFER_TABLES = (
        "newapi_bindings",
        "newapi_openid_bindings",
        "newapi_check_in_state",
        "daily_heist_log",
    )

    # 迁移文件（SQLite）中的建表语句，与在线 SQLite 模式结构一致
    _TRANSFER_SQLITE_DDL = {
        "newapi_bindings": """
            CREATE TABLE IF NOT EXISTS newapi_bindings (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              qq_id INTEGER NOT NULL UNIQUE,
              website_user_id INTEGER NOT NULL UNIQUE,
              binding_time TEXT NOT NULL DEFAULT (datetime('now')),
              last_check_in_time TEXT
            )
        """,
        "newapi_openid_bindings": """
            CREATE TABLE IF NOT EXISTS newapi_openid_bindings (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              openid TEXT NOT NULL UNIQUE,
              website_user_id INTEGER NOT NULL UNIQUE,
              binding_time TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """,
        "newapi_check_in_state": """
            CREATE TABLE IF NOT EXISTS newapi_check_in_state (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              website_user_id INTEGER NOT NULL UNIQUE,
              last_check_in_time TEXT
            )
        """,
        "daily_heist_log": """
            CREATE TABLE IF NOT EXISTS daily_heist_log (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              robber_qq_id INTEGER NOT NULL,
              victim_website_id INTEGER NOT NULL,
              heist_time TEXT NOT NULL DEFAULT (datetime('now')),
              outcome TEXT NOT NULL,
              amount INTEGER NOT NULL
            )
        """,
    }

    async def _get_transfer_db_path(self) -> str:
        """获取迁移文件路径：{AstrBot数据目录}/plugin_data/astrbot_plugin_newapi_tx/transfer.db"""
        plugin_dir = self._resolve_plugin_data_dir()
        os.makedirs(plugin_dir, exist_ok=True)
        return os.path.join(plugin_dir, "transfer.db")

    async def export_database(self) -> Dict[str, Any]:
        """导出：把【当前活动数据库】的全部业务表内容写入迁移文件 transfer.db（整文件覆盖）。

        返回 {"path": 迁移文件路径, "counts": {表名: 行数}}。
        """
        path = await self._get_transfer_db_path()

        # 1. 从当前引擎读取全量数据
        data: Dict[str, list] = {}
        for t in self._TRANSFER_TABLES:
            data[t] = await self.execute_query(f"SELECT * FROM `{t}`", fetch='all') or []

        # 2. 覆盖写入迁移 SQLite 文件
        if os.path.exists(path):
            os.remove(path)
        counts: Dict[str, int] = {}
        conn = await aiosqlite.connect(path)
        try:
            for t in self._TRANSFER_TABLES:
                await conn.execute(self._TRANSFER_SQLITE_DDL[t])
                rows = data[t]
                for r in rows:
                    cols = list(r.keys())
                    vals = [
                        self._format_datetime_for_sqlite(r[c]) if isinstance(r[c], datetime) else r[c]
                        for c in cols
                    ]
                    ph = ", ".join("?" for _ in cols)
                    await conn.execute(
                        f"INSERT INTO `{t}` ({', '.join(f'`{c}`' for c in cols)}) VALUES ({ph})", vals
                    )
                counts[t] = len(rows)
            await conn.commit()
        finally:
            await conn.close()

        logger.info(f"[NewAPI Utils] 数据库导出完成 → {path}，各表行数: {counts}")
        return {"path": path, "counts": counts}

    async def import_database(self) -> Dict[str, Any]:
        """导入：读取迁移文件 transfer.db，【清空当前活动数据库】对应表后整体写入。

        返回 {"path": 迁移文件路径, "counts": {表名: 行数}}。
        ⚠️ 破坏性操作：目标库中这四张表的现有数据会被替换。
        """
        path = await self._get_transfer_db_path()
        if not os.path.exists(path):
            raise FileNotFoundError(f"迁移文件不存在: {path}")

        # 1. 从迁移文件读取全量数据（缺表视为空）
        data: Dict[str, list] = {}
        conn = await aiosqlite.connect(path)
        try:
            conn.row_factory = aiosqlite.Row
            for t in self._TRANSFER_TABLES:
                cur = await conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (t,)
                )
                if await cur.fetchone() is None:
                    data[t] = []
                    continue
                cur = await conn.execute(f"SELECT * FROM `{t}`")
                data[t] = [dict(r) for r in await cur.fetchall()]
        finally:
            await conn.close()

        # 2. 安全防护：迁移文件四表全空时拒绝导入，防止误用空文件清空当前数据库
        total_rows = sum(len(v) for v in data.values())
        if total_rows == 0:
            logger.error(f"[NewAPI Utils] 迁移文件 {path} 中没有任何数据，已拒绝导入。")
            raise ValueError("迁移文件中没有任何数据")

        # 3. 清空目标表后逐行写入当前引擎
        counts: Dict[str, int] = {}
        for t in self._TRANSFER_TABLES:
            rows = data[t]
            await self.execute_query(f"DELETE FROM `{t}`")
            for r in rows:
                cols = list(r.keys())
                if self.db_mode == "sqlite":
                    vals = [
                        self._format_datetime_for_sqlite(r[c]) if isinstance(r[c], datetime) else r[c]
                        for c in cols
                    ]
                else:  # MySQL：datetime 对象可直接交由驱动处理
                    vals = [r[c] for c in cols]
                ph = ", ".join("%s" for _ in cols)  # _execute_sqlite 会自动转 ?
                await self.execute_query(
                    f"INSERT INTO `{t}` ({', '.join(f'`{c}`' for c in cols)}) VALUES ({ph})", tuple(vals)
                )
            counts[t] = len(rows)

        logger.info(f"[NewAPI Utils] 数据库导入完成 ← {path}，各表行数: {counts}")
        return {"path": path, "counts": counts}

    # ------------------------------------------------------------------ #
    #  红包（拼手气，凭空发放，24h 过期）                                #
    # ------------------------------------------------------------------ #

    def _get_red_packet_lock(self, packet_id: int) -> asyncio.Lock:
        """获取红包领取锁（懒创建；按红包 ID 串行化抢红包动作）。"""
        if packet_id not in self._red_packet_locks:
            self._red_packet_locks[packet_id] = asyncio.Lock()
        return self._red_packet_locks[packet_id]

    @staticmethod
    def _split_red_packet(total_raw: int, n: int) -> list:
        """微信式拼手气拆分：随机递减期望，总和恰好等于 total_raw，每份至少 1。"""
        shares = []
        remain = total_raw
        people = n
        for _ in range(n - 1):
            avg = remain // people
            high = max(1, 2 * avg)
            cap = remain - (people - 1)          # 给后面每人至少留 1
            amt = random.randint(1, max(1, min(high, cap)))
            shares.append(amt)
            remain -= amt
            people -= 1
        shares.append(max(1, remain))
        # 修正极端情况下总和偏差（理论上不会发生，保险起见）
        diff = total_raw - sum(shares)
        if diff:
            shares[-1] += diff
        return shares

    @staticmethod
    def _parse_dt(val) -> Optional[datetime]:
        """把 MySQL datetime / SQLite 时间字符串统一解析为 datetime。"""
        if isinstance(val, datetime):
            return val
        if isinstance(val, str):
            try:
                return datetime.strptime(val[:19].replace("T", " "), "%Y-%m-%d %H:%M:%S")
            except (ValueError, TypeError):
                return None
        return None

    # 红包代码字符集：小写字母+数字，剔除易混淆的 i/l/o/0/1
    RP_CODE_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"

    async def _rp_existing_codes(self) -> set:
        """仍处于「有效期 + 过期后 7 天冷却」内的红包代码集合；冷却结束的代码视为可复用。"""
        try:
            cutoff = self._format_datetime_for_sqlite(datetime.utcnow() - timedelta(days=7))
            rows = await self.execute_query(
                "SELECT rp_code FROM newapi_red_packets "
                "WHERE rp_code IS NOT NULL AND expire_at > %s",
                (cutoff,), fetch='all'
            )
            return {r["rp_code"] for r in rows} if rows else set()
        except Exception as e:
            logger.warning(f"[NewAPI Utils] 查询红包代码占用失败（按空处理）: {e}")
            return set()

    def _gen_rp_code(self, existing: set) -> str:
        """生成不与冷却期内代码冲突的 6 位随机码。"""
        for length in (6, 7, 8):
            for _ in range(50):
                code = "".join(random.choice(self.RP_CODE_ALPHABET) for _ in range(length))
                if code not in existing:
                    return code
        raise RuntimeError("红包代码生成失败")

    async def create_red_packet(self, creator_identity: str,
                                total_display: float, grab_count: int) -> Dict[str, Any]:
        """创建拼手气红包（凭空发放）。返回 {"pid", "code", "total_display", "grab_count", "expire_hours"}。

        金额按原始额度整数预拆分，保证各份之和精确等于总额。
        对外仅公布 code（6位随机码）；代码在「过期+7天冷却」后允许被复用。
        """
        conf = self.config.get('red_packet_settings', {})
        ratio = self.config.get('binding_settings.quota_display_ratio', 500000) or 1
        expire_hours = int(conf.get('expire_hours', 24))
        total_raw = int(round(total_display * ratio))
        # 防护：每份至少 1 原始额度，否则拆分会产生非正数份额
        if total_raw < grab_count:
            return {"error": "TOO_SMALL", "grab_count": grab_count}
        shares = self._split_red_packet(total_raw, grab_count)
        now = datetime.utcnow()
        expire = now + timedelta(hours=expire_hours)
        now_s = self._format_datetime_for_sqlite(now)
        exp_s = self._format_datetime_for_sqlite(expire)

        code = self._gen_rp_code(await self._rp_existing_codes())
        pid = await self.execute_query(
            "INSERT INTO newapi_red_packets (creator_identity, total_raw, total_display, display_ratio, "
            "grab_count, remain_count, shares_json, status, created_at, expire_at, rp_code) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, 'ACTIVE', %s, %s, %s)",
            (creator_identity, total_raw, float(total_display), ratio, grab_count, grab_count,
             json.dumps(shares), now_s, exp_s, code),
            return_lastrowid=True,
        )
        pid = int(pid) if pid else 0
        logger.info(f"[NewAPI Utils] 红包 #{pid}({code}) 已创建：{total_display} 额度 / {grab_count} 份 / {expire_hours}h 有效")
        return {"pid": pid, "code": code, "total_display": total_display,
                "grab_count": grab_count, "expire_hours": expire_hours}

    async def resolve_rp_packet(self, ref: str) -> Optional[Dict]:
        """按对外代码或数字 ID 解析红包行；数字优先按主键查，找不到再按代码查。"""
        ref = str(ref or "").strip().lower()
        if not ref:
            return None
        if ref.isdigit():
            row = await self.execute_query(
                "SELECT * FROM newapi_red_packets WHERE id = %s", (int(ref),), fetch='one'
            )
            if row:
                return row
        return await self.execute_query(
            "SELECT * FROM newapi_red_packets WHERE rp_code = %s", (ref,), fetch='one'
        )

    async def _rp_summary_entries(self, packet_id: int) -> list:
        """汇总某红包的全部领取记录，按金额从多到少排序。"""
        ratio = self.config.get('binding_settings.quota_display_ratio', 500000) or 1
        rows = await self.execute_query(
            "SELECT COALESCE(grabber_name, '') AS gname, identity, amount_raw "
            "FROM newapi_red_packet_records WHERE packet_id = %s",
            (packet_id,), fetch='all'
        )
        entries = [
            {"name": (r["gname"] or r["identity"]),
             "display": int(r["amount_raw"]) / ratio}
            for r in (rows or [])
        ]
        entries.sort(key=lambda e: e["display"], reverse=True)
        return entries

    async def grab_red_packet(self, packet_ref: str, identity: str,
                              website_user_id: int,
                              grabber_name: Optional[str] = None) -> Tuple[str, Dict[str, Any]]:
        """抢红包（支持对外代码或数字ID）。锁内完成：有效期校验 → 重复领取校验 →
        取份额 → 入账 → 记录(含昵称) → 扣减剩余份数；全部抢完时附带降序排行数据。

        status: SUCCESS / ALREADY / EMPTY / EXPIRED / NOT_FOUND / DISABLED / API_ERROR
        """
        conf = self.config.get('red_packet_settings', {})
        if not conf.get('enabled', True):
            return "DISABLED", {}
        ratio = self.config.get('binding_settings.quota_display_ratio', 500000) or 1

        # 先解析真实主键，再按主键加锁，保证同一红包并发串行
        p0 = await self.resolve_rp_packet(packet_ref)
        if not p0:
            return "NOT_FOUND", {}
        packet_id = int(p0["id"])

        lock = self._get_red_packet_lock(packet_id)
        async with lock:
            p = await self.execute_query(
                "SELECT * FROM newapi_red_packets WHERE id = %s", (packet_id,), fetch='one'
            )
            if not p:
                return "NOT_FOUND", {}
            if p['status'] == 'EXPIRED':
                return "EXPIRED", {}
            if p['status'] != 'ACTIVE' or int(p['remain_count']) <= 0:
                return "EMPTY", {}

            expire_at = self._parse_dt(p.get('expire_at'))
            if expire_at and datetime.utcnow() >= expire_at:
                await self.execute_query(
                    "UPDATE newapi_red_packets SET status = 'EXPIRED' WHERE id = %s", (packet_id,)
                )
                return "EXPIRED", {}

            dup = await self.execute_query(
                "SELECT id FROM newapi_red_packet_records WHERE packet_id = %s AND identity = %s",
                (packet_id, identity), fetch='one'
            )
            if dup:
                return "ALREADY", {}

            idx = int(p['grab_count']) - int(p['remain_count'])
            try:
                shares = json.loads(p['shares_json'])
                amount_raw = int(shares[idx])
            except (ValueError, KeyError, IndexError, TypeError):
                return "EMPTY", {}

            # 先入账，入账失败不消耗份额（可重试）
            if not await self.manage_user_quota(website_user_id, "add", amount_raw):
                return "API_ERROR", {}

            try:
                await self.execute_query(
                    "INSERT INTO newapi_red_packet_records (packet_id, identity, website_user_id, amount_raw, grabber_name) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (packet_id, identity, website_user_id, amount_raw, grabber_name)
                )
            except Exception as e:
                # 唯一键冲突=已抢过（并发兜底）；其他异常同样不重复入账
                logger.warning(f"[NewAPI Utils] 红包记录写入受限（可能重复领取）: {e}")
                return "ALREADY", {}

            new_remain = int(p['remain_count']) - 1
            new_status = 'EXHAUSTED' if new_remain <= 0 else 'ACTIVE'
            await self.execute_query(
                "UPDATE newapi_red_packets SET remain_count = %s, status = %s WHERE id = %s",
                (new_remain, new_status, packet_id)
            )

            details = {
                "amount_display": amount_raw / ratio,
                "remain": new_remain,
                "total": int(p['grab_count']),
                "code": p.get('rp_code') or str(packet_id),
            }
            if new_status == 'EXHAUSTED':
                details["exhausted"] = True
                details["entries"] = await self._rp_summary_entries(packet_id)
            return "SUCCESS", details

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

    async def get_user_by_openid(self, openid: str) -> Optional[Dict]:
        """通过 OpenID 查找绑定（newapi_openid_bindings 表）。"""
        return await self.execute_query(
            "SELECT * FROM newapi_openid_bindings WHERE openid = %s", (openid,), fetch='one'
        )

    async def get_openid_by_website_id(self, website_user_id: int) -> Optional[Dict]:
        """通过网站用户 ID 查找 OpenID 绑定。"""
        return await self.execute_query(
            "SELECT * FROM newapi_openid_bindings WHERE website_user_id = %s", (website_user_id,), fetch='one'
        )

    async def insert_openid_binding(self, openid: str, website_user_id: int) -> int:
        """插入 OpenID 绑定记录。"""
        return await self.execute_query(
            "INSERT INTO newapi_openid_bindings (openid, website_user_id) VALUES (%s, %s)",
            (openid, website_user_id)
        )

    async def delete_openid_binding(self, *, openid: Optional[str] = None,
                                    website_user_id: Optional[int] = None) -> int:
        """删除 OpenID 绑定记录。"""
        if openid:
            return await self.execute_query(
                "DELETE FROM newapi_openid_bindings WHERE openid = %s", (openid,)
            )
        if website_user_id:
            return await self.execute_query(
                "DELETE FROM newapi_openid_bindings WHERE website_user_id = %s", (website_user_id,)
            )
        return 0

    async def get_user_by_identity(self, user_id) -> Optional[Dict]:
        """按身份查找绑定：数字（QQ号）走 newapi_bindings，字符串（OpenID）走 newapi_openid_bindings。
        
        返回字段统一含 website_user_id，QQ 绑定额外含 qq_id，OpenID 绑定额外含 openid。
        """
        if isinstance(user_id, int) or (isinstance(user_id, str) and user_id.strip().lstrip('-').isdigit()):
            return await self.get_user_by_qq(int(user_id))
        if isinstance(user_id, str) and user_id.strip():
            return await self.get_user_by_openid(user_id.strip())
        return None

    async def get_api_user_data(self, user_id: int) -> Optional[Dict]:
        response = await self.api_request("GET", f"/api/user/{user_id}")
        if response and response.get("success"):
            return response.get("data")
        return None

    async def _http_request_json(self, method: str, url: str, headers: Dict[str, str],
                                 json_data: Optional[Dict] = None) -> Optional[Dict]:
        """发送 HTTP 请求并解析 JSON；非 2xx 或异常返回 None（供自定义鉴权头请求复用）。"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.request(
                    method, url, headers=headers, json=json_data, timeout=10.0
                )
            if not response.is_success:
                logger.info(f"[NewAPI Utils] HTTP {response.status_code} {url}: {response.text[:200]}")
                return None
            return response.json()
        except Exception as e:
            logger.warning(f"[NewAPI Utils] HTTP 请求失败 {method} {url}: {e}")
            return None

    async def get_self_by_user_token(self, token: str) -> Optional[Dict]:
        """用网站用户的系统访问令牌调用 GET /api/user/self 验证身份。

        令牌有效时返回 {"user_id": int, "username": str}；无效/网络失败返回 None。
        """
        if not self.api_base_url or not token or not str(token).strip():
            return None
        token = str(token).strip()
        if token.lower().startswith("bearer "):
            token = token[7:].strip()
        url = f"{self.api_base_url.rstrip('/')}/api/user/self"
        data = await self._http_request_json("GET", url, {"Authorization": f"Bearer {token}"})
        if data and data.get("success"):
            user = data.get("data") or {}
            uid = user.get("id")
            try:
                return {"user_id": int(uid), "username": user.get("username")}
            except (TypeError, ValueError):
                return None
        return None

    async def get_user_token_consumption(self, hours: int = 24) -> Optional[list]:
        """聚合近 N 小时全站消耗日志（type=2），按网站用户 ID 汇总 token 消耗。

        通过 New API 后台接口 GET /api/log/ 分页拉取并聚合，返回：
            [{"user_id": int, "username": str, "tokens": int, "quota": int}, ...]
        其中 tokens = prompt_tokens + completion_tokens，quota 为累计消耗的原始额度。失败返回 None。
        注意：需要 New API 已开启「记录消耗日志」（LogConsumeEnabled），否则榜单为空。
        """
        end_ts = int(time.time())
        start_ts = end_ts - max(1, int(hours)) * 3600
        page_size = 100      # New API 服务端单页上限为 100
        max_pages = 100      # 最多聚合 100 页（约 1 万条日志），防止超大站点拖垮命令
        stats: Dict[int, Dict[str, Any]] = {}
        page = 1
        while page <= max_pages:
            endpoint = (
                f"/api/log/?type=2&start_timestamp={start_ts}&end_timestamp={end_ts}"
                f"&p={page}&page_size={page_size}"
            )
            resp = await self.api_request("GET", endpoint)
            if not resp or not resp.get("success"):
                return None
            data = resp.get("data") or {}
            items = data.get("items") or []
            if not items:
                break
            total = int(data.get("total") or 0)
            for item in items:
                user_id = item.get("user_id")
                if user_id is None:
                    continue
                tokens = int(item.get("prompt_tokens") or 0) + int(item.get("completion_tokens") or 0)
                entry = stats.setdefault(user_id, {
                    "user_id": user_id,
                    "username": item.get("username") or "",
                    "tokens": 0,
                    "quota": 0,
                })
                entry["tokens"] += tokens
                entry["quota"] += int(item.get("quota") or 0)
                if not entry["username"] and item.get("username"):
                    entry["username"] = item["username"]
            if page * page_size >= total:
                break
            page += 1
        return list(stats.values())

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

    def _get_check_in_lock(self, website_user_id: int) -> asyncio.Lock:
        """获取指定网站账号的签到锁（懒创建；纯同步无 await，事件循环内天然原子）。"""
        if website_user_id not in self._check_in_locks:
            self._check_in_locks[website_user_id] = asyncio.Lock()
        return self._check_in_locks[website_user_id]

    def _get_user_rp_lock(self, website_user_id) -> asyncio.Lock:
        """获取指定网站账号的个人红包发送锁（懒创建；键统一为 str）。"""
        key = str(website_user_id)
        if key not in self._user_rp_locks:
            self._user_rp_locks[key] = asyncio.Lock()
        return self._user_rp_locks[key]

    async def get_check_in_state(self, website_user_id: int) -> Optional[Dict]:
        """获取指定网站账号的持久化签到状态（按网站用户去重，防止多 QQ 轮流绑同一账号刷礼包与重复签到）。"""
        return await self.execute_query(
            "SELECT * FROM newapi_check_in_state WHERE website_user_id = %s", (website_user_id,), fetch='one'
        )

    async def set_check_in_time(self, website_user_id: int) -> int:
        """写入/更新指定网站账号的签到时间到独立状态表（跨引擎 upsert）。"""
        # datetime.utcnow() 存储为字符串以兼容 SQLite
        now_str = self._format_datetime_for_sqlite(datetime.utcnow())
        existing = await self.get_check_in_state(website_user_id)
        if existing:
            return await self.execute_query(
                "UPDATE newapi_check_in_state SET last_check_in_time = %s WHERE website_user_id = %s",
                (now_str, website_user_id)
            )
        return await self.execute_query(
            "INSERT INTO newapi_check_in_state (website_user_id, last_check_in_time) VALUES (%s, %s)",
            (website_user_id, now_str)
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

        website_user_id = binding['website_user_id']
        # 按网站账号加签到锁，防止同一账号并发签到绕过「今日已签到」检查（TOCTOU 重复领奖）
        async with self._get_check_in_lock(website_user_id):
            return await self._perform_check_in_locked(qq_id, binding, check_in_conf)

    async def _perform_check_in_locked(self, qq_id: int, binding: Dict, check_in_conf: Dict) -> Tuple[str, Dict[str, Any]]:
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
        # 签到时间按【网站用户】持久化：退群/解绑不清除，且防止多个 QQ 轮流绑定同一网站账号刷礼包与重复签到。
        # 兼容旧数据：状态表无记录时回退到绑定记录上的 last_check_in_time，实现一次性迁移。
        website_user_id = binding['website_user_id']
        state = await self.get_check_in_state(website_user_id)
        last_check_in_time = state.get('last_check_in_time') if state else binding.get('last_check_in_time')
        is_first_check_in = last_check_in_time is None

        if not is_first_check_in:
            local_last_check_in_date = (last_check_in_time + time_delta).date()
            if local_last_check_in_date == local_today:
                return "ALREADY_CHECKED_IN", {}

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

        await self.set_check_in_time(website_user_id)

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
        openid_binding = await self.get_openid_by_website_id(website_user_id)
        if not binding_info and not openid_binding:
            logger.warning(f"净化请求失败：未找到网站ID {website_user_id} 的绑定记录。")
            return False, None
        try:
            if binding_info:
                logger.info(f"开始净化网站ID {website_user_id} (QQ: {binding_info['qq_id']})...")
                await self.revert_user_group(website_user_id)
                await self.delete_binding(website_user_id=website_user_id)
            if openid_binding:
                logger.info(f"开始净化网站ID {website_user_id} (OpenID: {openid_binding['openid']})...")
                await self.delete_openid_binding(website_user_id=website_user_id)
            logger.info(f"净化成功：已删除网站ID {website_user_id} 的所有绑定记录。")
            return True, (binding_info or openid_binding)
        except Exception as e:
            logger.error(f"执行净化网站ID {website_user_id} 的过程中发生未知错误: {e}", exc_info=True)
            return False, (binding_info or openid_binding)

    async def lookup_binding(self, identifier) -> Tuple[str, Optional[Dict]]:
        """智能查找绑定：int 按网站ID/QQ号，string 按 OpenID（若为数字字符串则回退到 int 查找）。"""
        if isinstance(identifier, str):
            # 字符串：先尝试 OpenID 匹配
            binding = await self.get_user_by_openid(identifier)
            if binding:
                return "OPENID", binding
            # 纯数字字符串 → 转为 int 走常规查找
            if identifier.strip().lstrip('-').isdigit():
                identifier = int(identifier)
            else:
                return "NOT_FOUND", None

        # 数字：网站ID 或 QQ号
        if isinstance(identifier, int):
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
