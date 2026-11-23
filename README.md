# Sessiontool

在本机完整查看 Claude 桌面应用（Code 标签页）、Claude Code、Codex 和 Gemini（Antigravity）的会话记录，并统计用量和费用。

桌面应用对过大的会话只显示最近一段（“Earlier messages aren't shown. This session is too large to load in full.”）。
记录其实完整地保存在磁盘上，Sessiontool 读取它们，在浏览器里把每个会话从第一条消息开始显示出来。
用 [multi-claude](https://github.com/thomasog/multi-claude) 同时登录几个账号的，各个账号的会话也都在一起，标题旁标着是哪个账号的。

## 启动

双击 `Sessiontool.bat`，或者在本文件夹运行：

```bash
python -m sessiontool
```

它会在本机启动一个网页服务并打开浏览器（默认 <http://127.0.0.1:7707/>）。保持那个窗口开着，关掉窗口即停止。
需要 Python 3.10 或更高版本，没有第三方依赖。

想在任意位置用 `sessiontool` 命令：

```bash
pip install -e .
```

## 功能

- **完整历史**：一个应用会话在磁盘上常常对应多份记录（压缩或重启后会新建文件），本工具按应用自己的会话清单把它们合并去重，一个会话一页。
- **多个账号**：普通安装的应用和 multi-claude 的每个配置各有一份会话清单，都会读到；同一个会话在几处都有时取最近活动的那份。每个会话标着属于哪个账号（邮箱 @ 前面那段，悬停看完整邮箱），列表可以按账号筛选。
- **Codex**：`~/.codex` 里 Codex 的会话和 Claude、Gemini 的放在一起看，左栏最上面切换来源或“全部”。标题、归档取自 Codex 自己的线程表，工具调用、推理摘要、截图、改过的文件和 Claude 的会话一样显示。
- **Gemini**：读取 `~/.gemini/antigravity` 与 `~/.gemini/antigravity-cli` 中 Antigravity 应用和 CLI 的会话记录。标题、工作区、归档状态和子代理归属取自 `conversation_summaries.db`，思考过程、工具调用、图片、修改过的文件与子代理过程按统一格式展示，子代理用量计入所属会话。
- **实时更新**：页面开着时，有新记录就自动显示出来，不用刷新页面；只换有变化的部分，读到哪、展开了什么都保持原样。正在看最新内容时自动跟到底，不在底部时浮出“有新内容”。右上角的“实时”可以暂停。
- **复刻的会话**：补上只存在于原会话里的更早历史，并标出复刻点。
- **全文搜索**：搜全部会话的对话内容，空格分隔的多个词要同时出现在一条消息里；可选择同时搜工具调用与输出。点结果直接跳到那条消息并高亮，会话页里也可以单独搜索。
- **过程可以折起**：每一轮分成“你的提问 → 过程 → 最终答复”。过程（中间说明、工具调用）可以单独折起；过程的小结里写着这一轮的用时和费用。
- **三种视图**：完整（完整内容，并默认展开每一段思考）；对话（隐藏工具调用、思考过程和系统通知）；结果（只留提问和最终答复）。
- **工具调用**：默认只显示一行摘要，展开时才读取完整的输入和输出，包括被应用另存到 `tool-results` 的超长输出。
- **图片**：你发的图片、工具输出里的截图（以缩略图排在那次调用下面）、Claude 发给你的图片文件都直接显示，点击放大。
- **发给你的文件**：Claude 交付的文件单独列出，带说明；原位置已经没有的会标出来。
- **子代理**：调用了子代理的地方可以点进去看它自己的完整过程。
- **改写过的消息**：回退并改写后，旧的那一支折叠成“改写前的旧分支”，和应用一样默认不显示。
- **回复进行中追加的消息**、中断、上下文压缩、额度恢复后的自动继续，都按实际发生的位置标出来。
- **修改过的文件**：会话页顶部汇总这次会话里编辑、写入过的文件，点文件名跳到第一次修改的位置。
- **在应用中打开**：从会话页直接跳回 Claude 桌面应用里的同一个会话。
- **导出**：任一会话可导出为单个 HTML（可离线打开，可选内嵌工具截图）或 Markdown。
- **会话详情**：两种 ID（应用会话 ID、记录 ID）、恢复命令、项目文件夹和记录文件的路径都可以一键复制；账号（邮箱、账号 ID、组织 ID、multi-claude 配置）；
  费用和用量（按 API 价格估算的费用和分项、缓存命中率、输入输出、读写缓存、思考、网页搜索），按模型、按推理强度各一张表；
  还有时间、模型与设置、各项数量、最常用的工具、应用记下的最近状态、相关的复刻会话。
- **统计**：左栏“统计”页，类似 Claude Code 的 `/stats`，可按时间（7 / 30 / 90 天、全部）、来源和账号筛选：
  费用、tokens、缓存命中率、回复、会话、活跃天数和连续天数、最常用的模型、最忙的时段；每天按模型分开的柱状图（可换成表格）、
  每天回复次数的日历、一周 × 24 小时的时段分布；按模型、推理强度、账号、项目的明细，花得最多的会话；
  各账号的额度（应用自己隔一会儿记下的 5 小时窗口和 7 天窗口用了多少，以及最近 7 天的走势）。

### 费用怎么算

费用都是按 API 价格估算的：同样的用量按 token 计价要多少钱。订阅用户实际不按 token 付费，看的是相对大小。

- 每次回复的用量（输入、输出、读缓存、写缓存分 5 分钟和 1 小时两种、网页搜索）取自记录本身；一次回复在记录里拆成多行时只算一次。
- Claude 的价格取自 Anthropic 官方价目（2026-11，含 Fable 5.2、Opus / Sonnet / Haiku 5.5、快速模式与 Haiku 5.5 长提示词分档）；Codex 的价格取自 OpenAI 官方价目（2026-11，含 GPT-6.2 Astra / Sol、GPT-6.1 Sol / Terra、GPT-6、GPT-5 系列及 272K 长提示词与快速模式分档）；Gemini 的价格取自 Google 官方价目（2026-11 标准价，含 Gemini 4 隐式缓存读取 95% 折扣）。
- 复刻的会话只算复刻点之后自己的回复，之前的算在原会话里；子代理的用量算在调用它的会话里。
- 没有价格的模型不计入费用，金额后面会带个 `+`。可以在索引目录（默认 `~/.sessiontool`）放一个 `prices.json` 补上或改写，单位是美元 / 百万 token：

```json
{"gpt-6-luna": [1.25, 10, 0.125], "claude-opus-5-5": [4, 20, 0.2, 5, 8]}
```

五项依次是输入、输出、读缓存、写缓存（5 分钟）、写缓存（1 小时）；只写前三项时写缓存按输入价算。

## 界面

- **左栏**：左右分栏各自独立滚动。顶栏右侧通过横向滑块切换页面（会话 / 统计），下方切换来源（Claude / Codex / Gemini 并列，右侧带独立的“全部”按钮，存在多种来源时出现）；会话页左栏上方为账号下拉菜单，中部为项目列表，选项置底；统计页左栏展示当前范围的用量摘要与趣味换算（如《万叶集》倍数等）。
- **会话列表**：右侧按最近活动分组，复刻的会话缩进在原会话下面。每行显示最近一条有内容的提问、账号、费用；鼠标移上去右下角有“复制 ID”和“详情”。
- **会话页**：左侧是你每条提问的目录（支持正序 / 倒序切换），会跟随阅读位置高亮；右下角有回到开头和滑到底部的浮动按钮。你是蓝色头像和气泡，Claude 是赭色头像、Codex 是绿色、Gemini 是靛紫色；一条竖线把提问、过程和答复串成一轮。标题下面的 ID 点一下就复制。
- **统计页**：最上面一行是筛选，下面的数字、图和表都按它来；图上悬停看每一天、每一格的数字。
- **记住状态**：从会话回到列表时，筛选、搜索词和滚动位置都还在；再次打开一个会话时直接回到上次阅读到的精确位置。
- **图片**：点击放大后可以用 ← → 在整页的图片之间切换。
- **主题**：切换浅色、深色或跟随系统，选择会记住。
- **动效**：页面切换、折叠块开合、提示条都有过渡；系统设置了“减少动态效果”时自动关闭。

按 `?` 可以在页面里打开这张表。

| 按键 | 作用 |
|---|---|
| `/` | 聚焦搜索框 |
| `R` | 立刻重读磁盘 |
| `L` | 暂停或继续实时更新 |
| `S` | 列表页、统计页：切换 Claude / Codex / Gemini / 全部 |
| `I` | 会话详情（列表页是选中的那个会话） |
| `J` / `K` | 会话页：下一条 / 上一条你的提问。列表页：在会话和搜索结果之间移动（`↓` `↑` 也可以） |
| `Enter` | 列表页：打开选中的会话。搜索时：跳到下一处（`Shift+Enter` 上一处） |
| `C` | 列表页：复制选中会话的 ID |
| `1` `2` `3` | 会话页：完整 / 对话 / 结果视图 |
| `E` | 会话页：折起或展开当前这一轮的过程 |
| `Esc` | 关闭浮层、清空搜索 |

## 命令行

```bash
python -m sessiontool                      # 启动网页（同 serve）
python -m sessiontool serve --port 8000 --no-browser
python -m sessiontool list                 # 列出全部会话，带来源、账号和费用
python -m sessiontool export 36960785      # 按编号导出为 HTML，输出到 ./export
python -m sessiontool export "PPT 设计" -f md -o D:\notes
python -m sessiontool export --all --images  # 全部导出，并内嵌工具截图（文件很大）
python -m sessiontool reindex              # 删除索引并重建
```

`--root 路径` 指定别的会话记录目录（默认 `~/.claude/projects`），`--codex 路径` 指定 Codex 的数据目录（默认 `~/.codex` 或环境变量 `CODEX_HOME`），`--gemini 路径` 指定 Gemini（Antigravity）的数据目录（默认 `~/.gemini` 或环境变量 `GEMINI_HOME`），`--home 路径` 指定索引放在哪（默认 `~/.sessiontool`）。这几个选项都写在子命令前面。

## 数据与隐私

- **只读**：不修改、不删除任何会话记录。
- **不联网**：服务只监听 `127.0.0.1`，拒绝非本机地址的请求，页面不加载任何外部资源。
- **读取的位置**
  - Claude Code 的会话记录：`~/.claude/projects/<项目>/<会话>.jsonl`（各个账号共用这一处），以及同目录下的标题旁路文件 `<会话>/custom-title.json`、后台任务状态 `~/.claude/jobs/*/state.json`
  - 应用的会话清单（标题、哪些记录属于同一会话、复刻关系、属于哪个账号）：
    `%LOCALAPPDATA%\Claude-Data\<包名>\claude-code-sessions`（2.42304 起）、`%APPDATA%\Claude\claude-code-sessions`；
    Windows 商店版在 `%LOCALAPPDATA%\Packages\Claude_*\LocalCache\Roaming\Claude\claude-code-sessions`；
    multi-claude 的各个配置在 `~/.multi-claude/data/Claude-<配置名>/claude-code-sessions`
  - 额度用量：上面各个应用数据目录里的 `plan-usage-history.json`
  - 账号的邮箱：Claude Code 在终端登录的账号（`~/.claude.json`）；记录里写着的邮箱；
    Codex 登录的账号（`~/.codex/auth.json` 里只解开身份令牌中写着邮箱的那段，不读、不用任何令牌）；
    Gemini（Antigravity）登录的账号（`Antigravity/app_storage.json` 中的 `agy.onboarding.lastLoginUsername` 或 `~/.gemini/antigravity-cli/cli.log`）
  - Codex：`~/.codex/sessions/**/rollout-*.jsonl`、`~/.codex/archived_sessions`，标题和归档取自 `~/.codex/state_*.sqlite`（只读打开）
  - Gemini（Antigravity）：`~/.gemini/antigravity/brain/*/.system_generated/logs/transcript_full.jsonl` 及 `~/.gemini/antigravity-cli` 下同结构记录；标题、工作区、归档与子代理归属取自 `conversation_summaries.db`，项目名取自 `~/.gemini/config/projects/*.json`，各步骤的精确模型、用量与思考 token 取自 `conversations/*.db`（均只读打开）
- **写入的位置**：只有索引 `~/.sessiontool/index.db`（可用环境变量 `SESSIONTOOL_HOME` 改位置）。
  索引只存文字、位置和用量，图片和工具的完整输出留在原记录里按需读取，所以索引远小于记录本身。删掉它不影响任何记录，下次启动会重建。
- 导出的文件包含对话内容，注意存放位置。

## 已知的限制

- 桌面应用清单里没有的记录（终端里直接运行的 Claude Code、或桌面应用清单已被删除的会话）各自显示为一个会话，不会互相合并；其中由桌面应用创建但清单缺失的会话会标出“不在应用列表中”，`claude agents` 中用 `Ctrl+X`（或 `claude rm`）移除的后台会话会标出“已归档”。
- 复刻会话里与原会话重复的消息，搜索结果只列在原会话下。
- “在应用中打开”依赖应用注册的 `claude://` 链接，由系统默认的那个 Claude 打开；multi-claude 的配置里的会话要在那个配置的窗口里找。不在应用列表中的会话没有这个按钮。
- 思考过程只有在记录里保存了文字时才显示。应用多数时候只保存一段加密签名、不保存文字，那部分无法还原。
- 账号的邮箱靠线索推断：登录信息里没有的账号，取它的会话记录里出现最多的邮箱。
- 子代理的过程读取 Claude 的 `<会话>/subagents/agent-*.jsonl` 以及 Antigravity 中按父会话关联的子代理记录。写在 Claude 主记录内部的旧式子代理记录不显示。
- 工具截图和发给你的图片读的是原文件或原记录：临时目录里的文件被清掉后，对应的图片就不再显示。
- 只覆盖 Code 标签页的会话，不包括普通聊天和 Cowork。
- 浏览器对同一个地址同时只开六条连接：实时更新只在看得见的标签页里连着，切到后台的页面回到前台时再补上。

## 开发

```bash
python -m unittest discover -s tests
```

| 模块 | 作用 |
|---|---|
| `util.py` | 零依赖公共基础工具（工具提示提取、内容扁平化、只读 SQLite 连接、ISO 本地时间解析） |
| `claude.py` | 解析 Claude Code / 桌面应用的 `.jsonl` 记录与用量 |
| `codex.py` | 将 Codex 记录整理为统一数据结构 |
| `gemini.py` | 将 Gemini（Antigravity）记录与 `conversations/*.db` 元数据整理为统一数据结构 |
| `providers.py` | 多来源适配器注册表（统一维护各来源元数据、编辑工具集合与解析入口） |
| `sources.py` | 发现会话记录、各处应用清单（含 multi-claude）、Codex 与 Gemini 数据及账号线索 |
| `index.py` | 将各来源 `.jsonl` 增量解析入 SQLite，并按文件与消息索引对话和用量 |
| `sessions.py` | 合并同一会话的多份记录，识别复刻与改写分支，整理条目、账号归属、用量与全文搜索 |
| `pricing.py` | 模型价目表、按 API 价格估算费用与模型显示名归一化 |
| `stats.py` | 计算统计页的时间序列、热力图、模型槽位、账号额度与汇总指标 |
| `details.py` | 按偏移量从原记录或允许目录按需读取工具详情与图片 |
| `markdown.py` | 面向消息正文的零依赖 Markdown → HTML 渲染器 |
| `render.py` | 条目 → HTML / Markdown，按页面装配样式与前端脚本 |
| `server.py` | 本地只读 HTTP 服务、首页渲染缓存与 SSE 实时更新事件流 |
| `export.py` | 导出离线单文件 HTML / Markdown |
| `static/` | 按页拆分的零构建前端资源（`theme.js`、`core.js`、`info.js`、`session.js`、`index.js`、`stats.js`、`app.css`、`icon.svg`） |
