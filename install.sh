#!/usr/bin/env bash
# hermes-purge one-command installer (macOS / Linux).
#
#   bash install.sh --repo luol75569-collab/hermes-purge
#   curl -fsSLo install.sh https://raw.githubusercontent.com/luol75569-collab/hermes-purge/master/install.sh
#   bash install.sh --repo luol75569-collab/hermes-purge
#
# The script only drives Hermes' own `hermes plugins install`; it never patches the
# Hermes checkout and never writes outside the selected profile home.
set -euo pipefail

REPO="${HERMES_PURGE_REPO:-}"
REF="${HERMES_PURGE_REF:-}"
HOME_DIR="${HERMES_HOME:-}"
ENABLE=1
FORCE=0

usage() {
  cat <<'EOF'
用法: install.sh [--repo luol75569-collab/hermes-purge] [--ref <40位commit SHA>] [--home <HERMES_HOME>]
                 [--no-enable] [--force]

  --repo      GitHub 仓库或完整 Git URL；在仓库目录内运行时可自动从 origin 推断
  --ref       固定到某个 40 位 commit SHA（可复现安装）
  --home      指定要安装到的 profile home（等价于设置 HERMES_HOME）
  --no-enable 装完不自动启用（想先 doctor 检查时用）
  --force     覆盖已安装的同源副本
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --repo) REPO="${2:?--repo 需要值}"; shift 2 ;;
    --ref) REF="${2:?--ref 需要值}"; shift 2 ;;
    --home) HOME_DIR="${2:?--home 需要值}"; shift 2 ;;
    --no-enable) ENABLE=0; shift ;;
    --force) FORCE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "未知参数: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [ -z "$REPO" ]; then
  here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  REPO="$(git -C "$here" remote get-url origin 2>/dev/null || true)"
fi
if [ -z "$REPO" ]; then
  echo "缺少仓库地址：加 --repo luol75569-collab/hermes-purge，或设置 HERMES_PURGE_REPO" >&2
  exit 2
fi

command -v hermes >/dev/null 2>&1 || {
  echo "找不到 hermes CLI。先装 Hermes 本体，并确保 hermes 在 PATH 上。" >&2; exit 3; }
command -v git >/dev/null 2>&1 || {
  echo "找不到 git：hermes plugins install 需要 clone 仓库。" >&2; exit 3; }

args=(plugins install "$REPO" --yes-deps)
[ -n "$REF" ] && args+=(--ref "$REF")
[ "$FORCE" = 1 ] && args+=(--force)
if [ "$ENABLE" = 1 ]; then args+=(--enable); else args+=(--no-enable); fi

echo "→ hermes ${args[*]}"
if [ -n "$HOME_DIR" ]; then
  HERMES_HOME="$HOME_DIR" hermes "${args[@]}"
else
  hermes "${args[@]}"
fi

cat <<EOF

✓ hermes-purge 已安装${REF:+（已固定到 ${REF}）}。

接下来：
  1. 完全退出 Hermes（含托盘）再打开，让它加载插件
  2. 新开一个会话，运行：hermes purge armor      # 看加密提示词套与改写规则表
  3. 确认后再应用破甲预设：hermes purge apply --preset armor
  4. 想撤销：hermes purge revert（配置） / hermes plugins disable hermes-purge（整体停用）
EOF
