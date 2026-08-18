# NewAPI 多功能插件（星涵煦版）

> `astrbot_plugin_newapi_tx` 是独立维护的 **New API 网站 × QQ 群联动插件**，为 [AstrBot](https://github.com/he0119/AstrBot) 打造，集用户绑定、额度经济、群聊娱乐、管理员工具于一体，并内置退群自动解绑与账号净化能力。

本仓库由 [Tianxu-Astrbot-Plugins](https://github.com/Tianxu-Astrbot-Plugins) 独立维护，功能与配置均以本仓库为准。

## ✨ 功能特性

- **用户系统**：QQ 号 ↔ 网站用户 ID 无缝绑定与数据互通。
- **经济系统**：每日签到随机发放额度、余额查询，额度显示精确到小数点后 6 位。
- **娱乐互动**：`/打劫` 群聊玩法，支持成功、暴击、失败惩罚、每日次数与冷却限制。
- **自动化管理**：监控指定群聊，成员退群（主动退群 / 被踢）时自动解绑并恢复网站用户组。
- **管理员工具**：远程查余额、解绑、智能查询、调整用户额度等便捷指令。
- **配置灵活**：优先推荐插件配置（WebUI）图形化设置，`.env` 文件作为备选，自动建表无需手动操作。

## 🔧 安装步骤

1. **下载插件**：克隆或下载本仓库，您会得到一个名为 `astrbot_plugin_newapi_tx` 的文件夹。
2. **放置插件**：将整个 `astrbot_plugin_newapi_tx` 文件夹放入 AstrBot 实例的 `data/plugins/` 目录。
3. **重启服务**：重启 AstrBot，在 WebUI → `插件市场` → `已安装` 中即可看到本插件。

## ⚙️ 核心配置

机密信息（数据库密码、API 密钥等）支持**两种配置方式**，可同时存在也可只配其一。

> **推荐使用插件配置（WebUI）**，图形化、无需手动维护文件；`.env` 作为备选方案，适合无法打开 WebUI 的场景。

> **优先级规则**：同一字段在插件配置与 `.env` 中同时存在时，**以插件配置为准**；只存在于一方时使用该方；两方皆空则初始化失败。

### 方式一（推荐）：通过插件配置（WebUI）

在 AstrBot 的 WebUI 插件界面中打开本插件配置面板，在 `New API 网站配置` 与 `数据库配置` 分组下填写对应字段即可。其余功能配置（签到奖励、打劫概率、消息模板、监控群号等）均可在同一面板中图形化配置，无需改文件。

### 方式二（备选）：通过 `.env` 文件

如果无法进入 WebUI 或希望以文件方式管理机密信息，可在插件根目录（与 `main.py` 同级）创建 `.env`：

```dotenv
# --- 数据库配置 ---
DB_HOST=127.0.0.1
DB_PORT=3306
DB_USER=your_database_user
DB_PASS=your_database_password
DB_NAME=your_database_name

# --- New API 网站配置 ---
# 您的 New API 网站地址，结尾不要带 /
API_BASE_URL=https://your-new-api-domain.com
# 您在 New API 后台生成的令牌
API_ACCESS_TOKEN=sk-xxxxxxxxxxxxxxxxxxxxxxxx
# 执行管理员操作时使用的用户ID (通常是 1)
API_ADMIN_USER_ID=1
```

> 插件启动时会自动创建所需数据表，无需手动建表。

### 🗄️ 单 SQLite 模式（可选）

不想维护 MySQL 的轻量用户，可在 WebUI → **`SQLite 模式`** 板块中开启 **`use_sqlite_mode`** 开关。开启后：

- 不再使用 MySQL，绑定与打劫日志等数据存储在插件目录的 SQLite 单文件数据库中（`{AstrBot数据目录}/plugin_data/astrbot_plugin_newapi_tx/newapi.db`），自动建表、零配置。
- MySQL 相关配置（主机/端口/用户/密码/库名及 `.env` 中的 `DB_*`）全部忽略。

> ⚠️ **注意**：SQLite 模式与 MySQL 模式是**两套独立数据**，切换模式不会自动迁移已有绑定数据；如从 MySQL 切换到 SQLite，已绑定的用户需要**重新绑定**。

## 📜 指令大全

### 用户指令

| 指令 | 说明 |
| --- | --- |
| `/绑定 [你的网站ID]` | 将您的 QQ 与指定的网站用户 ID 绑定 |
| `/查询余额` | 查询您当前绑定的网站账号剩余额度 |
| `/签到` | 每日签到，随机获取额度奖励（可触发翻倍） |
| `/打劫 @目标用户` | 对群内另一位已绑定用户发起打劫，有成有败 |

### 管理员指令（需 AstrBot 管理员权限）

| 指令 | 说明 |
| --- | --- |
| `/查余额 [网站ID或QQ号/@对方]` | 查询指定用户网站余额（智能识别 ID，支持 @） |
| `/解绑 [网站ID]` | 强制解除指定网站 ID 的绑定关系 |
| `/查询 [网站ID或QQ号]` | 智能查询绑定关系（ID ↔ QQ 互查） |
| `/调整余额 [ID/@对方] [额度]` | 调整用户额度，正数增加、负数减少，如 `/调整余额 12345 100` 或 `/调整余额 @某人 100` |
| `/pingapi` | 检查插件运行状态、数据库与 New API 连接状态 |

## 🤖 自动化功能

### 退群自动净化

在 WebUI 配置中填写需要监控的群号列表后，当成员**主动退群**或**被踢出群聊**时，插件自动：

1. 查询该成员是否已绑定网站 ID；
2. 若已绑定，删除其绑定记录；
3. 通过 API 将其网站用户组恢复为预设的默认组；
4. 在群内发送净化完成通知。

## 📦 版本与更新日志

- 版本号统一以 [metadata.yaml](metadata.yaml) 中的 `version` 为准，主代码自动读取，无需多处同步。
- 更新记录见 [CHANGELOG.md](CHANGELOG.md)。

---

© Tianxu-Astrbot-Plugins | [GitHub](https://github.com/Tianxu-Astrbot-Plugins)
