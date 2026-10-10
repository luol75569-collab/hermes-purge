#!/usr/bin/env bash
# Publish this checkout to GitHub: fill the account placeholders, create the repository
# (when a token is present), push master and the release tag, and open a Release.
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

ACCOUNT="${REPO%%/*}"
PRIVATE=0
[ "$MODE" = "--private" ] && PRIVATE=1
DRY=0
[ "$MODE" = "--dry-run" ] && DRY=1

TAG="v$(sed -n 's/^version *= *"\([^"]*\)".*/\1/p' pyproject.toml)"
[ -n "$TAG" ] || { echo "读不到 pyproject.toml 里的 version" >&2; exit 2; }
DESCRIPTION="Hermes armor plugin: sealed prompt injection, host-copy rewrites, refusal continuation, reversible config (community port of dsh-purge's approach)"
TOKEN="${GITHUB_TOKEN:-${GH_TOKEN:-}}"
run() { if [ "$DRY" = 1 ]; then echo "[dry-run] $*"; else "$@"; fi; }
push_with_auth() {
  if [ -n "$TOKEN" ]; then
    export GITHUB_TOKEN="$TOKEN"
    run git -c 'credential.helper=!f() { echo username=x-access-token; echo "password=$GITHUB_TOKEN"; }; f' "$@"
  else
    run git "$@"
  fi
}

# ── 1. 把账号填进占位符，推上去就是可直接转发的状态 ─────────────────────────────
if grep -q "<owner>\|OWNER" README.md SHARE.md install.sh install.ps1 2>/dev/null; then
  echo "→ 替换占位符：<owner> / OWNER → $ACCOUNT"
  if [ "$DRY" = 1 ]; then
    echo "[dry-run] 替换 README.md SHARE.md install.sh install.ps1 并提交"
  else
    ACCOUNT="$ACCOUNT" python3 - <<'PY'
import os, pathlib, re
account = os.environ["ACCOUNT"]
share = pathlib.Path("SHARE.md")
lines = [line for line in share.read_text(encoding="utf-8").splitlines(keepends=True)
         if not line.startswith("> **发出去之前**") and not line.startswith("> macOS：")]
text = re.sub(r"\n{3,}", "\n\n", "".join(lines).lstrip("\n"))
share.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
for name in ("README.md", "SHARE.md", "install.sh", "install.ps1"):
    path = pathlib.Path(name)
    path.write_text(path.read_text(encoding="utf-8").replace("<owner>", account).replace("OWNER", account), encoding="utf-8")
print("   done")
PY
    git add -A
    git diff --cached --quiet || git -c user.name="$(git config user.name || echo publish)" \
      -c user.email="$(git config user.email || echo publish@local)" \
      commit -q -m "release: fill repository account placeholders for $REPO"
    echo "   已提交占位符替换"
  fi
else
  echo "→ 占位符已替换过，跳过"
fi

# ── 2. 建库（有 token 时） ────────────────────────────────────────────────────
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
                   "homepage": f"https://github.com/{repo}",
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

# ── 3. 推送 master 与标签 ────────────────────────────────────────────────────
if git remote get-url origin >/dev/null 2>&1; then
  run git remote set-url origin "https://github.com/${REPO}.git"
else
  run git remote add origin "https://github.com/${REPO}.git"
fi

echo "→ 推送 master"
push_with_auth push -u origin master

if git rev-parse -q --verify "refs/tags/$TAG" >/dev/null; then
  echo "→ 标签 $TAG 已存在"
else
  run git tag -a "$TAG" -m "hermes-purge $TAG"
fi
echo "→ 推送标签 $TAG"
push_with_auth push origin "refs/tags/$TAG"

# ── 4. Release（有 token 且有 release-notes.md 时） ──────────────────────────
if [ -n "$TOKEN" ] && [ -f release-notes.md ]; then
  echo "→ 创建 Release $TAG"
  if [ "$DRY" = 1 ]; then
    echo "[dry-run] POST https://api.github.com/repos/$REPO/releases {\"tag_name\":\"$TAG\"}"
  else
    REPO="$REPO" TAG="$TAG" TOKEN="$TOKEN" python3 - <<'PY'
import json, os, urllib.error, urllib.request
token, repo, tag = os.environ["TOKEN"], os.environ["REPO"], os.environ["TAG"]
body = open("release-notes.md", encoding="utf-8").read()
payload = json.dumps({"tag_name": tag, "name": tag, "body": body, "draft": False,
                      "prerelease": False}).encode()
req = urllib.request.Request(f"https://api.github.com/repos/{repo}/releases", data=payload,
                            method="POST",
                            headers={"Authorization": f"Bearer {token}",
                                     "Accept": "application/vnd.github+json",
                                     "User-Agent": "hermes-purge-publish",
                                     "Content-Type": "application/json"})
try:
    with urllib.request.urlopen(req, timeout=60) as r:
        print("   release:", json.load(r).get("html_url"))
except urllib.error.HTTPError as exc:
    detail = exc.read().decode("utf-8", "replace")[:300]
    if exc.code == 422 and "already_exists" in detail:
        print("   Release 已存在，跳过")
    else:
        print(f"   Release 创建失败 HTTP {exc.code}: {detail}")
PY
  fi
fi

cat <<EOF

✓ 发布完成：https://github.com/${REPO}

可以直接转发给对方：
  链接：hermes://plugin/install?repo=${REPO}&enable=1
  命令：hermes plugins install ${REPO} --yes-deps --enable
  说明：把仓库里的 SHARE.md 内容整段发过去（占位符已替换）
EOF
