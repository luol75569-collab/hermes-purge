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

### C. 发布前自检

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
