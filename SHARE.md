# Hermes Purge 安装（发给对方照做即可）

> **发出去之前**：把本文所有 `OWNER` 换成你的 GitHub 账号或仓库所属账号。
> macOS：`sed -i '' 's/OWNER/你的账号/g' SHARE.md`　Linux：`sed -i 's/OWNER/你的账号/g' SHARE.md`　Windows：`(Get-Content SHARE.md) -replace 'OWNER','你的账号' | Set-Content SHARE.md`

**前置**：机器上有 Hermes（桌面端或 CLI 任一），并且 `git` 在 PATH（`git --version` 有输出；Windows 装 Git for Windows）。全新装好的 Hermes 第一次装插件会先准备自己的依赖环境，需要联网，可能等几分钟。

## 方式 1：点链接（装了 Hermes 桌面端就选这个）

```
hermes://plugin/install?repo=OWNER/hermes-purge&enable=1
```

点开后会弹出确认框（显示仓库、安装前提示、GitHub 浏览/克隆链接），勾选组件再确认——它不会静默安装。

聊天软件有时会吞掉自定义协议：链接点不动就复制到浏览器地址栏回车，或存成一个 `.html`/`.url` 文件双击打开。

## 方式 2：PowerShell 一行（CLI 用户，或链接被吞时）

```powershell
hermes plugins install OWNER/hermes-purge --yes-deps --enable
```

要可复现（固定到某个提交）就加 `--ref <40位commit SHA>`；先装后验用 `--no-enable`。

## 方式 3：一键脚本（自查前置、失败会直接报错）

```powershell
irm https://raw.githubusercontent.com/OWNER/hermes-purge/master/install.ps1 -OutFile $env:TEMP\install.ps1
& $env:TEMP\install.ps1 -Repo OWNER/hermes-purge
```

macOS / Linux：

```bash
curl -fsSL https://raw.githubusercontent.com/OWNER/hermes-purge/master/install.sh | bash -s -- --repo OWNER/hermes-purge
```

## 方式 4：整段复制给对方的 AI 助手

> 请帮我核对并安装 Hermes 插件 hermes-purge，仓库 `OWNER/hermes-purge`，版本 0.2.0。
>
> 先检查环境：`hermes --version`；`hermes plugins list --user` 看目标 profile 是否已有同名插件；确认 `git` 可用；多 profile 时用 `hermes -p <name>` 或 `HERMES_HOME` 指定目标 profile，不要装错 home。
>
> 安装：`hermes plugins install OWNER/hermes-purge --yes-deps --no-enable`
> 再用 `hermes plugins doctor hermes-purge` 核对：必须报 manifest `hermes-purge 0.2.0`、`runtime discovery, manifest parsing, import, and registration passed`、`3 tool(s), 2 hook(s)`。不要用同名插件、其它版本或其它仓库替代。
>
> 通过后 `hermes plugins enable hermes-purge`，完全退出并重开目标 profile，再验证 `hermes plugins list --user`、`hermes purge armor`、`hermes purge status`。任何一步不符或环境不满足，先说明原因再继续。

## 装完验证（三条都过才算成功）

```bash
hermes plugins list --user
hermes plugins doctor hermes-purge   # 期望：hermes-purge 0.2.0；registration passed；3 tool(s), 2 hook(s)
hermes purge armor                   # 期望：列出 3 套密封提示词套 + 改写规则表
```

然后**完全退出 Hermes（含托盘）再打开**，新开一个会话。想启用破甲再单独执行一次：

```bash
hermes purge apply --preset armor
```

## 撤销

```bash
hermes purge revert                  # 只回滚配置（每次回滚一层）
hermes plugins disable hermes-purge  # 整体停用，保留文件
hermes plugins remove hermes-purge   # 彻底移除
```

## 这是什么

Hermes 版破甲插件：加密破甲提示词注入、宿主拦截文案改写、拒答续跑，外加提示词与配置的可回滚管理（预览差异、SHA256 备份、逐次回滚、本地控制面板）。

`armor` 预设会写 `approvals.mode=off`，也就是关闭 Hermes 的常规审批。**只在自己有权管理的机器上装。** 来源与署名见仓库 [NOTICE.md](NOTICE.md)，实现边界与已知差异见 [README](README.md)。
