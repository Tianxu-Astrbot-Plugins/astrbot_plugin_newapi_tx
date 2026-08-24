import os
import asyncio
from typing import Optional, Tuple
from functools import wraps
from astrbot.api import logger, AstrBotConfig
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent
from astrbot.api.message_components import At

from .newapi_utils import NewApiCore
from .heist_logic import HeistLogic
from .i18n import translate

def load_plugin_version() -> str:
    """
    从插件根目录的 metadata.yaml 读取 version 字段，
    作为本插件的唯一版本来源，避免主代码中硬编码版本号。
    """
    try:
        metadata_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "metadata.yaml"
        )
        with open(metadata_path, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped.startswith("version:"):
                    version = stripped.split(":", 1)[1].strip().strip('"').strip("'")
                    if version:
                        return version
    except Exception as e:
        logger.warning(f"读取 metadata.yaml 版本号失败，使用默认版本: {e}")
    return "1.0.4"

PLUGIN_VERSION = load_plugin_version()

def require_binding(f):
    """
    检查命令发起者是否绑定网站ID，若未绑定则中断并提示，若已绑定则附加binding对象以便后续使用。
    同时支持 QQ 号绑定（int）与 OpenID 绑定（str）。
    """
    @wraps(f)
    async def wrapper(self, event: AstrMessageEvent, *args, **kwargs):
        sender_id = event.get_sender_id()
        
        # 避免重复获取binding
        if hasattr(event, 'binding'):
            async for item in f(self, event, *args, **kwargs):
                yield item
            return

        binding = await self.core.get_user_by_identity(sender_id)

        if not binding:
            yield event.plain_result(self.t("not_bound"))
            return
        
        # 附加binding对象到event
        event.binding = binding
        
        async for item in f(self, event, *args, **kwargs):
            yield item
            
    return wrapper

def require_group_whitelist(f):
    """
    仅当消息来自白名单群（或白名单功能未启用）时放行，否则静默忽略、不回复。

    用于「签到 / 打劫 / 查询余额」等仅允许在配置群内响应的命令。
    """
    @wraps(f)
    async def wrapper(self, event: AstrMessageEvent, *args, **kwargs):
        if not self._command_group_allowed(event):
            return
        async for item in f(self, event, *args, **kwargs):
            yield item
            
    return wrapper

@register(
    "NewAPI_plugin",
    "Future-404",
    "集成了核心用户管理与娱乐功能的New API插件套件。",
    PLUGIN_VERSION
)
class NewApiSuitePlugin(Star):
    """
    New API 功能套件主插件类，作为功能套件的唯一入口点。
    """
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.core = NewApiCore(config)
        self.heist_handler = HeistLogic(config, self.core)
        # 回复语言：zh / en（配置 i18n_settings.language）
        self.lang = self._resolve_language()
        # 余额缓存：用户每次操作时顺手更新，排行榜直接读缓存无需查 API
        self._balance_cache: dict[int, tuple[int, int]] = {}
        # KV 绑定缓存读-改-写锁，避免并发操作互相覆盖丢失更新
        self._kv_lock = asyncio.Lock()
        logger.info("[NewAPI Suite] 插件已实例化，准备进行异步初始化...")

    def _resolve_language(self) -> str:
        """解析回复语言，缺省中文。"""
        lang = self.config.get('i18n_settings.language', 'zh')
        return "en" if str(lang).lower().startswith("en") else "zh"

    def t(self, key: str, **kwargs) -> str:
        """翻译运行时消息。"""
        return translate(self.lang, key, **kwargs)

    def _is_debug(self) -> bool:
        """是否开启调试模式（debug_settings.enabled），动态读取便于随时切换。"""
        return bool(self.config.get('debug_settings.enabled', False))

    def _command_group_allowed(self, event: AstrMessageEvent) -> bool:
        """判断当前消息是否命中群白名单：白名单未启用时一律放行。

        启用后，仅当消息来自 group_whitelist_settings.group_list 中列出的群时返回 True；
        私聊（group_id 为空）与未列出的群一律返回 False，实现「只监听配置群」。
        """
        conf = self.config.get('group_whitelist_settings', {})
        if not conf.get('enabled', False):
            return True
        group_list = conf.get('group_list', [])
        allowed = {str(g) for g in group_list if str(g).strip()}
        group_id = str(event.get_group_id() or "")
        return group_id in allowed

    async def _update_binding_cache(self, website_user_id, qq_id: Optional[int]):
        """更新 KV 绑定缓存单条映射（qq_id 为 None 表示删除），加锁避免并发读改写竞态。"""
        async with self._kv_lock:
            cache = await self.get_kv_data("binding_cache", {})
            if qq_id is None:
                cache.pop(str(website_user_id), None)
            else:
                cache[str(website_user_id)] = qq_id
            await self.put_kv_data("binding_cache", cache)

    @staticmethod
    def _extract_at_qq(event: AstrMessageEvent) -> Optional[int]:
        """提取消息中第一个 @ 提及（排除机器人自身）的 QQ 号，无则返回 None。"""
        for seg in event.get_messages():
            if isinstance(seg, At) and seg.qq != int(event.get_self_id()):
                return seg.qq
        return None

    @staticmethod
    def _parse_int_safe(value) -> Optional[int]:
        s = str(value).strip() if value is not None else ""
        return int(s) if s.lstrip('-').isdigit() else None

    def _resolve_target(self, event: AstrMessageEvent, identifier) -> Optional[int]:
        """解析查询/操作目标：优先 @ 提及的 QQ，否则解析数字 ID（网站ID或QQ号）。"""
        at_qq = self._extract_at_qq(event)
        if at_qq is not None:
            return at_qq
        return self._parse_int_safe(identifier)

    async def initialize(self):
        init_success = await self.core.initialize()
        if init_success:
            logger.info("[NewAPI Suite] 核心服务初始化成功。" )
        else:
            logger.error("[NewAPI Suite] 核心服务初始化失败。" )

    async def terminate(self):
        """插件被禁用或重载时调用，清空 KV 绑定缓存。"""
        await self.delete_kv_data("binding_cache")
        logger.info("[NewAPI Suite] KV 绑定缓存已清空。")


    @filter.command("pingapi")
    async def handle_ping_command(self, event: AstrMessageEvent):
        """响应ping命令，并报告数据库与 New API 连接状态。"""
        db_status = self.t("ping.connected") if self.core.is_db_ready() else self.t("ping.disconnected")
        api_status = self.t("ping.connected") if await self.core.check_api_connection() else self.t("ping.disconnected")
        engine = "SQLite" if self.core.db_mode == "sqlite" else "MySQL"
        reply = (
            f"{self.t('ping.running', version=PLUGIN_VERSION)}\n"
            "--------------------\n"
            f"{self.t('ping.db_engine')}: {engine}\n"
            f"{self.t('ping.db_status')}: {db_status}\n"
            f"{self.t('ping.api_status')}: {api_status}"
        )
        yield event.plain_result(reply)

    @filter.command("查询余额")
    @require_group_whitelist
    @require_binding
    async def handle_query_balance(self, event: AstrMessageEvent):
        """允许已绑定用户查询网站余额。"""
        binding = event.binding
        website_user_id = binding['website_user_id']
        api_user_data = await self.core.get_api_user_data(website_user_id)

        if not api_user_data:
            yield event.plain_result(self.t("query_balance.failed"))
            return

        binding_conf = self.config.get('binding_settings', {})
        ratio = binding_conf.get('quota_display_ratio', 500000)
        display_quota = api_user_data.get("quota", 0) / ratio

        reply = self.t("query_balance.success", site_id=website_user_id, quota=f"{display_quota:.6f}")

        # 顺便更新余额缓存，供排行榜使用
        self._balance_cache[website_user_id] = (binding['qq_id'], api_user_data.get("quota", 0))
        
        yield event.plain_result(reply)

    @filter.command("查余额")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def handle_query_other_balance(self, event: AstrMessageEvent, identifier: str = ""):
        """(管理员) 智能识别 @ 提及、网站ID或QQ号，查询其网站余额。"""
        target_id = self._resolve_target(event, identifier)
        if target_id is None:
            yield event.plain_result(self.t("common.at_or_id_required"))
            return
        id_type, binding = await self.core.lookup_binding(target_id)
        if id_type == "NOT_FOUND":
            yield event.plain_result(self.t("query_other.not_found", id=target_id))
            return

        website_user_id = binding['website_user_id']
        api_user_data = await self.core.get_api_user_data(website_user_id)
        if not api_user_data:
            yield event.plain_result(self.t("query_other.failed"))
            return

        ratio = self.config.get('binding_settings.quota_display_ratio', 500000)
        display_quota = api_user_data.get("quota", 0) / ratio
        label = self.t("query_other.label_website") if id_type == "WEBSITE_ID" else self.t("query_other.label_qq")

        reply = self.t("query_other.success", label=label, id=target_id, site_id=website_user_id, quota=f"{display_quota:.6f}")
        yield event.plain_result(reply)

    @filter.command("绑定")
    async def handle_bind_command(self, event: AstrMessageEvent, website_user_id: str = ""):
        """处理用户绑定请求，并执行校验。支持 QQ 号绑定 与（开启开关后）OpenID 绑定。"""
        # 网站ID 人工校验：缺失/非数字时给出人类可读提示，避免框架类型转换直接抛异常
        raw_id = str(website_user_id or "").strip()
        if not raw_id:
            yield event.plain_result(self.t("bind.id_required"))
            return
        if not raw_id.isdigit():
            yield event.plain_result(self.t("bind.id_invalid", input=raw_id))
            return
        site_id = int(raw_id)

        binding_conf = self.config.get('binding_settings', {})
        sender_id = event.get_sender_id()
        openid_enabled = binding_conf.get('enable_openid_binding', False)
        # 官机环境 sender_id 为 openid 字符串（非纯数字）时，走 OpenID 绑定
        is_openid_sender = (
            openid_enabled
            and isinstance(sender_id, str)
            and not sender_id.strip().lstrip('-').isdigit()
        )

        if is_openid_sender:
            openid = sender_id.strip()
            yield event.plain_result(await self._perform_openid_binding(event, openid, site_id))
            return

        user_qq_id = sender_id

        error_message = (
            await self._check_self_binding(user_qq_id) or
            await self._check_qq_level(event, user_qq_id) or
            await self._check_user_blacklist(user_qq_id) or
            await self._check_website_id_blacklist(site_id) or
            await self._check_api_user_exists(site_id) or
            await self._check_id_uniqueness(site_id)
        )
        
        if error_message:
            yield event.plain_result(error_message)
            return
        
        yield event.plain_result(self.t("bind.validating"))
        
        success, message = await self._perform_binding_ritual(user_qq_id, site_id)
        
        if success:
            await self._update_binding_cache(site_id, user_qq_id)
            await self._send_success_pm(event, user_qq_id, site_id)
        
        yield event.plain_result(message)

    @filter.command("签到")
    @require_group_whitelist
    @require_binding
    async def handle_check_in(self, event: AstrMessageEvent):
        """处理用户每日签到请求。"""
        user_qq_id = event.get_sender_id()
        
        status, details = await self.core.perform_check_in(user_qq_id, binding=event.binding)
        
        check_in_conf = self.config.get('check_in_settings', {})
        
        reply = ""
        match status:
            case "SUCCESS":
                first_bonus_enabled = check_in_conf.get('first_check_in_bonus_enabled', False)
                ratio = self.config.get('binding_settings.quota_display_ratio', 500000)

                if details["is_first"] and first_bonus_enabled:
                    template = check_in_conf.get('first_check_in_success_template')
                elif details["is_doubled"]:
                    template = check_in_conf.get('check_in_doubled_template')
                else:
                    template = check_in_conf.get('check_in_success_template')
                
                reply = template.format(
                    display_added=f"{details['display_added']:.6f}", 
                    display_total=f"{details['display_total']:.6f}",
                    user_qq=details['user_qq'],
                    site_id=details['site_id']
                )
                # 签到成功后顺便更新余额缓存，供排行榜使用
                new_raw_quota = int(details['display_total'] * ratio)
                self._balance_cache[details['site_id']] = (details['user_qq'], new_raw_quota)
            case "DISABLED":
                reply = self.t("check_in.disabled")
            case "ALREADY_CHECKED_IN":
                reply = self.t("check_in.already")
            case "API_USER_NOT_FOUND":
                reply = self.t("check_in.api_user_not_found")
            case "API_UPDATE_FAILED":
                reply = self.t("check_in.api_update_failed")
            case _:
                reply = self.t("check_in.unknown")
        
        yield event.plain_result(reply)
    @filter.command("解绑")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def handle_unbind_command(self, event: AstrMessageEvent, website_user_id: str = ""):
        """(管理员) 强制解除指定网站ID的绑定。"""
        # 人工校验：非数字时给出人类可读提示，避免框架类型转换直接抛异常
        raw_id = str(website_user_id or "").strip()
        if not raw_id:
            yield event.plain_result(self.t("bind.id_required"))
            return
        if not raw_id.isdigit():
            yield event.plain_result(self.t("bind.id_invalid", input=raw_id))
            return
        site_id = int(raw_id)

        success, binding_info = await self.core.purge_user_binding(site_id)
        
        reply = ""
        if success:
            await self._update_binding_cache(site_id, None)
            # QQ 绑定显示 qq_id；仅 OpenID 绑定时显示 openid
            identity = binding_info.get('qq_id', binding_info.get('openid'))
            reply = self.t("unbind.success", site_id=site_id, qq=identity)
        else:
            if binding_info is None:
                reply = self.t("unbind.not_found", site_id=site_id)
            else:
                reply = self.t("unbind.failed", site_id=site_id)
                
        yield event.plain_result(reply)

    @filter.command("查询")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def handle_universal_lookup(self, event: AstrMessageEvent, identifier: str = ""):
        """(管理员) 智能查询，自动识别网站ID或QQ号。"""
        raw_id = str(identifier or "").strip()
        if not raw_id:
            yield event.plain_result(self.t("common.at_or_id_required"))
            return
        if not raw_id.isdigit():
            yield event.plain_result(self.t("bind.id_invalid", input=raw_id))
            return
        target_id = int(raw_id)

        id_type, binding = await self.core.lookup_binding(target_id)
        
        reply = ""
        match id_type:
            case "WEBSITE_ID":
                reply = self.t("lookup.website", site_id=binding['website_user_id'], qq=binding['qq_id'], time=binding['binding_time'].strftime('%Y-%m-%d %H:%M:%S'))
            case "QQ_ID":
                reply = self.t("lookup.qq", qq=binding['qq_id'], site_id=binding['website_user_id'], time=binding['binding_time'].strftime('%Y-%m-%d %H:%M:%S'))
            case "NOT_FOUND":
                reply = self.t("lookup.not_found", id=target_id)
        
        yield event.plain_result(reply)

    @filter.command("new-tx")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def handle_db_transfer(self, event: AstrMessageEvent, action: str = ""):
        """(管理员) 数据库导入导出：导出=当前库内容写入迁移文件；导入=迁移文件覆盖当前库。"""
        act = str(action or "").strip()
        if act not in ("导出", "导入"):
            yield event.plain_result(self.t("db_transfer.usage"))
            return

        act_label = self.t("db_transfer.act_export") if act == "导出" else self.t("db_transfer.act_import")
        yield event.plain_result(self.t("db_transfer.working", action=act_label))

        try:
            if act == "导出":
                result = await self.core.export_database()
                done_key = "db_transfer.export_done"
            else:
                result = await self.core.import_database()
                done_key = "db_transfer.import_done"
            detail = self._format_transfer_counts(result["counts"])
            total = sum(result["counts"].values())
            reply = self.t(done_key, detail=detail, total=total)
        except FileNotFoundError:
            reply = self.t("db_transfer.no_file")
        except ValueError:
            # 迁移文件为空，安全防护拒绝导入
            reply = self.t("db_transfer.empty_file")
        except Exception as e:
            logger.error(f"数据库{act}操作失败: {e}", exc_info=True)
            reply = self.t("db_transfer.failed", action=act_label, err=e)

        yield event.plain_result(reply)

    def _format_transfer_counts(self, counts: dict) -> str:
        """把各表行数格式化为多行人类可读明细。"""
        labels = {
            "newapi_bindings": "db_transfer.label_bindings",
            "newapi_openid_bindings": "db_transfer.label_openid_bindings",
            "newapi_check_in_state": "db_transfer.label_check_in_state",
            "daily_heist_log": "db_transfer.label_heist_log",
        }
        return "\n".join(
            self.t("db_transfer.detail_line", label=self.t(key), count=counts.get(table, 0))
            for table, key in labels.items()
        )

    # --- 红包（拼手气） ---

    @filter.command("发红包")
    @filter.permission_type(filter.PermissionType.ADMIN)
    @require_group_whitelist
    async def handle_send_red_packet(self, event: AstrMessageEvent, count: str = "", amount: str = ""):
        """(管理员) 发拼手气红包：发红包 数量 总额度（凭空发放，24h 有效）。"""
        conf = self.config.get('red_packet_settings', {})
        if not conf.get('enabled', True):
            yield event.plain_result(self.t("rp.disabled"))
            return

        raw_count = str(count or "").strip()
        raw_amount = str(amount or "").strip()

        if not raw_count:
            yield event.plain_result(self.t("rp.count_required"))
            return
        if not raw_count.isdigit():
            yield event.plain_result(self.t("rp.count_invalid", input=raw_count))
            return
        grab_count = int(raw_count)
        max_count = int(conf.get('max_grab_count', 100))
        if grab_count <= 0 or grab_count > max_count:
            yield event.plain_result(self.t("rp.count_too_large", max=max_count))
            return

        if not raw_amount:
            yield event.plain_result(self.t("rp.amount_required"))
            return
        try:
            total_display = round(float(raw_amount), 6)
        except ValueError:
            yield event.plain_result(self.t("rp.amount_invalid", input=raw_amount))
            return
        if total_display <= 0:
            yield event.plain_result(self.t("rp.amount_invalid", input=raw_amount))
            return
        max_total = float(conf.get('max_total_display', 100000))
        if total_display > max_total:
            yield event.plain_result(self.t("rp.amount_too_large", max=f"{max_total:g}"))
            return

        # 每份至少 1 原始额度，总额过低无法拆分
        ratio = self.config.get('binding_settings.quota_display_ratio', 500000) or 1
        if int(round(total_display * ratio)) < grab_count:
            yield event.plain_result(self.t("rp.too_small", count=grab_count))
            return

        creator = str(event.get_sender_id())
        result = await self.core.create_red_packet(creator, total_display, grab_count)
        if not result or result.get('error') or not result.get('pid'):
            yield event.plain_result(self.t("rp.api_error"))
            return
        amount_str = f"{total_display:.6f}".rstrip('0').rstrip('.')
        yield event.plain_result(self.t(
            "rp.created", pid=result['pid'], count=grab_count,
            amount=amount_str, hours=result['expire_hours'], creator=creator,
        ))

    @filter.command("抢红包")
    @require_group_whitelist
    async def handle_grab_red_packet(self, event: AstrMessageEvent, packet_id: str = ""):
        """抢拼手气红包：抢红包 红包编号。额度直接入账网站余额。"""
        raw_pid = str(packet_id or "").strip()
        if not raw_pid:
            yield event.plain_result(self.t("rp.pid_required"))
            return
        if not raw_pid.isdigit():
            yield event.plain_result(self.t("rp.pid_invalid", input=raw_pid))
            return
        pid = int(raw_pid)

        identity = str(event.get_sender_id())
        binding = await self.core.get_user_by_identity(identity)
        if not binding:
            yield event.plain_result(self.t("not_bound"))
            return
        site_id = binding['website_user_id']

        status, details = await self.core.grab_red_packet(pid, identity, site_id)

        reply = ""
        match status:
            case "SUCCESS":
                amount_str = f"{details['amount_display']:.6f}"
                reply = self.t("rp.success", amount=amount_str,
                               remain=details['remain'], total=details['total'])
                # 抢到后顺便更新余额缓存，供排行榜使用
                data = await self.core.get_api_user_data(site_id)
                if data:
                    self._balance_cache[site_id] = (
                        binding.get('qq_id', binding.get('openid')), data.get('quota', 0)
                    )
            case "ALREADY":
                reply = self.t("rp.already")
            case "EMPTY":
                reply = self.t("rp.empty")
            case "EXPIRED":
                reply = self.t("rp.expired")
            case "NOT_FOUND":
                reply = self.t("rp.not_found", pid=pid)
            case "DISABLED":
                reply = self.t("rp.disabled")
            case _:
                reply = self.t("rp.api_error")

        yield event.plain_result(reply)

    @filter.command("调整余额")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def handle_adjust_balance(
        self, event: AstrMessageEvent, identifier: str = "", display_adjustment: float = 0.0
    ):
        """(管理员) 智能识别 @ 提及、网站ID或QQ号，并调整用户显示额度。"""
        at_qq = self._extract_at_qq(event)
        if at_qq is not None:
            # @ 场景：目标为 @ 提及的 QQ。
            # 注意：At 段在 AstrBot 的 message_str 中会变成 "@昵称(QQ)" 文本并占据 identifier 位置，
            # 真正金额由 AstrBot 解析到 display_adjustment（float），故此处不解析 identifier。
            target_id = at_qq
        else:
            # 非 @ 场景：目标为数字 ID（网站ID 或 QQ号）
            target_id = self._parse_int_safe(identifier)

        if target_id is None:
            yield event.plain_result(self.t("common.at_or_id_required"))
            return

        # 金额统一取 display_adjustment（AstrBot 已把数字参数转为 float）；0 视为未提供（调整 0 额度无意义）
        amount = display_adjustment
        if amount == 0.0:
            yield event.plain_result(self.t("common.amount_required"))
            return

        status, details = await self.core.adjust_balance_by_identifier(target_id, amount)

        reply = ""
        match status:
            case "SUCCESS":
                key = "adjust.success_inc" if amount >= 0 else "adjust.success_dec"
                reply = self.t(key, site_id=details['website_user_id'], amount=f"{abs(amount):.6f}", total=f"{details['new_display_quota']:.6f}")
            case "USER_NOT_FOUND":
                reply = self.t("adjust.not_found", id=target_id)
            case "API_FETCH_FAILED":
                reply = self.t("adjust.fetch_failed", site_id=details['website_user_id'])
            case "API_UPDATE_FAILED":
                reply = self.t("adjust.update_failed", site_id=details['website_user_id'])

        yield event.plain_result(reply)

    @filter.command("打劫")
    @require_group_whitelist
    async def handle_heist_command(self, event: AstrMessageEvent, identifier: str = ""):
        """(娱乐) 打劫目标：@ 提及，或输入 QQ 号 / OpenID（开启 openid 绑定后支持）。"""
        robber_qq_id = event.get_sender_id()

        # 1. 提取目标：优先 @ 提及，其次文本参数（QQ号 / 网站ID / OpenID）
        target_qq_ids = [
            seg.qq  # 从At消息段中提取qq号
            for seg in event.get_messages()
            if isinstance(seg, At) and seg.qq != int(event.get_self_id())
        ]

        # 2. 校验
        if len(target_qq_ids) > 1:
            yield event.plain_result(self.t("heist.too_many"))
            return

        if target_qq_ids:
            victim_identifier = target_qq_ids[0]  # @：QQ 号
        else:
            raw = (identifier or "").strip()
            if not raw:
                yield event.plain_result(self.t("heist.no_target"))
                return
            # 文本参数：优先数字（QQ号/网站ID），否则视为 OpenID（需开启 openid 绑定）
            if raw.lstrip('-').isdigit():
                victim_identifier = int(raw)
            else:
                openid_conf = self.config.get('binding_settings', {})
                if not openid_conf.get('enable_openid_binding', False):
                    yield event.plain_result(self.t("heist.no_target"))
                    return
                victim_identifier = raw

        status, details = await self.heist_handler.execute_heist(robber_qq_id, victim_identifier)
        
        # 4. 根据结果生成回复
        heist_conf = self.config.get('heist_settings', {})
        reply = ""

        # --- 缓存模板 ---
        success_template = heist_conf.get('success_template', "成功: +{gain:.2f}")
        critical_template = heist_conf.get('critical_template', "暴击: +{gain:.2f}")
        failure_template = heist_conf.get('failure_template', "失败: -{penalty:.2f}")
        disabled_template = heist_conf.get('disabled_template', "⚔️ 打劫活动尚未开启。" )
        robber_not_bound_template = heist_conf.get('robber_not_bound_template', "🤔 请先绑定账号。" )
        victim_not_found_template = heist_conf.get('victim_not_found_template', "💨 未找到目标 {victim_identifier}。" )
        cannot_rob_self_template = heist_conf.get('cannot_rob_self_template', "🤦‍♂️ 不能打劫自己。" )
        attempts_exceeded_template = heist_conf.get('attempts_exceeded_template', "🥵 次数用尽。" )
        defenses_exceeded_template = heist_conf.get('defenses_exceeded_template', "🛡️ 对方已有防备 (ID:{victim_id})。" )
        cooldown_template = heist_conf.get('cooldown_template', "⏳ 冷却中，剩余 {remaining_time} 秒。")
        # --- 缓存结束 ---

        match status:
            case "SUCCESS":
                reply = success_template.format(gain=details['gain'])
                # 打劫成功后顺便更新余额缓存（抢劫者+受害者），供排行榜使用
                robber_binding = await self.core.get_user_by_identity(robber_qq_id)
                victim_binding = await self.core.get_user_by_identity(victim_identifier)
                for b in (robber_binding, victim_binding):
                    if b:
                        data = await self.core.get_api_user_data(b['website_user_id'])
                        if data:
                            self._balance_cache[b['website_user_id']] = (b.get('qq_id', b.get('openid')), data.get('quota', 0))
            case "CRITICAL":
                reply = critical_template.format(gain=details['gain'])
                # 同上
                robber_binding = await self.core.get_user_by_identity(robber_qq_id)
                victim_binding = await self.core.get_user_by_identity(victim_identifier)
                for b in (robber_binding, victim_binding):
                    if b:
                        data = await self.core.get_api_user_data(b['website_user_id'])
                        if data:
                            self._balance_cache[b['website_user_id']] = (b.get('qq_id', b.get('openid')), data.get('quota', 0))
            case "FAILURE":
                reply = failure_template.format(penalty=details['penalty'])
            case "DISABLED":
                reply = disabled_template
            case "ROBBER_NOT_BOUND":
                reply = robber_not_bound_template
            case "VICTIM_NOT_FOUND":
                reply = victim_not_found_template.format(victim_identifier=f" {victim_identifier}")
            case "CANNOT_ROB_SELF":
                reply = cannot_rob_self_template
            case "ATTEMPTS_EXCEEDED":
                reply = attempts_exceeded_template
            case "DEFENSES_EXCEEDED":
                reply = defenses_exceeded_template.format(victim_id=details['victim_id'])
            case "COOLDOWN_ACTIVE":
                reply = cooldown_template.format(remaining_time=details['remaining_time'])
            case "API_ERROR":
                reply = self.t("heist.api_error")
            case _:
                reply = self.t("heist.unknown")
        
        yield event.plain_result(reply)

    @filter.command("榜单")
    async def handle_leaderboard(self, event: AstrMessageEvent):
        """展示群内余额榜与打劫榜（余额从用户操作缓存读取，无需查API）。"""
        lb_conf = self.config.get('leaderboard_settings', {})
        if not lb_conf.get('enabled', False):
            yield event.plain_result(self.t("leaderboard.disabled"))
            return
        top_n = max(1, int(lb_conf.get('top_n', 10)))
        ratio = self.config.get('binding_settings.quota_display_ratio', 500000)

        # 余额榜：直接从缓存读取并排序（用户每次签到/查余额/打劫时更新缓存）
        balance_lines = self._build_balance_board_from_cache(top_n, ratio)
        # 打劫榜：纯 SQL 聚合
        heist_lines = await self._build_heist_board(top_n, ratio)

        reply = self.t("leaderboard.header", top_n=top_n, balance=balance_lines, heist=heist_lines)
        yield event.plain_result(reply)

    @filter.command("消耗榜")
    async def handle_consumption_leaderboard(self, event: AstrMessageEvent):
        """(管理员) 展示全站用户近 N 小时 token 消耗排行榜（用户名 + 已绑定则附 QQ 号）。"""
        conf = self.config.get('consumption_leaderboard_settings', {})
        if not conf.get('enabled', False):
            yield event.plain_result(self.t("consumption.disabled"))
            return
        top_n = max(1, int(conf.get('top_n', 10)))
        hours = max(1, int(conf.get('window_hours', 24)))

        yield event.plain_result(self.t("consumption.fetching", hours=hours))

        stats = await self.core.get_user_token_consumption(hours=hours)
        if stats is None:
            yield event.plain_result(self.t("consumption.fetch_failed"))
            return
        if not stats:
            yield event.plain_result(self.t("consumption.no_data", hours=hours))
            return

        stats.sort(key=lambda x: x['tokens'], reverse=True)
        top = stats[:top_n]

        ratio = self.config.get('binding_settings.quota_display_ratio', 500000)
        ratio = ratio if ratio else 1
        show_quota = bool(conf.get('show_quota', False))
        show_qq = bool(conf.get('show_qq', True))

        # 缓存所有有消耗用户的绑定关系到 KV（单个 dict 键），避免每次查 DB
        # 加锁保护读-改-写，避免与绑定/解绑的缓存更新互相覆盖
        cache: dict = {}
        db_lookups = 0
        db_hits = 0
        if show_qq:
            try:
                async with self._kv_lock:
                    cache = await self.get_kv_data("binding_cache", {}) or {}
                    cache_updated = False
                    for s in stats:
                        user_id = str(s["user_id"])
                        if user_id not in cache:
                            db_lookups += 1
                            binding = await self.core.get_user_by_website_id(s["user_id"])
                            if binding:
                                db_hits += 1
                                cache[user_id] = binding['qq_id']
                                cache_updated = True
                    if cache_updated:
                        await self.put_kv_data("binding_cache", cache)
            except Exception as e:
                # 预填充失败不阻断出榜：下方展示层会对上榜用户逐条回退查库
                logger.warning(f"[消耗榜] 绑定缓存预填充失败（将逐条回退查询）: {e}")
            if self._is_debug():
                sample = ",".join(f"{s['user_id']}→{type(s['user_id']).__name__}" for s in top[:3])
                logger.info(
                    f"[消耗榜][DEBUG] show_qq={show_qq} 缓存大小={len(cache)} 窗口用户数={len(stats)} "
                    f"预填充查库={db_lookups}次 命中={db_hits}次 TOP3类型[{sample}]"
                )

        lines = []
        medals = ["🥇", "🥈", "🥉"]
        for idx, s in enumerate(top):
            rank = idx + 1
            prefix = medals[idx] if idx < 3 else f"{rank}."
            username = s.get("username") or str(s["user_id"])
            raw_cached = cache.get(str(s["user_id"])) if show_qq else None
            if self._is_debug():
                logger.info(f"[消耗榜][DEBUG] 行{rank} user={s['user_id']!r} 缓存原始值={raw_cached!r}")
            qq_id = raw_cached
            if show_qq and qq_id is None:
                # 展示层兜底：上榜用户缓存未命中时逐条回退查库，
                # 避免缓存被清空（如插件重载）或预填充失败导致整榜无 QQ 号
                try:
                    binding = await self.core.get_user_by_website_id(s["user_id"])
                    if binding:
                        qq_id = binding['qq_id']
                        if self._is_debug():
                            logger.info(f"[消耗榜][DEBUG] 兜底命中 user_id={s['user_id']} → QQ:{qq_id}")
                        try:
                            async with self._kv_lock:
                                fresh = await self.get_kv_data("binding_cache", {}) or {}
                                fresh[str(s["user_id"])] = qq_id
                                await self.put_kv_data("binding_cache", fresh)
                        except Exception as e:
                            logger.warning(f"[消耗榜] 回写绑定缓存失败（不影响本次展示）: {e}")
                    else:
                        if self._is_debug():
                            logger.info(f"[消耗榜][DEBUG] 兜底未命中 user_id={s['user_id']}（数据库无此绑定行，类型={type(s['user_id']).__name__}）")
                except Exception as e:
                    logger.warning(f"[消耗榜] 榜单用户 {s['user_id']} 绑定查询失败: {e}")
            show_bound = show_qq and qq_id is not None
            if self._is_debug():
                logger.info(f"[消耗榜][DEBUG] 行{rank} 最终 qq_id={qq_id!r} show_bound={show_bound}")
            qq = str(qq_id) if show_bound else ""
            if show_quota:
                display_quota = (s.get("quota", 0) or 0) / ratio
                if show_bound:
                    line = self.t("consumption.line_bound_quota", prefix=prefix, username=username,
                                  qq=qq, tokens=f"{s['tokens']:,}",
                                  quota=f"{display_quota:.6f}")
                else:
                    line = self.t("consumption.line_quota", prefix=prefix, username=username,
                                  tokens=f"{s['tokens']:,}", quota=f"{display_quota:.6f}")
            else:
                if show_bound:
                    line = self.t("consumption.line_bound", prefix=prefix, username=username,
                                  qq=qq, tokens=f"{s['tokens']:,}")
                else:
                    line = self.t("consumption.line", prefix=prefix, username=username,
                                  tokens=f"{s['tokens']:,}")
            lines.append(line)

        reply = self.t("consumption.header", top_n=top_n, hours=hours, lines="\n".join(lines))
        # 指纹日志：确认可见回复由本实例/本段代码渲染（排查重复加载的旧实例分流）
        if self._is_debug():
            logger.info(
                f"[消耗榜][DEBUG] 实例#{id(self) % 0xffff} 渲染首行={lines[0] if lines else '(空)'}"
            )
            logger.info(f"[消耗榜][DEBUG] 实例#{id(self) % 0xffff} 渲染全文>>>\n{reply}\n<<<全文结束")
        yield event.plain_result(reply)

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def handle_group_decrease(self, event: AstrMessageEvent):
        """监听群成员减少事件，执行解绑并发送通知。"""
        if not isinstance(event, AiocqhttpMessageEvent):
            return

        raw = event.message_obj.raw_message
        if not (
            isinstance(raw, dict)
            and raw.get("post_type") == "notice"
            and raw.get("notice_type") == "group_decrease"
        ):
            return
        
        group_id = raw.get("group_id")
        user_id = raw.get("user_id")

        leave_conf = self.config.get('group_leave_settings', {})
        monitored_groups_str = leave_conf.get('group_monitoring_list', [])
        monitored_groups = [int(g) for g in monitored_groups_str if str(g).isdigit()]

        if group_id not in monitored_groups:
            return

        binding = await self.core.get_user_by_qq(user_id)
        if not binding:
            logger.info(f"用户 {user_id} 退出了受监控的群 {group_id}，但其未被绑定，无需净化。" )
            return

        website_user_id = binding['website_user_id']
        success, _ = await self.core.purge_user_binding(website_user_id)

        if success:
            await self._update_binding_cache(website_user_id, None)
            logger.info(f"用户 {user_id} (网站ID: {website_user_id}) 的退群净化仪式成功完成。" )
            
            try:
                sub_type = raw.get("sub_type")
                operator_id = raw.get("operator_id")
                bot = event.bot

                user_info = await bot.get_stranger_info(user_id=user_id, no_cache=True)
                user_nickname = user_info.get("nickname", str(user_id))

                announcement = ""
                if sub_type == "leave":
                    announcement = self.t("leave.announcement", nickname=user_nickname, qq=user_id)
                elif sub_type == "kick":
                    operator_info = await bot.get_group_member_info(group_id=group_id, user_id=operator_id, no_cache=True)
                    operator_nickname = operator_info.get("card") or operator_info.get("nickname", str(operator_id))
                    announcement = self.t("kick.announcement", nickname=user_nickname, qq=user_id, op=operator_nickname)
                
                if announcement:
                    await bot.send_group_msg(group_id=group_id, message=announcement)

            except Exception as e:
                logger.error(f"在为用户 {user_id} 发送退群净化通告时发生错误: {e}", exc_info=True)
        
        event.stop_event()

    # --- 排行榜辅助方法 ---

    def _build_balance_board_from_cache(self, top_n: int, ratio: int) -> str:
        """构建余额排行榜：直接读取内存缓存，无需查 API。

        缓存由用户每次操作（签到/查余额/打劫）时顺手更新。
        """
        if not self._balance_cache:
            return self.t("leaderboard.no_balance_cache")
        results = sorted(
            self._balance_cache.values(), key=lambda x: x[1], reverse=True
        )[:top_n]
        if not results:
            return self.t("leaderboard.no_balance")
        lines = []
        medals = ["🥇", "🥈", "🥉"]
        for idx, (qq_id, quota) in enumerate(results):
            rank = idx + 1
            prefix = medals[idx] if idx < 3 else f"{rank}."
            display = quota / ratio
            lines.append(f"{prefix} QQ:{qq_id} → {display:.6f}")
        return "\n".join(lines)

    async def _build_heist_board(self, top_n: int, ratio: int) -> str:
        """构建打劫排行榜：聚合打劫日志，按净收益排序（成功为正、失败为负）。"""
        query = """
            SELECT robber_qq_id,
                   COUNT(*) AS attempts,
                   SUM(CASE WHEN outcome IN ('SUCCESS', 'CRITICAL') THEN 1 ELSE 0 END) AS wins,
                   SUM(amount) AS net
            FROM daily_heist_log
            GROUP BY robber_qq_id
            ORDER BY net DESC
            LIMIT %s
        """
        rows = await self.core.execute_query(query, (top_n,), fetch='all')
        if not rows:
            return self.t("leaderboard.no_heist")

        lines = []
        medals = ["🥇", "🥈", "🥉"]
        for idx, row in enumerate(rows):
            rank = idx + 1
            prefix = medals[idx] if idx < 3 else f"{rank}."
            net_display = (row['net'] or 0) / ratio
            lines.append(
                self.t("leaderboard.heist_line", prefix=prefix, qq=row['robber_qq_id'],
                       attempts=row['attempts'], wins=row['wins'], net=f"{net_display:.6f}")
            )
        return "\n".join(lines)

    # --- 绑定功能辅助方法 ---

    async def _check_self_binding(self, user_qq_id: int) -> Optional[str]:
        """检查用户QQ是否已绑定。"""
        if binding := await self.core.get_user_by_qq(user_qq_id):
            return self.t("bind.already_bound", site_id=binding['website_user_id'])
        return None

    async def _check_qq_level(self, event: AstrMessageEvent, user_qq_id: int) -> Optional[str]:
        binding_conf = self.config.get('binding_settings', {})
        min_level = binding_conf.get('min_qq_level', 16)
        try:
            stranger_info = await event.bot.get_stranger_info(user_id=user_qq_id, no_cache=True)

            raw_level = stranger_info.get('qqLevel') 

            if raw_level is not None:
                user_qq_level = int(raw_level)
                if user_qq_level < min_level:
                    return self.t("bind.qq_level_low", level=user_qq_level, min_level=min_level)
            else:
                logger.warning(f"无法从API获取用户 {user_qq_id} 的QQ等级，将跳过此项检查。" )
        except Exception as e:
            logger.warning(f"获取QQ等级失败，跳过检查: {e}", exc_info=True)
        return None

    async def _check_api_user_exists(self, website_user_id: int) -> Optional[str]:
        """检查网站用户ID是否存在。"""
        if not await self.core.get_api_user_data(website_user_id):
            return self.t("bind.api_user_not_found", site_id=website_user_id)
        return None

    async def _check_website_id_blacklist(self, website_user_id: int) -> Optional[str]:
        """检查网站ID是否在禁止绑定黑名单中（仅针对新增绑定，已绑定不受影响）。"""
        binding_conf = self.config.get('binding_settings', {})
        blacklist = binding_conf.get('forbidden_website_ids', [])
        forbidden_ids = set(int(i) for i in blacklist if str(i).lstrip('-').isdigit())
        if website_user_id in forbidden_ids:
            return self.t("bind.website_blacklisted", site_id=website_user_id)
        return None

    async def _check_user_blacklist(self, user_qq_id: int) -> Optional[str]:
        """检查用户QQ是否在禁止绑定黑名单中（仅针对新增绑定，已绑定不受影响）。"""
        binding_conf = self.config.get('binding_settings', {})
        blacklist = binding_conf.get('forbidden_user_ids', [])
        forbidden_ids = set(int(i) for i in blacklist if str(i).lstrip('-').isdigit())
        if user_qq_id in forbidden_ids:
            return self.t("bind.user_blacklisted", qq=user_qq_id)
        return None

    async def _check_id_uniqueness(self, website_user_id: int) -> Optional[str]:
        """检查网站用户ID是否已被他人绑定。"""
        if await self.core.get_user_by_website_id(website_user_id):
            return self.t("bind.id_taken", site_id=website_user_id)
        return None

    async def _perform_binding_ritual(self, user_qq_id: int, website_user_id: int) -> Tuple[bool, str]:
        """
        执行最终的绑定操作，包含数据库写入和API更新，失败时回滚。
        """
        try:
            await self.core.insert_binding(user_qq_id, website_user_id)
            
            api_user_data = await self.core.get_api_user_data(website_user_id)
            binding_conf = self.config.get('binding_settings', {})
            target_group = binding_conf.get('binding_group', 'default')
            
            if api_user_data:
                if api_user_data.get('group') == target_group:
                    # 【修复】用户已在目标组中，跳过无意义的 PUT，避免重绑时 no-op 更新被拒
                    logger.info(f"网站用户 {website_user_id} 已在目标组 {target_group} 中，跳过用户组更新。")
                else:
                    # 【修复】只发送后端允许修改的字段，避免 Invalid parameters
                    update_payload = {
                        "id": website_user_id,
                        "username": api_user_data.get("username"),
                        "display_name": api_user_data.get("display_name"),
                        "role": api_user_data.get("role"),
                        "status": api_user_data.get("status"),
                        "group": target_group
                    }
                    update_success = await self.core.update_api_user(update_payload)
                    if not update_success:
                        raise Exception("API group update failed.")
            else:
                raise Exception("API user data not found during binding ritual.")

            return True, self.t("bind.success", site_id=website_user_id, group=target_group)
        
        except Exception as e:
            logger.error(f"绑定仪式中发生错误: {e}", exc_info=True)
            await self.core.delete_binding(qq_id=user_qq_id)
            return False, self.t("bind.failed")

    async def _perform_openid_binding(self, event, openid: str, website_user_id: int) -> str:
        """执行 OpenID 绑定（优先前检查冲突，写入 newapi_openid_bindings 表，晋升用户组）。"""
        # 检查 OpenID 是否已被绑定
        existing = await self.core.get_user_by_openid(openid)
        if existing:
            return self.t("bind.already_bound", site_id=existing['website_user_id'])

        # 检查网站 ID 是否已被 OpenID 绑定
        already = await self.core.get_openid_by_website_id(website_user_id)
        if already:
            return self.t("bind.id_taken", site_id=website_user_id)

        # 检查网站用户是否存在
        if not await self.core.get_api_user_data(website_user_id):
            return self.t("bind.api_user_not_found", site_id=website_user_id)

        # 网站黑名单
        binding_conf = self.config.get('binding_settings', {})
        blacklist = binding_conf.get('forbidden_website_ids', [])
        forbidden_ids = set(int(i) for i in blacklist if str(i).lstrip('-').isdigit())
        if website_user_id in forbidden_ids:
            return self.t("bind.website_blacklisted", site_id=website_user_id)

        try:
            await self.core.insert_openid_binding(openid, website_user_id)
            # 晋升用户组
            target_group = binding_conf.get('binding_group', 'default')
            api_user_data = await self.core.get_api_user_data(website_user_id)
            if api_user_data and api_user_data.get('group') != target_group:
                update_payload = {
                    "id": website_user_id,
                    "username": api_user_data.get("username"),
                    "display_name": api_user_data.get("display_name"),
                    "role": api_user_data.get("role"),
                    "status": api_user_data.get("status"),
                    "group": target_group
                }
                update_success = await self.core.update_api_user(update_payload)
                if not update_success:
                    raise Exception("API group update failed.")

            return self.t("bind.openid_success", openid=openid, site_id=website_user_id, group=target_group)
        except Exception as e:
            logger.error(f"OpenID 绑定失败: {e}", exc_info=True)
            await self.core.delete_openid_binding(openid=openid)
            return self.t("bind.failed")

    async def _send_success_pm(self, event: AstrMessageEvent, user_qq_id: int, website_user_id: int):
        """如果配置允许，发送绑定成功私信。"""
        pm_conf = self.config.get('optional_pm_settings', {})
        if not pm_conf.get('enable_bind_success_pm'):
            return
        
        try:
            template = pm_conf.get('bind_success_pm_template', "绑定成功！")
            group = self.config.get('binding_settings.binding_group', 'default')

            user_nickname = str(user_qq_id)
            try:
                stranger_info = await event.bot.get_stranger_info(user_id=user_qq_id, no_cache=True)
                user_nickname = stranger_info.get("nickname", str(user_qq_id))
            except Exception as e:
                logger.warning(f"为私信模板获取QQ昵称失败: {e}", exc_info=True)

            site_username = self.t("common.unknown")
            api_user_data = await self.core.get_api_user_data(website_user_id)
            if api_user_data:
                site_username = api_user_data.get("username", self.t("common.unknown"))

            content = template.format(
                id=website_user_id,
                group=group,
                user_qq=user_qq_id,
                user_nickname=user_nickname,
                site_username=site_username
            )
            
            await event.bot.send_private_msg(user_id=user_qq_id, message=content)
            logger.info(f"成功发送绑定成功私信至 {user_qq_id}。" )
        except Exception as e:
            logger.error(f"发送绑定成功私信失败: {e}", exc_info=True)