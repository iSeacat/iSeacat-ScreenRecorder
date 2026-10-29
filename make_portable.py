# -*- coding: utf-8 -*-
"""
make_portable.py —— 一键把本工具打包成「免安装便携版」

做三件事：
1. 找到本机 Python 3.13 基础安装，整体复制到 runtime/python/
2. 把运行依赖 (bettercam / opencv-python-headless / numpy / comtypes)
   用 pip 装进 runtime/python/Lib/site-packages/
3. 准备 FFmpeg：优先复用本机已装的（WinGet / PATH），
   否则从 gyan.dev 下载 essentials 构建并解压出 ffmpeg.exe 到 runtime/ffmpeg/

完成后整个文件夹可复制到其他 Windows 10/11 x64 电脑，
双击「启动录屏工具.bat」即可运行，目标机零安装。
"""
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.join(ROOT, "runtime")
PY_DIR = os.path.join(RUNTIME, "python")
FF_DIR = os.path.join(RUNTIME, "ffmpeg")
PACKAGES = ["bettercam", "opencv-python-headless", "numpy", "comtypes"]
FFMPEG_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"


def find_base_python():
    """定位一个 Python 3.13 基础安装（非 venv）。"""
    # 1) py 启动器
    for probe in (["py", "-3.13", "-c", "import sys;print(sys.base_prefix)"],
                  [sys.executable, "-c", "import sys;print(sys.base_prefix)"]):
        try:
            out = subprocess.run(probe, capture_output=True, text=True,
                                 timeout=20).stdout.strip()
            if out and os.path.isdir(os.path.join(out, "Lib")) \
                    and sys.version_info[:2] == (3, 13):
                return out
        except Exception:
            pass
    # 2) 常见安装路径
    local = os.getenv("LOCALAPPDATA") or ""
    for cand in (os.path.join(local, "Programs", "Python", "Python313"),
                 r"C:\Program Files\Python313", r"C:\Python313"):
        if os.path.isdir(os.path.join(cand, "Lib")):
            return cand
    raise SystemExit("[x] 未找到 Python 3.13 基础安装，请先安装："
                     "https://www.python.org/downloads/")


def step_copy_python():
    src = find_base_python()
    print("[1/3] 复制 Python 基础安装 -> %s" % PY_DIR)
    if os.path.exists(os.path.join(PY_DIR, "pythonw.exe")):
        print("      已存在，跳过")
        return
    shutil.copytree(src, PY_DIR, dirs_exist_ok=True)


def step_install_packages():
    print("[2/3] 安装依赖包到 runtime site-packages")
    target = os.path.join(PY_DIR, "Lib", "site-packages")
    cmd = [os.path.join(PY_DIR, "python.exe"), "-m", "pip", "install",
           "--target", target, "--upgrade"] + PACKAGES
    subprocess.run(cmd, check=True)


def step_prepare_ffmpeg():
    print("[3/3] 准备 FFmpeg")
    dst = os.path.join(FF_DIR, "ffmpeg.exe")
    if os.path.exists(dst):
        print("      已存在，跳过")
        return
    # 优先复用本机已有的 ffmpeg
    import shutil as _sh
    found = _sh.which("ffmpeg")
    if not found:
        cand = os.path.join(os.getenv("LOCALAPPDATA") or "",
                            "Microsoft", "WinGet", "Links", "ffmpeg.exe")
        found = cand if os.path.exists(cand) else None
    if found:
        os.makedirs(FF_DIR, exist_ok=True)
        shutil.copy(found, dst)
        print("      复制本机 FFmpeg: %s" % found)
        return
    # 否则下载 essentials 构建（约 80MB）
    print("      下载 %s（约 80MB）..." % FFMPEG_URL)
    zpath = os.path.join(RUNTIME, "ffmpeg-essentials.zip")
    os.makedirs(RUNTIME, exist_ok=True)
    urllib.request.urlretrieve(FFMPEG_URL, zpath)
    with zipfile.ZipFile(zpath) as z:
        for name in z.namelist():
            if name.endswith("/bin/ffmpeg.exe"):
                with z.open(name) as fsrc, open(dst, "wb") as fdst:
                    shutil.copyfileobj(fsrc, fdst)
                break
    os.remove(zpath)
    print("      已解压 -> %s" % dst)


def main():
    if not (sys.platform == "win32"):
        raise SystemExit("[x] 仅支持 Windows")
    step_copy_python()
    step_install_packages()
    step_prepare_ffmpeg()
    size = 0
    for dp, _, fns in os.walk(RUNTIME):
        for fn in fns:
            size += os.path.getsize(os.path.join(dp, fn))
    print("\n[OK] 便携版就绪：runtime/ 共 %.0f MB" % (size / 1048576))
    print("     整个文件夹可复制到其他电脑，双击「启动录屏工具.bat」运行")


if __name__ == "__main__":
    main()
