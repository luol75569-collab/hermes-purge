# hermes-purge one-command installer (Windows PowerShell 5.1+ / PowerShell 7+).
#
#   irm https://raw.githubusercontent.com/<owner>/hermes-purge/master/install.ps1 -OutFile install.ps1
#   .\install.ps1 -Repo <owner>/hermes-purge
#
# The script only drives Hermes' own `hermes plugins install`; it never patches the
# Hermes checkout and never writes outside the selected profile home.
[CmdletBinding()]
param(
    [string]$Repo = $env:HERMES_PURGE_REPO,
    [string]$Ref = $env:HERMES_PURGE_REF,
    [string]$HomePath = $env:HERMES_HOME,
    [switch]$NoEnable,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'

$usage = @'
用法: install.ps1 [-Repo <owner>/hermes-purge] [-Ref <40位commit SHA>] [-HomePath <HERMES_HOME>]
                  [-NoEnable] [-Force]

  -Repo GitHub 仓库或完整 Git URL；在仓库目录内运行时可自动从 origin 推断
  -Ref  固定到某个 40 位 commit SHA（可复现安装）
  -HomePath 指定要安装到的 profile home（等价于设置 HERMES_HOME）
  -NoEnable 装完不自动启用（想先 doctor 检查时用）
  -Force 覆盖已安装的同源副本
'@

if (-not $Repo) {
    try {
        $scriptRoot = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
        if (Test-Path (Join-Path $scriptRoot '.git')) {
            $Repo = (git -C $scriptRoot remote get-url origin)
        }
    } catch {
        $Repo = $null
    }
}
if (-not $Repo) {
    Write-Host $usage
    throw "缺少仓库地址：加 -Repo <owner>/hermes-purge，或设置环境变量 HERMES_PURGE_REPO"
}

if (-not (Get-Command hermes -ErrorAction SilentlyContinue)) {
    throw "找不到 hermes CLI。先装 Hermes 本体，并确保 hermes 在 PATH 上。"
}
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "找不到 git：hermes plugins install 需要 clone 仓库（装 Git for Windows 后重开 PowerShell）。"
}

$hermesArgs = @('plugins', 'install', $Repo, '--yes-deps')
if ($Ref) { $hermesArgs += @('--ref', $Ref) }
if ($Force) { $hermesArgs += '--force' }
$hermesArgs += if ($NoEnable) { '--no-enable' } else { '--enable' }

Write-Host ("→ hermes " + ($hermesArgs -join ' '))
if ($HomePath) { $env:HERMES_HOME = $HomePath }
& hermes @hermesArgs
if ($LASTEXITCODE -ne 0) { throw "hermes plugins install 失败（exit $LASTEXITCODE）" }

Write-Host @"

✓ hermes-purge 已安装$(if ($Ref) { "（已固定到 ${Ref}）" })。

接下来：
  1. 完全退出 Hermes（含托盘）再打开，让它加载插件
  2. 新开一个会话，运行：hermes purge armor      # 看加密提示词套与改写规则表
  3. 确认后再应用破甲预设：hermes purge apply --preset armor
  4. 想撤销：hermes purge revert（配置） / hermes plugins disable hermes-purge（整体停用）
"@
