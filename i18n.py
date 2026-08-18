# -*- coding: utf-8 -*-
"""运行时消息国际化（中文 / 英文）。

配置项 i18n_settings.language 控制回复语言；缺省回退中文。
WebUI 文案的国际化请见 .astrbot-plugin/i18n/*.json。
"""

_TRANSLATIONS = {
    "zh": {
        # 通用
        "common.at_or_id_required": "请 @ 对方，或输入网站ID/QQ号。",
        "common.amount_required": "请提供要调整的额度。",
        "common.unknown": "未知",
        # 未绑定
        "not_bound": "您尚未绑定网站ID，无法进行此操作。\n请使用 `/绑定 [您的网站ID]` 指令。",
        # pingapi
        "ping.connected": "✅ 已连接",
        "ping.disconnected": "❌ 连接失败",
        "ping.running": "🎉 Pong! NewAPI 插件套件 V{version} 正在运行！",
        "ping.db_engine": "数据库引擎",
        "ping.db_status": "数据库状态",
        "ping.api_status": "New API 状态",
        # 查询余额（本人）
        "query_balance.failed": "查询失败，无法从网站获取您的余额信息。请稍后再试或联系管理员。",
        "query_balance.success": "查询成功！\n--------------------\n您绑定的网站ID: {site_id}\n当前剩余额度: {quota}",
        # 查余额（管理员）
        "query_other.not_found": "❌ 查询失败：未在绑定记录中找到与 {id} 相关的任何信息。",
        "query_other.failed": "查询失败，无法从网站获取该用户的余额信息。请稍后再试或联系管理员。",
        "query_other.label_website": "网站ID",
        "query_other.label_qq": "QQ号",
        "query_other.success": "✅ 查询成功！\n--------------------\n输入类型: {label}\n{label}: {id}\n绑定的网站ID: {site_id}\n当前剩余额度: {quota}",
        # 绑定
        "bind.validating": "验证通过，执行绑定...",
        "bind.already_bound": "您好，您的QQ已经与网站ID {site_id} 签订了契约，无需重复绑定。",
        "bind.qq_level_low": "抱歉，您的QQ等级({level})未达到所要求的 {min_level} 级，暂时无法绑定。",
        "bind.api_user_not_found": "审核失败：网站中不存在ID为 {site_id} 的用户，请检查您的ID。",
        "bind.website_blacklisted": "审核失败：网站ID {site_id} 已被管理员列入禁止绑定名单，无法绑定。",
        "bind.user_blacklisted": "审核失败：您的QQ {qq} 已被管理员列入禁止绑定名单，无法绑定。",
        "bind.id_taken": "审核失败：ID {site_id} 已被另一位用户绑定，无法操作。",
        "bind.success": "恭喜您！绑定成功！\n您的QQ现已与网站ID {site_id} 绑定。\n已自动为您晋升至【{group}】分组。",
        "bind.failed": "绑定过程中发生未知错误，操作已自动撤销，请联系管理员。",
        # 签到
        "check_in.disabled": "抱歉，每日签到功能当前未开启。",
        "check_in.already": "您今天已经签过到了，请明天再来吧！",
        "check_in.api_user_not_found": "签到失败：无法获取您的网站用户信息，请联系管理员。",
        "check_in.api_update_failed": "签到失败：向网站服务器更新额度时发生错误，请稍后再试。",
        "check_in.unknown": "签到时发生未知错误，请联系管理员。",
        # 解绑
        "unbind.success": "✅ 操作成功！\n已将网站ID: {site_id}\n从QQ用户: {qq} 的契约中解放。",
        "unbind.not_found": "❌ 操作无效：未找到网站ID {site_id} 的绑定记录。",
        "unbind.failed": "❌ 操作失败：在为网站ID {site_id} 执行净化时发生未知错误，请检查后台日志。",
        # 查询（管理员）
        "lookup.website": "✅ 查询成功！输入的是【网站ID】\n--------------------\n网站ID: {site_id}\n已绑定至QQ: {qq}\n绑定时间: {time}",
        "lookup.qq": "✅ 查询成功！输入的是【QQ号】\n--------------------\nQQ号: {qq}\n已绑定至网站ID: {site_id}\n绑定时间: {time}",
        "lookup.not_found": "❌ 查询失败：未在绑定记录中找到与 {id} 相关的任何信息。",
        # 调整余额
        "adjust.success_inc": "✅ 操作成功！\n--------------------\n目标用户ID: {site_id}\n已为其增加显示额度: {amount}\n该用户当前总显示额度为: {total}",
        "adjust.success_dec": "✅ 操作成功！\n--------------------\n目标用户ID: {site_id}\n已为其减少显示额度: {amount}\n该用户当前总显示额度为: {total}",
        "adjust.not_found": "❌ 操作失败：未在绑定记录中找到与 {id} 相关的用户。",
        "adjust.fetch_failed": "❌ 操作失败：无法从网站获取ID为 {site_id} 的用户信息。",
        "adjust.update_failed": "❌ 操作失败：向网站更新ID为 {site_id} 的余额时发生错误。",
        # 打劫
        "heist.no_target": "🤔 打劫谁呢？请 @ 你要打劫的目标。",
        "heist.too_many": "🏃‍♂️ 不要太贪心，一次只能打劫一个目标！",
        "heist.api_error": "- 发生了一个API错误，请联系管理员。",
        "heist.unknown": "❓ 发生未知错误。",
        # 榜单
        "leaderboard.disabled": "排行榜功能未开启。",
        "leaderboard.header": "🏆 群余额榜 TOP {top_n}\n{balance}\n\n🥷 打劫榜 TOP {top_n}\n{heist}",
        "leaderboard.no_balance_cache": "暂无缓存余额数据（请先执行签到或查余额）。",
        "leaderboard.no_balance": "暂无缓存余额数据。",
        "leaderboard.no_heist": "暂无打劫记录。",
        "leaderboard.heist_line": "{prefix} QQ:{qq} → 出手{attempts}次 胜{wins}次 净赚{net}",
        # 退群公告
        "leave.announcement": "成员【{nickname}】({qq}) 已主动退出群聊。\n其绑定的网站数据已自动解绑，用户组已重置。",
        "kick.announcement": "成员【{nickname}】({qq}) 已被管理员【{op}】移出群聊。\n其绑定的网站数据已自动解绑，用户组已重置。",
    },
    "en": {
        "common.at_or_id_required": "Please @ a user or enter a website ID / QQ number.",
        "common.amount_required": "Please provide the quota amount.",
        "common.unknown": "Unknown",
        "not_bound": "You haven't bound a website ID yet.\nPlease use `/绑定 [your website ID]` to bind first.",
        "ping.connected": "✅ Connected",
        "ping.disconnected": "❌ Failed",
        "ping.running": "🎉 Pong! NewAPI plugin suite V{version} is running!",
        "ping.db_engine": "Database Engine",
        "ping.db_status": "Database Status",
        "ping.api_status": "New API Status",
        "query_balance.failed": "Query failed: unable to fetch your balance from the website. Please try again later or contact the admin.",
        "query_balance.success": "Query successful!\n--------------------\nYour bound website ID: {site_id}\nCurrent remaining quota: {quota}",
        "query_other.not_found": "❌ Query failed: no binding record found for {id}.",
        "query_other.failed": "Query failed: unable to fetch this user's balance. Please try again later or contact the admin.",
        "query_other.label_website": "Website ID",
        "query_other.label_qq": "QQ",
        "query_other.success": "✅ Query successful!\n--------------------\nInput type: {label}\n{label}: {id}\nBound website ID: {site_id}\nCurrent remaining quota: {quota}",
        "bind.validating": "Validation passed, binding...",
        "bind.already_bound": "Your QQ is already bound to website ID {site_id}, no need to bind again.",
        "bind.qq_level_low": "Sorry, your QQ level ({level}) is below the required {min_level}; unable to bind.",
        "bind.api_user_not_found": "Check failed: no user with ID {site_id} exists on the website. Please check your ID.",
        "bind.website_blacklisted": "Check failed: website ID {site_id} has been blacklisted; unable to bind.",
        "bind.user_blacklisted": "Check failed: your QQ {qq} has been blacklisted; unable to bind.",
        "bind.id_taken": "Check failed: ID {site_id} is already bound to another user.",
        "bind.success": "Congratulations! Binding successful!\nYour QQ is now bound to website ID {site_id}.\nYou've been promoted to group 【{group}】.",
        "bind.failed": "An unknown error occurred during binding; the operation was rolled back. Please contact the admin.",
        "check_in.disabled": "Sorry, daily check-in is currently disabled.",
        "check_in.already": "You've already checked in today, come back tomorrow!",
        "check_in.api_user_not_found": "Check-in failed: unable to fetch your website user info. Please contact the admin.",
        "check_in.api_update_failed": "Check-in failed: error updating quota on the server. Please try again later.",
        "check_in.unknown": "An unknown error occurred during check-in. Please contact the admin.",
        "unbind.success": "✅ Success!\nWebsite ID {site_id} has been unbound from QQ user {qq}.",
        "unbind.not_found": "❌ Invalid: no binding record found for website ID {site_id}.",
        "unbind.failed": "❌ Failed: an unknown error occurred while purging website ID {site_id}. Please check the logs.",
        "lookup.website": "✅ Found! Input was a [Website ID]\n--------------------\nWebsite ID: {site_id}\nBound to QQ: {qq}\nBound at: {time}",
        "lookup.qq": "✅ Found! Input was a [QQ]\n--------------------\nQQ: {qq}\nBound to website ID: {site_id}\nBound at: {time}",
        "lookup.not_found": "❌ Query failed: no binding record found for {id}.",
        "adjust.success_inc": "✅ Success!\n--------------------\nTarget user ID: {site_id}\nIncreased display quota by: {amount}\nCurrent total display quota: {total}",
        "adjust.success_dec": "✅ Success!\n--------------------\nTarget user ID: {site_id}\nDecreased display quota by: {amount}\nCurrent total display quota: {total}",
        "adjust.not_found": "❌ Failed: no user found for {id}.",
        "adjust.fetch_failed": "❌ Failed: unable to fetch info for user {site_id}.",
        "adjust.update_failed": "❌ Failed: error updating balance for user {site_id}.",
        "heist.no_target": "🤔 Who to rob? Please @ your target.",
        "heist.too_many": "🏃‍♂️ Don't be greedy, only one target at a time!",
        "heist.api_error": "- An API error occurred, please contact the admin.",
        "heist.unknown": "❓ An unknown error occurred.",
        "leaderboard.disabled": "Leaderboard is disabled.",
        "leaderboard.header": "🏆 Group Balance TOP {top_n}\n{balance}\n\n🥷 Heist TOP {top_n}\n{heist}",
        "leaderboard.no_balance_cache": "No cached balance data yet (check in or query balance first).",
        "leaderboard.no_balance": "No cached balance data.",
        "leaderboard.no_heist": "No heist records yet.",
        "leaderboard.heist_line": "{prefix} QQ:{qq} → {attempts} attempts, {wins} wins, net {net}",
        "leave.announcement": "Member 【{nickname}】({qq}) left the group.\nTheir binding has been removed and user group reset.",
        "kick.announcement": "Member 【{nickname}】({qq}) was removed by admin 【{op}】.\nTheir binding has been removed and user group reset.",
    },
}


def translate(lang: str, key: str, **kwargs):
    """按语言返回翻译后的文案；缺 key 或语言时回退到中文，再回退到 key 本身。"""
    lang_key = "en" if str(lang).lower().startswith("en") else "zh"
    msg = _TRANSLATIONS.get(lang_key, _TRANSLATIONS["zh"]).get(key)
    if msg is None:
        msg = _TRANSLATIONS["zh"].get(key, key)
    if kwargs:
        try:
            return msg.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            return msg
    return msg
