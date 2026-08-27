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
        "common.unexpected_error": "❌ 处理命令时发生未预期错误：{err}",
        # 未绑定
        "not_bound": "您尚未绑定网站ID，无法进行此操作。\n请发送「绑定 [您的网站ID]」指令完成绑定。",
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
        "bind.id_required": "请提供要绑定的网站ID。\n用法：绑定 [你的网站ID]（纯数字），例如：绑定 1234",
        "bind.id_invalid": "❌ 网站ID应为纯数字，你输入的「{input}」无法识别。\n请检查后重试，例如：绑定 1234",
        "bind.validating": "验证通过，执行绑定...",
        "bind.already_bound": "您好，您的QQ已经与网站ID {site_id} 签订了契约，无需重复绑定。",
        "bind.qq_level_low": "抱歉，您的QQ等级({level})未达到所要求的 {min_level} 级，暂时无法绑定。",
        "bind.api_user_not_found": "审核失败：网站中不存在ID为 {site_id} 的用户，请检查您的ID。",
        "bind.website_blacklisted": "审核失败：网站ID {site_id} 已被管理员列入禁止绑定名单，无法绑定。",
        "bind.user_blacklisted": "审核失败：您的QQ {qq} 已被管理员列入禁止绑定名单，无法绑定。",
        "bind.id_taken": "审核失败：ID {site_id} 已被另一位用户绑定，无法操作。",
        "bind.success": "恭喜您！绑定成功！\n您的QQ现已与网站ID {site_id} 绑定。\n已自动为您晋升至【{group}】分组。",
        "bind.openid_success": "恭喜您！绑定成功！\n您的OpenID {openid} 现已与网站ID {site_id} 绑定。\n已自动为您晋升至【{group}】分组。",
        "bind.openid_success_no_group": "恭喜您！绑定成功！\n您的OpenID {openid} 现已与网站ID {site_id} 绑定。\nℹ️ 已开启「仅野机绑定改分组」：官机绑定不改变用户组。",
        "bind.openid_need_qq": "❌ 绑定失败：当前已开启「官机绑定需先绑QQ」，网站ID {site_id} 还没有 QQ 号（野机）绑定。\n请先在野机机器人处完成「绑定 {site_id}」后再来。",
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
        "lookup.openid_extra": "\n🔗 另有 OpenID 绑定（官机）：{openid}",
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
        # 消耗榜
        "consumption.fetching": "🔄 正在拉取全站近 {hours} 小时消耗日志，请稍候…",
        "consumption.disabled": "消耗排行榜功能未开启。",
        "consumption.fetch_failed": "❌ 拉取全站消耗日志失败，请稍后再试或联系管理员。",
        "consumption.no_data": "近 {hours} 小时暂无消耗记录。",
        "consumption.header": "📊 全站消耗榜 TOP {top_n}（近 {hours} 小时）\n{lines}",
        "consumption.line": "{prefix} {username} → {tokens} tokens",
        "consumption.line_bound": "{prefix} {username} [QQ:{qq}] → {tokens} tokens",
        "consumption.line_quota": "{prefix} {username} → {tokens} tokens · 消耗 {quota} 额度",
        "consumption.line_bound_quota": "{prefix} {username} [QQ:{qq}] → {tokens} tokens · 消耗 {quota} 额度",
        # 退群公告
        "leave.announcement": "成员【{nickname}】({qq}) 已主动退出群聊。\n其绑定的网站数据已自动解绑，用户组已重置。",
        "kick.announcement": "成员【{nickname}】({qq}) 已被管理员【{op}】移出群聊。\n其绑定的网站数据已自动解绑，用户组已重置。",
        # 数据库导入导出
        "db_transfer.usage": "用法：发送「new-tx 导出」把当前数据库内容导出到迁移文件，或「new-tx 导入」把迁移文件导入当前数据库。\n⚠️ 导入为覆盖操作：当前库中绑定 / 签到状态 / 打劫日志表会先清空再写入文件内容。",
        "db_transfer.act_export": "导出",
        "db_transfer.act_import": "导入",
        "db_transfer.working": "🔄 正在{action}数据库，请稍候…",
        "db_transfer.detail_line": "{label}：{count} 条",
        "db_transfer.export_done": "✅ 导出完成，已写入迁移文件 transfer.db：\n{detail}\n共 {total} 条记录。",
        "db_transfer.import_done": "✅ 导入完成，当前数据库已更新：\n{detail}\n共 {total} 条记录。",
        "db_transfer.no_file": "❌ 未找到迁移文件（transfer.db），请先执行「new-tx 导出」。",
        "db_transfer.empty_file": "❌ 迁移文件（transfer.db）中没有任何数据，已拒绝导入以保护当前数据库。\n如确认要导入，请先检查该文件是否正确。",
        "db_transfer.failed": "❌ 数据库{action}失败：{err}\n请查看后台日志。",
        "db_transfer.label_bindings": "QQ 绑定",
        "db_transfer.label_openid_bindings": "OpenID 绑定",
        "db_transfer.label_check_in_state": "签到状态",
        "db_transfer.label_heist_log": "打劫日志",
        # 红包
        "rp.disabled": "🧧 红包功能当前未开启。",
        "rp.count_required": "请提供红包份数。\n用法：发红包 [份数] [总额度]，例如：发红包 10 50",
        "rp.count_invalid": "❌ 红包份数应为正整数，你输入的「{input}」无法识别。\n例如：发红包 10 50",
        "rp.count_too_large": "❌ 单个红包最多 {max} 份。",
        "rp.amount_required": "请提供红包总额度。\n用法：发红包 [份数] [总额度]，例如：发红包 10 50",
        "rp.amount_invalid": "❌ 总额度应为正数，你输入的「{input}」无法识别。\n例如：发红包 10 50",
        "rp.amount_too_large": "❌ 单个红包总额度不能超过 {max}。",
        "rp.too_small": "❌ 总额度太低，无法拆成 {count} 份，请提高额度或减少份数。",
        "rp.created": "🧧 {creator} 发出了一个拼手气红包！\n💰 总额度 {amount} · 共 {count} 份\n👉 快发送「抢红包 {pid}」来抢！\n⏰ {hours} 小时内有效，先到先得～",
        "rp.official_only_hint": "\n🤖 本红包仅可通过官方机器人抢夺，在其他机器人处发送无效～",
        "rp.pid_required": "请提供红包编号（发红包时会公布），例如：抢红包 3",
        "rp.pid_invalid": "❌ 红包编号应为数字，你输入的「{input}」无法识别。\n例如：抢红包 3",
        "rp.not_found": "❌ 没有找到红包 #{pid}，检查一下编号吧。",
        "rp.expired": "⏰ 手慢了，这个红包已过期。",
        "rp.empty": "😭 手慢了，红包已被抢完！",
        "rp.already": "🙃 你已经抢过这个红包啦，别贪心～",
        "rp.api_error": "- 红包入账失败（本次未消耗份额），请稍后再试或联系管理员。",
        "rp.success": "🎉 恭喜！抢到 {amount} 额度！\n💰 已直接存入你的余额\n📦 本红包剩余 {remain}/{total} 份",
        # 个人红包（普通用户，扣自己余额）
        "rp.user.disabled": "🧧 个人红包功能当前未开启。",
        "rp.user.count_required": "请提供红包份数。\n用法：个人红包 [份数] [总额度]，例如：个人红包 10 50",
        "rp.user.count_invalid": "❌ 红包份数应为正整数，你输入的「{input}」无法识别。\n例如：个人红包 10 50",
        "rp.user.count_too_large": "❌ 单个红包最多 {max} 份。",
        "rp.user.amount_required": "请提供红包总额度。\n用法：个人红包 [份数] [总额度]，例如：个人红包 10 50",
        "rp.user.amount_invalid": "❌ 总额度应为正数，你输入的「{input}」无法识别。\n例如：个人红包 10 50",
        "rp.user.not_verified": "🔒 首次发个人红包需要先验证身份。\n请发送：验证令牌 你的网站访问令牌\n（在 New API 网站「个人设置 → 生成系统访问令牌」获取）\n⚠️ 令牌等同密码：建议私聊机器人验证；若已在群内发送，验证后请尽快到网站重置令牌。",
        "rp.user.balance_unavailable": "❌ 暂时无法获取你的账户余额，请稍后再试。",
        "rp.user.limit_reached": "🧧 今日个人红包次数已用完～\n💰 当前余额 {balance}（每满 {per} 可发 1 次，每日上限 {max} 次）\n📅 今日已发 {used} 次，明天再来吧！",
        "rp.user.exceeds_balance": "❌ 红包总额度不能超过你的余额（当前 {balance}）。",
        "rp.user.deduct_failed": "❌ 扣款失败，红包未发出。请稍后再试或联系管理员。",
        "rp.user.create_failed": "❌ 红包创建失败，已为你退还 {amount} 额度。请稍后再试；若额度未到账请联系管理员。",
        "rp.user.created": "🧧 {creator} 用自己的额度发出了拼手气红包！\n💰 总额度 {amount} · 共 {count} 份（已从余额扣除）\n📦 发送者余额剩余 {balance}\n👉 快发送「抢红包 {pid}」来抢！\n⏰ {hours} 小时内有效 · 发送者今日还可发 {left} 次",
        # 个人红包身份验证
        "rp.verify.token_required": "用法：验证令牌 [你的网站访问令牌]\n在 New API 网站「个人设置 → 生成系统访问令牌」获取。\n⚠️ 令牌等同密码：建议私聊机器人验证；若已在群内发送，验证后请尽快到网站重置令牌。",
        "rp.verify.success": "✅ 身份验证成功！令牌有效且与网站ID {site_id} 对应。\n之后即可直接使用「个人红包 [份数] [总额度]」，无需重复验证。",
        "rp.verify.failed": "❌ 验证失败：访问令牌无效，或与你绑定的网站ID不匹配。\n请确认令牌来自你绑定的账号后重新发送。",
    },
    "en": {
        "common.at_or_id_required": "Please @ a user or enter a website ID / QQ number.",
        "common.amount_required": "Please provide the quota amount.",
        "common.unknown": "Unknown",
        "common.unexpected_error": "❌ An unexpected error occurred while processing the command: {err}",
        "not_bound": "You haven't bound a website ID yet.\nPlease send the command \"绑定 [your website ID]\" to bind first.",
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
        "bind.id_required": "Please provide your website ID.\nUsage: 绑定 [your website ID] (digits only), e.g. 绑定 1234",
        "bind.id_invalid": "❌ The website ID must be numeric, but \"{input}\" cannot be recognized.\nPlease check and retry, e.g. 绑定 1234",
        "bind.validating": "Validation passed, binding...",
        "bind.already_bound": "Your QQ is already bound to website ID {site_id}, no need to bind again.",
        "bind.qq_level_low": "Sorry, your QQ level ({level}) is below the required {min_level}; unable to bind.",
        "bind.api_user_not_found": "Check failed: no user with ID {site_id} exists on the website. Please check your ID.",
        "bind.website_blacklisted": "Check failed: website ID {site_id} has been blacklisted; unable to bind.",
        "bind.user_blacklisted": "Check failed: your QQ {qq} has been blacklisted; unable to bind.",
        "bind.id_taken": "Check failed: ID {site_id} is already bound to another user.",
        "bind.success": "Congratulations! Binding successful!\nYour QQ is now bound to website ID {site_id}.\nYou've been promoted to group 【{group}】.",
        "bind.openid_success": "Congratulations! Binding successful!\nYour OpenID {openid} is now bound to website ID {site_id}.\nYou've been promoted to group 【{group}】.",
        "bind.openid_success_no_group": "Congratulations! Binding successful!\nYour OpenID {openid} is now bound to website ID {site_id}.\nℹ️ \"Wild-bind-only group change\" is enabled: official (OpenID) binding does not change the user group.",
        "bind.openid_need_qq": "❌ Binding failed: \"official binding requires an existing QQ binding\" is enabled, and website ID {site_id} has no QQ (wild bot) binding yet.\nPlease run 绑定 {site_id} via the wild bot first.",
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
        "lookup.openid_extra": "\n🔗 Also bound via OpenID (official bot): {openid}",
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
        "consumption.fetching": "🔄 Fetching site-wide consumption logs for the last {hours} hours, please wait…",
        "consumption.disabled": "Consumption leaderboard is disabled.",
        "consumption.fetch_failed": "❌ Failed to fetch consumption logs. Please try again later or contact the admin.",
        "consumption.no_data": "No consumption records in the last {hours} hours.",
        "consumption.header": "📊 Site-wide Consumption TOP {top_n} (last {hours}h)\n{lines}",
        "consumption.line": "{prefix} {username} → {tokens} tokens",
        "consumption.line_bound": "{prefix} {username} [QQ:{qq}] → {tokens} tokens",
        "consumption.line_quota": "{prefix} {username} → {tokens} tokens · {quota} quota",
        "consumption.line_bound_quota": "{prefix} {username} [QQ:{qq}] → {tokens} tokens · {quota} quota",
        "leave.announcement": "Member 【{nickname}】({qq}) left the group.\nTheir binding has been removed and user group reset.",
        "kick.announcement": "Member 【{nickname}】({qq}) was removed by admin 【{op}】.\nTheir binding has been removed and user group reset.",
        # Database import/export
        "db_transfer.usage": "Usage: send \"new-tx 导出\" to export the current database into the transfer file, or \"new-tx 导入\" to import the transfer file into the current database.\n⚠️ Import is destructive: bindings / check-in states / heist logs in the current database will be cleared and replaced by the file contents.",
        "db_transfer.act_export": "export",
        "db_transfer.act_import": "import",
        "db_transfer.working": "🔄 Database {action} in progress, please wait…",
        "db_transfer.detail_line": "{label}: {count}",
        "db_transfer.export_done": "✅ Export finished, written to transfer file transfer.db:\n{detail}\nTotal {total} records.",
        "db_transfer.import_done": "✅ Import finished, current database updated:\n{detail}\nTotal {total} records.",
        "db_transfer.no_file": "❌ Transfer file (transfer.db) not found. Please run \"new-tx 导出\" first.",
        "db_transfer.empty_file": "❌ The transfer file (transfer.db) contains no data; import was refused to protect the current database.",
        "db_transfer.failed": "❌ Database {action} failed: {err}\nPlease check the logs.",
        "db_transfer.label_bindings": "QQ bindings",
        "db_transfer.label_openid_bindings": "OpenID bindings",
        "db_transfer.label_check_in_state": "Check-in states",
        "db_transfer.label_heist_log": "Heist logs",
        # Red packets
        "rp.disabled": "🧧 The red packet feature is currently disabled.",
        "rp.count_required": "Please provide the number of shares.\nUsage: 发红包 [shares] [total quota], e.g. 发红包 10 50",
        "rp.count_invalid": "❌ Shares must be a positive integer, but \"{input}\" cannot be recognized.\ne.g. 发红包 10 50",
        "rp.count_too_large": "❌ A packet can have at most {max} shares.",
        "rp.amount_required": "Please provide the total quota.\nUsage: 发红包 [shares] [total quota], e.g. 发红包 10 50",
        "rp.amount_invalid": "❌ Total quota must be a positive number, but \"{input}\" cannot be recognized.\ne.g. 发红包 10 50",
        "rp.amount_too_large": "❌ Total quota per packet cannot exceed {max}.",
        "rp.too_small": "❌ Total quota is too low to split into {count} shares. Increase the amount or reduce the share count.",
        "rp.created": "🧧 {creator} sent a lucky red packet!\n💰 Total {amount} quota · {count} shares\n👉 Send \"抢红包 {pid}\" to grab!\n⏰ Valid for {hours} hours, first come first served~",
        "rp.official_only_hint": "\n🤖 This packet can only be grabbed via the official bot; grabs sent elsewhere are ignored.",
        "rp.pid_required": "Please provide the packet ID (announced when created), e.g. 抢红包 3",
        "rp.pid_invalid": "❌ Packet ID must be numeric, but \"{input}\" cannot be recognized.\ne.g. 抢红包 3",
        "rp.not_found": "❌ Packet #{pid} not found. Please check the ID.",
        "rp.expired": "⏰ Too slow, this red packet has expired.",
        "rp.empty": "😭 Too slow, the red packet has been fully grabbed!",
        "rp.already": "🙃 You've already grabbed this packet, don't be greedy~",
        "rp.api_error": "- Failed to credit the red packet (share not consumed). Please retry later or contact the admin.",
        "rp.success": "🎉 Congrats! You grabbed {amount} quota!\n💰 Credited directly to your balance\n📦 {remain}/{total} shares left in this packet",
        # User red packets (deducted from sender balance)
        "rp.user.disabled": "🧧 The personal red packet feature is currently disabled.",
        "rp.user.count_required": "Please provide the number of shares.\nUsage: 个人红包 [shares] [total], e.g. 个人红包 10 50",
        "rp.user.count_invalid": "❌ Shares must be a positive integer, but \"{input}\" cannot be recognized.\ne.g. 个人红包 10 50",
        "rp.user.count_too_large": "❌ A packet can have at most {max} shares.",
        "rp.user.amount_required": "Please provide the total quota.\nUsage: 个人红包 [shares] [total], e.g. 个人红包 10 50",
        "rp.user.amount_invalid": "❌ Total quota must be a positive number, but \"{input}\" cannot be recognized.\ne.g. 个人红包 10 50",
        "rp.user.not_verified": "🔒 Identity verification is required before sending your first personal red packet.\nPlease send: 验证令牌 your-website-access-token\n(Get it on the New API site under Profile → Generate system access token)\n⚠️ Treat the token like a password: verify in a private chat if possible; reset it on the site if it was exposed in a group.",
        "rp.user.balance_unavailable": "❌ Unable to fetch your account balance right now. Please try again later.",
        "rp.user.limit_reached": "🧧 You've used up today's personal red packet sends~\n💰 Current balance {balance} (1 send per {per} of balance, up to {max}/day)\n📅 Sent today: {used}. Come back tomorrow!",
        "rp.user.exceeds_balance": "❌ The packet total cannot exceed your balance (currently {balance}).",
        "rp.user.deduct_failed": "❌ Deduction failed; the packet was not created. Please retry later or contact the admin.",
        "rp.user.create_failed": "❌ Packet creation failed; {amount} has been refunded. Please retry later; contact the admin if the refund is missing.",
        "rp.user.created": "🧧 {creator} sent a lucky red packet from their own balance!\n💰 Total {amount} · {count} shares (deducted from balance)\n📦 Sender's remaining balance: {balance}\n👉 Send \"抢红包 {pid}\" to grab!\n⏰ Valid for {hours} hours · sender can send {left} more today",
        # Personal packet identity verification
        "rp.verify.token_required": "Usage: 验证令牌 [your website access token]\nGet it on the New API site under Profile → Generate system access token.\n⚠️ Treat the token like a password: verify in private chat if possible; reset it if exposed in a group.",
        "rp.verify.success": "✅ Verification succeeded! The token is valid and matches website ID {site_id}.\nYou can now use \"个人红包 [shares] [total]\" directly — no need to verify again.",
        "rp.verify.failed": "❌ Verification failed: the access token is invalid or does not match your bound website ID.\nMake sure the token belongs to your bound account and try again.",
    },
}


