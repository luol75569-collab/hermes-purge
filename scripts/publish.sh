#!/usr/bin/env bash
# Publish this checkout to GitHub: create the repository (when a token is present),
# point origin at it, push master and the release tag.
#
#   bash scripts/publish.sh <owner>/hermes-purge            # public repo
#   bash scripts/publish.sh <owner>/hermes-purge --private   # private (friends cannot install from it)
#   bash scripts/publish.sh <owner>/hermes-purge --dry-run   # print actions only
#
# Authentication, in order:
#   1. GITHUB_TOKEN / GH_TOKEN in the environment (fine-grained PAT with Contents:write,
#      plus Administration:write when the repo must be created).
#   2. Otherwise your own git credential helper (macOS Keychain / Windows Credential
#      Manager / SSH) — the repository must already exist.
# The token is never written into .git/config and never passed on a command line.
set -euo pipefail

REPO="${1:-}"
MODE="${2:-}"
[ -n "$REPO" ] || { echo "用法: bash scripts/publish.sh <owner>/<repo> [--private|--dry-run]" >&2; exit 2; }
case "$MODE" in ""|--private|--dry-run) ;; *) echo "未知参数: $MODE" >&2; exit 2 ;; esac

PRIVATE=0
[ "$MODE" = "--private" ] && PRIVATE=1
DRY=0
[ "$MODE" = "--dry-run" ] && DRY=1

TAG="v$(sed -n 's/^version *= *"\([^"]*\)".*/\1/p' pyproject.toml)"
[ -n "$TAG" ] || { echo "读不到 pyproject.toml 里的 version" >&2; exit 2; }
DESCRIPTION="Hermes armor plugin: sealed prompt injection, host-copy rewrites, refusal continuation, reversible config (community port of dsh-purge's approach)"

TOKEN="${GITHUB_TOKEN:-${GH_TOKEN:-}}"
run() { if [ "$DRY" = 1 ]; then echo "[dry-run] $*"; else "$@"; fi; }

if [ -n "$TOKEN" ]; then
  echo "→ 建库（已存在则跳过）：$REPO $( [ "$PRIVATE" = 1 ] && echo '(private)' || echo '(public)' )"
  if [ "$DRY" = 1 ]; then
    echo "[dry-run] POST https://api.github.com/user/repos {\"name\":\"${REPO##*/}\",\"private\":$PRIVATE}"
  else
    REPO="$REPO" PRIVATE="$PRIVATE" DESCRIPTION="$DESCRIPTION" TOKEN="$TOKEN" python3 - <<'PY'
import json, os, urllib.error, urllib.request
token, repo = os.environ["TOKEN"], os.environ["REPO"]
name, private, desc = repo.split("/", 1)[1], os.environ["PRIVATE"] == "1", os.environ["DESCRIPTION"]
body = json.dumps({"name": name, "private": private, "description": desc,
                   "has_issues": True, "has_wiki": False, "has_projects": False,
                   "auto_init": False}).encode()
req = urllib.request.Request("https://api.github.com/user/repos", data=body, method="POST",
                            headers={"Authorization": f"Bearer {token}",
                                     "Accept": "application/vnd.github+json",
                                     "User-Agent": "hermes-purge-publish",
                                     "Content-Type": "application/json"})
try:
    with urllib.request.urlopen(req, timeout=60) as r:
        print("   created:", json.load(r).get("full_name"))
except urllib.error.HTTPError as exc:
    detail = exc.read().decode("utf-8", "replace")[:300]
    if exc.code == 422 and "already exists" in detail:
        print("   已存在，继续推送")
    else:
        raise SystemExit(f"建库失败 HTTP {exc.code}: {detail}")
PY
  fi
else
  echo "→ 没有 GITHUB_TOKEN/GH_TOKEN：跳过建库，直接用你本机的 git 凭据推送（远端仓库需已存在）"
fi

if git remote get-url origin >/dev/null 2>&1; then
  run git remote set-url origin "https://github.com/${REPO}.git"
else
  run git remote add origin "https://github.com/${REPO}.git"
fi

echo "→ 推送 master"
if [ -n "$TOKEN" ]; then
  export GITHUB_TOKEN="$TOKEN"
  run git -c 'credential.helper=!f() { echo username=x-access-token; echo "password=$GITHUB_TOKEN"; }; f' \
      push -u origin master
else
  run git push -u origin master
fi

if git rev-parse -q --verify "refs/tags/$TAG" >/dev/null; then
  echo "→ 标签 $TAG 已存在"
else
  run git tag -a "$TAG" -m "hermes-purge $TAG"
fi
echo "→ 推送标签 $TAG"
if [ -n "$TOKEN" ]; then
  export GITHUB_TOKEN="$TOKEN"
  run git -c 'credential.helper=!f() { echo username=x-access-token; echo "password=$GITHUB_TOKEN"; }; f' \
      push origin "refs/tags/$TAG"
else
  run git push origin "refs/tags/$TAG"
fi

cat <<EOF

✓ 发布完成：https://github.com/${REPO}

下一步（把占位符换成真实账号后即可转发）：
  sed -i '' 's/OWNER/${REPO%%/*}/g' SHARE.md README.md    # macOS
  sed -i 's/OWNER/${REPO%%/*}/g' SHARE.md README.md       # Linux
  一键链接：hermes://plugin/install?repo=${REPO}&enable=1
  一行命令：hermes plugins install ${REPO} --yes-deps --enable
EOF
