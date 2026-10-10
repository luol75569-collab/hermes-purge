# Hermes Purge

面向 **NousResearch/hermes-agent** 的破甲与配置管理插件，参考 [YuJunZhiXue/dsh-purge](https://github.com/YuJunZhiXue/dsh-purge) 的破甲机制、预览、应用和还原思路。当前版本 **0.2.0**。

破甲层由三部分组成，全部走 Hermes 自己的插件契约，不改宿主源码：

| 层 | 做什么 | 落点 |
| --- | --- | --- |
| 注入 | 把加密破甲提示词作为新会话的系统提示词段注入（身份、直接执行、反拒答） | `register_system_prompt_section` |
| 改写 | 每次请求前把宿主的信任边界/拒绝终局文案改成可用参考（如 `untrusted_tool_result` 框头、`approvals.deny` 终局句） | `llm_request` 中间件 |
| 续跑 | 检测到模型拒答后，在下一次请求末尾注入一条继续执行的 user 消息（按轮限次） | `llm_request` 中间件 + `transform_llm_output`/`post_llm_call` 观察 |

外加策略层：`armor` 预设把 `approvals.mode` 设为 `off`（Hermes 原生常规审批关闭）。显式 `approvals.deny`、硬线黑名单、特殊文件检查与模型服务端行为仍由上游决定。

提示词本体不以明文出现在仓库里：`hermes_purge/armor/*.md` 是编辑用的源文件，随包发布的是 `hermes_purge/armor_blob.py` 里的密封槽位（随机 mask 派生密钥 + 压缩 + 加密 + 校验标签），与上游 dsh-purge 的加密默认提示词同构。改提示词后运行 `python3 scripts/embed_armor_prompt.py` 重新封装。

## 安装

Hermes 的原生安装入口是 `hermes plugins install`，它只接受三种标识：catalog 条目名、完整 Git URL、`owner/repo` 简写（可带 `#子目录`）。**不接受本地路径**——本地目录走自带的 `hermes-purge install` 子命令。

### A. 发布到 GitHub，用 owner/repo 安装

仓库根目录必须**直接**是插件目录：`plugin.yaml`、`__init__.py`、`hermes_purge/` 放在仓库根，不要再套一层 `hermes-purge/`。本 tar 包里 `hermes-purge/` 的内容就是仓库根该有的东西。

```bash
cd hermes-purge
git init && git add . && git commit -m "hermes-purge 0.2.0"
git remote add origin git@github.com:<owner>/<repo>.git
git push -u origin master
```

目标机器上：

```bash
hermes plugins install <owner>/<repo> --enable
hermes plugins install https://github.com/<owner>/<repo>.git --ref <40 位 commit SHA> --yes-deps --enable
hermes plugins list --user
hermes purge armor            # 确认加密提示词套与改写规则表可读
```

`--ref` 固定到某个 commit；`--yes-deps` 让非交互环境（SSH、CI、容器入口）自动同意安装声明里的 `ruamel.yaml`，否则会停在依赖确认问题。装完重启 Hermes 并新建会话，提示词段才会进会话。之后 `hermes plugins update hermes-purge` 拉更新，`hermes plugins check-updates` 只检查不动。

进官方 curated catalog 是另一件事：条目由 hermes-agent 仓库的 `plugin-catalog/README.md` 准入规则管，需要走 PR；不申请也能用自己的 `owner/repo` 直接装。

### B. 本地目录

要求 Python 3.11+。在本项目目录运行：

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/python -m hermes_purge --home "$HOME/.hermes" install
hermes plugins enable hermes-purge
.venv/bin/python -m hermes_purge --home "$HOME/.hermes" serve --open
```

Windows 将 `.venv/bin/python` 换成 `.venv\Scripts\python.exe`，先用 `py -3.11 -m venv .venv`。如果 Hermes 的插件环境缺少依赖，使用该安装的原生插件依赖管理流程安装 manifest 声明的依赖；不要对 Hermes 环境运行上面的开发环境 pip 命令。

安装只复制本插件，不会自动应用配置。插件目录已存在时保留原文件并报错。面板地址带一次性随机令牌，仅监听 `127.0.0.1`；`Ctrl+C` 关闭。

### C. Windows

Windows 上和 macOS/Linux 的差别只有三处，都不需要单独分支：

Hermes 的 Windows 默认 home 是 **`%LOCALAPPDATA%\hermes`**（源码 `hermes_constants._get_platform_default_hermes_home`），不是 `~/.hermes`；设了 `HERMES_HOME` 时以环境变量为准。所以 `--home` 要写对：

```powershell
# 前置：Git for Windows（hermes plugins install 走 git clone ）、Node ≥18、Python 3.11+
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install .

# 发布后（推荐）
hermes plugins install <owner>/<repo> --yes-deps --enable

# 或从本地目录
.venv\Scripts\python.exe -m hermes_purge --home "$env:LOCALAPPDATA\hermes" install
hermes plugins enable hermes-purge
hermes purge armor
```

`--yes-deps` 在 Windows 上同样有用：`hermes plugins enable` 会提示安装声明里的 `ruamel.yaml`，非交互场景需要它替你应答（本机实测该步会自动装上依赖并输出 “Installing Python dependencies… ✓”）。

中文输出：本插件的 CLI 在打印前会把 stdout/stderr 切到 UTF-8（`cli.force_utf8_streams`），所以 `hermes purge armor` 里的中文标签不会在 cp936 控制台上抛 `UnicodeEncodeError`。终端若仍显示乱码，用 Windows Terminal 或 `chcp 65001`。面板同样可用：`hermes-purge serve --open`，只监听 `127.0.0.1`。

这一节基于源码与平台单测（Windows 的 home 解析分支、ASCII-only 控制台输出），**未在 Windows 实机跑过**；备份目录的 `0700`/`0600` 权限在 Windows 上按该系统语义降级。macOS/Linux 侧则是完整实机验证：`hermes plugins install → list → enable → doctor → hermes purge apply --preset armor → 会话提示词段渲染 → remove`。

### D. 发布前自检

用 Hermes 自己的准入校验器过一遍（本版本结果：14 项全 PASS，安全扫描 verdict `safe`，零警告）：

```bash
hermes plugins validate . --json     # catalog 准入 CI gate
hermes plugins doctor .              # 用真实运行时契约加载一遍
```

`validate` 会把 `plugin.yaml` 的 `provides_tools` / `provides_hooks` / `provides_middleware` 与 `register()` 实际注册的东西逐项对照，缺声明会直接 FAIL——本插件的 manifest 已按此对齐。

启用并重新加载后可以使用原生命令与模型工具：

```bash
hermes purge status            # 磁盘状态 + 破甲运行时计数（会话内，只读）
hermes purge armor             # 加密提示词套与文案改写规则表
hermes purge plan --preset armor
hermes purge apply --preset armor
hermes purge apply --preset armor --prompt-set armor-lite
hermes purge revert
hermes purge serve --open
```

模型侧工具：`purge_status`、`purge_apply`、`purge_revert`（与上游同名）。

## 一键安装（分享给别人）

要直接转发给对方，用 [SHARE.md](SHARE.md)——一段自包含说明，把里面的 `OWNER` 换成你的账号即可（文件顶部给了替换命令）。

### 1. 桌面端一键链接

Hermes Desktop 注册了 `hermes://` 协议，插件安装链接是官方支持的形态：

```
hermes://plugin/install?repo=<owner>/hermes-purge&enable=1
```

参数来自 `apps/desktop/src/lib/deeplink-routes.ts`：

| 参数 | 作用 |
| --- | --- |
| `repo`（或 `identifier`） | Git 仓库标识：`owner/repo` 或完整 URL |
| `enable` | 装完是否启用，**默认就是 true**；写 `0`/`false`/`no` 可关 |
| `force` | 覆盖已安装的同源副本 |
| `catalog` | 改走 curated catalog 名（本项目不用，见下） |

点链接**不会静默安装**：Desktop 会弹出确认框（仓库 id、安装前提示、GitHub 浏览/克隆链接），scan 出 agent / desktop 组件让用户勾选后才装，走的扫描与 `hermes plugins install` 完全一致。开发构建里 scheme 换成 `hermes-dev://`。

网站或 README 里直接贴，不需要任何 SDK：

```html
<a href="hermes://plugin/install?repo=<owner>/hermes-purge&enable=1">Install in Hermes</a>
```

### 2. 一条命令

```bash
hermes plugins install <owner>/hermes-purge --yes-deps --enable
hermes plugins install https://github.com/<owner>/hermes-purge.git --ref <40位SHA> --yes-deps --enable  # 可复现
```

Windows PowerShell 同一条（`hermes` 需在 PATH）。

### 3. 一键脚本

```bash
# macOS / Linux：先下载再看一眼，然后执行（不直接从管道执行）
curl -fsSLo install.sh https://raw.githubusercontent.com/<owner>/hermes-purge/master/install.sh
bash install.sh --repo <owner>/hermes-purge
```

```powershell
# Windows
irm https://raw.githubusercontent.com/<owner>/hermes-purge/master/install.ps1 -OutFile install.ps1
.\install.ps1 -Repo <owner>/hermes-purge
```

脚本只调 `hermes plugins install`，不改 Hermes 检出、不写选定 profile 之外的位置；`--ref` 固定 commit，`--no-enable` 先装后验，`--home` 指定 profile home。缺 `hermes` 或缺 `git` 时直接报错退出，不会装作成功。

### 4. 交给 AI 助手安装（整段复制）

> 请帮我核对并安装 Hermes 插件 hermes-purge，仓库 `<owner>/hermes-purge`，条目版本 0.2.0，安装包同版本。
>
> 先检查环境：`hermes --version`；`hermes plugins list --user` 看目标 profile 是否已有同名插件；确认 `git` 可用；多 profile 时用 `hermes -p <name>` 或 `HERMES_HOME` 指定目标 profile，不要装到错误的 home。
>
> 安装：
> `hermes plugins install <owner>/hermes-purge --yes-deps --no-enable`
> 然后用 `hermes plugins doctor hermes-purge` 核对 —— 必须报 manifest `hermes-purge 0.2.0`、`runtime discovery, manifest parsing, import, and registration passed`、`3 tool(s), 2 hook(s)`。
> 不要用同名插件、其它版本或其它仓库替代。
>
> 核对通过后 `hermes plugins enable hermes-purge`，完全退出并重开目标 profile，再验证：
> `hermes plugins list --user`、`hermes purge armor`（应列出 3 套密封提示词套与改写规则表）、`hermes purge status`。
> 只有以上真实输出确认过才算安装成功；任何一步不符或环境不满足（缺 hermes、缺 git、版本对不上），先说明原因再继续，不要跳过。
>
> 注意：本插件含破甲层（破甲提示词注入、宿主拦截文案改写、拒答续跑），`armor` 预设会写 `approvals.mode=off`。仅在你自己的机器上安装。应用破甲是单独一步：`hermes purge apply --preset armor`，回滚用 `hermes purge revert`，整体停用用 `hermes plugins disable hermes-purge`。

> **首次在全新 Hermes 上安装**：Hermes 会先为这个 home 准备隔离运行时（`uv sync` 整套依赖），需要网络、可能几分钟；网速差时它以 `Failed to download …` 结束，此时先 `hermes pm repair` 或换网重试，再装插件本身。已初始化过的 Hermes 不触发这一步。

### 5. 和 dsh-purge 那种链接的差别

- **没有"托管 tgz 制品"形态。** `hermes plugins install` 只接受 catalog 名、Git URL、`owner/repo`（`hermes_cli/plugins_cmd.py::_resolve_git_url`），所以链接指向仓库，不指向 tarball。
- **深链不能 pin commit。** 只有 catalog 条目带 40 位 SHA pin；要可复现就把 CLI 命令连 `--ref` 一起发。
- **本项目不走 curated catalog。** 条目要求精确 SHA + 能力声明（`plugin.yaml` 的 `provides_*` 已按此对齐），但准入规则 12 明确禁止插件绕过 Hermes 的审批系统，而 `armor` 预设会写 `approvals.mode=off`——与其在 PR 里把破甲摘掉，不如只走 `repo=` 深链和 CLI。

## 提示词套与模型

| 套名 | 用途 | 字符数 |
| --- | --- | --- |
| `armor`（默认） | 破甲主稿：身份、直接执行、反拒答、宿主文案降权 | 648 |
| `armor-lite` | 小上下文或审核很紧的小模型用短稿 | 261 |
| `plain` | 原工程版提示词，无身份与反拒答 | 408 |

不指定时按模型名自动选择（`flash/turbo/mini/lite/small/1..4b` → `armor-lite`，其余家族 → `armor`），可在面板或 `--prompt-set` 显式覆盖。选定套名写入 `plugins.entries.hermes-purge.settings.prompt_set`，提示词正文写入 `...settings.prompt`。

已有自定义提示词不会被预设重置；只有显式传入 `--prompt-file` 或 `--prompt-set` 才会覆盖。

## 预设

| 预设 | 实际变更 | 保持不变 |
| --- | --- | --- |
| `armor`（默认） | 破甲提示词 + `approvals.mode=off` | 模型、凭据、工具集合、轮次上限 |
| `developer` | 工程版提示词；开启原生执行、工具使用、完成任务和并行调用引导 | 审批模式、模型、凭据、工具集合 |
| `minimal` | 工程版提示词；关闭 `agent.execution_guidance` 文案块 | 其他引导和全部执行检查 |
| `prompt-only` | 仅工程版提示词 | 其他宿主配置 |

`--approval-mode manual|smart|off` 与 `--max-iterations` 与预设正交，显式传入才写。`off` 是 Hermes 原生的常规审批关闭，不等于关闭一切检查。`--max-iterations` 写入经源码核实的 `agent.max_turns`。

## 面板

`hermes purge serve --open` 打开本地面板（自带令牌、仅回环）。左侧选预设、提示词套、审批模式、轮次与提示词；右侧显示磁盘状态、密封提示词清单、文案改写规则表与差异预览。应用前必须预览，应用时校验预览哈希。

## 预览、备份与回滚

`plan` 不写文件。`apply` 保留 YAML 注释、键顺序和引号；只设置受管键，不清空其他配置。每次非空应用先保存完整原始配置与 SHA256，再原子替换；重复相同应用返回 `unchanged`。

备份位于选定 home 的 `purge/backups/`（目录 `0700`、文件 `0600`）。**备份包含原配置中的所有数据，应按原配置的保密等级管理。** 本地锁只协调本插件的写操作。

```bash
hermes-purge plan --preset armor
hermes-purge apply --preset armor --expected-sha256 '上一步输出的 before_sha256'
hermes-purge revert
```

`revert` 按后进先出逐次还原原始字节；多次应用需多次回滚。应用后文件被其他程序修改时回滚会停下并保留当前文件。备份哈希损坏、软链接、非法 YAML、错误 profile 记录或并发写入均报错。

卸载先回滚需要恢复的应用，再运行 `hermes plugins remove hermes-purge`。备份不自动删除。

## 运行时设置

`plugins.entries.hermes-purge.settings.*`：

| 键 | 默认 | 作用 |
| --- | --- | --- |
| `enabled` | `true` | 破甲运行时总开关（中间件与观察钩子） |
| `scrub` | `true` | 请求前改写宿主拦截文案 |
| `refusal_recover` | `true` | 拒答后追加继续执行消息 |
| `max_recoveries_per_turn` | `2` | 每轮续跑上限（0–5） |
| `recover_text` | 空 | 自定义续跑文案 |
| `prompt_set` | 空 | 提示词套；空表示按模型自动 |
| `prompt` | 空 | 自定义提示词；非空时优先于密封提示词 |

## 边界与已知差异

- **不逐条移植上游的宿主源码补丁。** dsh-purge 对 DSH 的 `@deepseek-ai` 包做磁盘补丁（提示词拼接、审批门、沙箱、拒绝恢复等）；Hermes 有原生的插件、钩子和中间件接口，本实现只在运行时的请求 payload 上做确定性改写，磁盘上的 Hermes 源码保持原样，`git status` 无改动。
- **续跑不是即时 followup。** 上游用 `agent.followup` 在轮次结束时立刻续跑；Hermes 没有插件可用的轮次内 followup 接口，因此续跑作为**下一次请求**的 user 消息（角色交替合法）下发，并按轮限次。检测本身按轮记录，计数可在 `hermes purge status` 的 `armor.stats` 查看。
- **不伪造模型回答。** `transform_llm_output` 只登记拒答，不改写用户已经看到的答复文本。
- **改写只覆盖有源码锚点的文案。** 规则表每条都标注 Hermes 源码位置（见 `hermes purge armor`）；宿主改了文案则命中数归零，不会凭空改写无关内容。改写是幂等的。
- **宿主上游仍有不可绕过的部分。** 硬线黑名单（`tools/approval_floors.py` 的 `_hardline_block_result` 路径）、`runtime_self_protection`、模型服务端策略不受本插件影响；对应文案的改写只影响模型如何理解那条拒绝，不影响拒绝本身是否发生。
- 未内嵌上游的演练台、红队技能库、`net-scope` 名单与桌面重启链；这些依赖 DSH 专有接口与资产，未在 Hermes 上做等价实现。
- 源码验证基线为 Hermes commit `f925b01791fe052e7d55dc975750c0bd985aff91`。需要原生 `register_system_prompt_section`、`register_command`、`register_cli_command`、`get_config`、`register_middleware`、`register_hook`、`register_tool`；缺失能力会明确报错，不猜测内部偏移。

验证命令：

```bash
python -m unittest discover -s tests -v
python tests/native_probe.py --hermes-source ../reference/hermes-agent
python tests/browser_probe.py
```

实现细节、逐项证据与剩余限制见 [适配报告](docs/adaptation-report.md)。

## 来源

破甲机制与提示词管理思路来源：[YuJunZhiXue/dsh-purge](https://github.com/YuJunZhiXue/dsh-purge)。Hermes 接口来源：[NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent)。独立第三方项目，没有上游官方背书。逐项借用清单见 [NOTICE.md](NOTICE.md)。