# 插件反馈 issue 入口（报错文案统一附带）
_ISSUE_URL = "https://github.com/Tianxu-Astrbot-Plugins/astrbot_plugin_newapi_tx/issues"
_ISSUE_FOOTER_ZH = f"\n\n🛠 遇到问题？请到 {_ISSUE_URL} 反馈（建议附上后台日志，我们会尽快处理）"
_ISSUE_FOOTER_EN = f"\n\n🛠 Having trouble? Report at {_ISSUE_URL} (backend logs appreciated)"

# 视为「插件内部失败」的文案 key：translate() 会自动附上反馈链接。
# 用户输入校验类提示（如 ID 格式错误、未绑定、黑名单）不算报错，不在此列。
_ERROR_KEYS = frozenset({
    "common.unexpected_error",
    "bind.failed",
    "unbind.failed",
    "check_in.api_user_not_found",
    "check_in.api_update_failed",
    "check_in.unknown",
    "query_balance.failed",
    "query_other.failed",
    "adjust.fetch_failed",
    "adjust.update_failed",
    "heist.api_error",
    "heist.unknown",
    "rp.api_error",
    "db_transfer.failed",
})


def translate(lang: str, key: str, **kwargs):
    """按语言返回翻译后的文案；缺 key 或语言时回退到中文，再回退到 key 本身。

    命中 ERROR_KEYS（插件内部失败类文案）时自动追加 issue 反馈链接，方便用户上报。
    """
    lang_key = "en" if str(lang).lower().startswith("en") else "zh"
    msg = _TRANSLATIONS.get(lang_key, _TRANSLATIONS["zh"]).get(key)
    if msg is None:
        msg = _TRANSLATIONS["zh"].get(key, key)
    if kwargs:
        try:
            msg = msg.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            pass
    if key in _ERROR_KEYS:
        msg += _ISSUE_FOOTER_ZH if lang_key == "zh" else _ISSUE_FOOTER_EN
    return msg
    return msg
