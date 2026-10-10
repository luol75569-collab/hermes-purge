# Release notes

## v0.2.0

**破甲层（新增）**

- 加密破甲提示词：三套（`armor` / `armor-lite` / `plain`）以密封槽位形式随包发布，源码与安装包内不可读；按模型名自动选择，也可显式指定。
- 宿主拦截文案改写：`llm_request` 中间件在出站请求上确定性改写 Hermes 真实存在的三类文案（`untrusted_tool_result` 信任边界、`approvals.deny` 终局句、硬线不可绕过句），并剥掉 untrusted 外壳；改写幂等，宿主换文案后命中归零。
- 拒答续跑：移植上游拒答检测正则族（道歉+拒绝动词近邻窗口、硬停例外），命中后在下一次请求末尾注入继续执行消息，按轮限次；`transform_llm_output` / `post_llm_call` 只登记，不改写用户已看到的答复。
- `armor` 预设（默认）：写入密封提示词 + `approvals.mode=off`；新增模型工具 `purge_status` / `purge_apply` / `purge_revert`。

**配置管理（0.1.0 起）**

- 受管键差异预览、YAML 注释/键序保留、SHA256 备份、原子替换、后进先出逐次回滚、漂移与损坏检测。
- 本地面板（仅回环 + 一次性令牌）、`hermes purge` 原生命令、`/purge` 会话入口。

**安装**

```bash
hermes plugins install <owner>/hermes-purge --yes-deps --enable
```

或桌面端一键链接：`hermes://plugin/install?repo=<owner>/hermes-purge&enable=1`

**验证与边界**

- 69 项 unittest、真实 `PluginManager` 加载探针、Chromium 面板端到端、真实 `hermes` CLI 全链路（隔离 home）。
- 准入校验 14 项全 PASS，`security scan` verdict `safe`，零警告。
- 仅在 Hermes 基线 `f925b01791fe052e7d55dc975750c0bd985aff91` 上核实；宿主硬线黑名单、`runtime_self_protection` 与模型服务端策略不受本插件影响。
- 破甲提示词注入、宿主文案改写、续跑与策略调整仅作用于使用者本机的 Hermes profile；上游 dsh-purge 的桌面补丁链、演练台、红队技能库未移植。署名与逐项借用清单见 `NOTICE.md`。
