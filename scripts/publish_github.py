#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
publish_github.py —— 通过 GitHub REST API 发布本仓库
（适用于 git 协议被网络拦截、但 api.github.com 可用的环境）

用法：
  GITHUB_TOKEN=ghp_xxx python scripts/publish_github.py                 # 建/更新仓库并推送代码
  GITHUB_TOKEN=ghp_xxx python scripts/publish_github.py --release FILE  # 创建 Release 并上传附件
"""
import base64
import datetime
import json
import os
import sys
import urllib.error
import urllib.request

OWNER = "Grace-Yeah"
REPO = "iSeacat-ScreenRecorder"
BRANCH = "main"
API = "https://api.github.com"
UPLOADS = "https://uploads.github.com"
TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TAG = "v1.5"

DESCRIPTION = ("免费开源的 Screen Studio 替代 | Windows 录屏工具：鼠标悬停自动放大、"
               "自定义鼠标样式、点击涟漪、9:16/16:9、双路输出 | 便携免安装")

SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", "runtime", "_release", "录制输出"}
SKIP_EXT = {".pyc", ".log", ".zip"}


def api(method, path, payload=None, raw=None, ctype="application/json"):
    url = path if path.startswith("http") else API + path
    data = raw if raw is not None else (
        json.dumps(payload).encode() if payload is not None else None)
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", "Bearer " + TOKEN)
    req.add_header("Accept", "application/vnd.github+json")
    if data is not None:
        req.add_header("Content-Type", ctype)
    try:
        with urllib.request.urlopen(req) as r:
            body = r.read()
            ct = r.headers.get("Content-Type", "")
            return r.status, (json.loads(body) if body and "json" in ct else {})
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:600]


def ensure_repo():
    st, res = api("GET", "/repos/%s/%s" % (OWNER, REPO))
    if st == 200:
        print("[repo] 已存在:", res.get("html_url"))
        return True
    st, res = api("POST", "/user/repos", {
        "name": REPO, "description": DESCRIPTION, "private": False,
        "has_wiki": False, "has_projects": False})
    if st in (201, 202):
        print("[repo] 已创建:", res.get("html_url"))
        return True
    print("[repo] 创建失败 %s: %s" % (st, res))
    return False


def collect_files():
    out = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        rel = os.path.relpath(dirpath, ROOT)
        head = rel.split(os.sep)[0]
        if head in SKIP_DIRS or "__pycache__" in dirpath:
            dirnames[:] = []
            continue
        for fn in filenames:
            if os.path.splitext(fn)[1].lower() in SKIP_EXT:
                continue
            out.append(os.path.join(dirpath, fn))
    return sorted(out)


def push_code():
    files = collect_files()
    print("[push] 共 %d 个文件" % len(files))
    items = []
    for fp in files:
        rel = os.path.relpath(fp, ROOT).replace("\\", "/")
        with open(fp, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        st, res = api("POST", "/repos/%s/%s/git/blobs" % (OWNER, REPO),
                      {"content": b64, "encoding": "base64"})
        if st != 201:
            print("  [x] blob 失败 %s: %s %s" % (rel, st, res))
            return False
        items.append({"path": rel, "mode": "100644", "type": "blob",
                      "sha": res["sha"]})
        print("  blob %-40s %6.1f KB" % (rel, len(b64) * 3 / 4 / 1024))
    st, res = api("POST", "/repos/%s/%s/git/trees" % (OWNER, REPO),
                  {"tree": items})
    if st != 201:
        print("[x] tree 失败 %s: %s" % (st, res))
        return False
    tree_sha = res["sha"]
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    ident = {"name": OWNER, "email": "378164305@qq.com", "date": now}
    st, res = api("POST", "/repos/%s/%s/git/commits" % (OWNER, REPO), {
        "message": "Initial release: iSeacat ScreenRecorder v1.5 (portable)",
        "tree": tree_sha, "author": ident, "committer": ident})
    if st != 201:
        print("[x] commit 失败 %s: %s" % (st, res))
        return False
    commit_sha = res["sha"]
    st, ref = api("GET", "/repos/%s/%s/git/ref/heads/%s" % (OWNER, REPO, BRANCH))
    if st == 200:
        st, res = api("PATCH",
                      "/repos/%s/%s/git/refs/heads/%s" % (OWNER, REPO, BRANCH),
                      {"sha": commit_sha})
    else:
        st, res = api("POST", "/repos/%s/%s/git/refs" % (OWNER, REPO),
                      {"ref": "refs/heads/%s" % BRANCH, "sha": commit_sha})
    if st not in (200, 201):
        print("[x] ref 失败 %s: %s" % (st, res))
        return False
    print("[push] 完成 commit=%s" % commit_sha[:10])
    return True


def make_release(asset):
    body = ("## 便携版 v%s\n\n"
            "- 解压后双击「启动录屏工具.bat」即可使用（免安装，自带 Python + FFmpeg）\n"
            "- 要求 Windows 10/11 64 位\n"
            "- 详见 README\n" % TAG[1:])
    st, res = api("GET", "/repos/%s/%s/releases/tags/%s" % (OWNER, REPO, TAG))
    if st == 200:
        rel_id, upload_url = res["id"], res["upload_url"].split("{")[0]
        print("[release] 已存在 tag %s" % TAG)
    else:
        st, res = api("POST", "/repos/%s/%s/releases" % (OWNER, REPO), {
            "tag_name": TAG, "target_commitish": BRANCH,
            "name": "便携版 %s" % TAG, "body": body})
        if st != 201:
            print("[x] release 失败 %s: %s" % (st, res))
            return False
        rel_id = res["id"]
        upload_url = res["upload_url"].split("{")[0]
        print("[release] 已创建 tag %s" % TAG)
    name = os.path.basename(asset)
    size = os.path.getsize(asset)
    print("[release] 上传 %s (%.0f MB)..." % (name, size / 1048576))
    with open(asset, "rb") as f:
        raw = f.read()
    st, res = api("POST", "%s?name=%s" % (upload_url, urllib.request.quote(name)),
                  raw=raw, ctype="application/zip")
    if st != 201:
        print("[x] 附件上传失败 %s: %s" % (st, res))
        return False
    print("[release] 附件上传完成:", res.get("browser_download_url"))
    return True


def main():
    if not TOKEN:
        raise SystemExit("[x] 请设置环境变量 GITHUB_TOKEN")
    if "--release" in sys.argv:
        asset = sys.argv[sys.argv.index("--release") + 1]
        sys.exit(0 if make_release(asset) else 1)
    if not ensure_repo():
        sys.exit(1)
    sys.exit(0 if push_code() else 1)


if __name__ == "__main__":
    main()
