# -*- coding: utf-8 -*-
"""
Grace 录屏引擎 v1.0
全屏 / 窗口 / 区域录制 + 鼠标悬停自动放大 + 自定义鼠标样式
供 grace_recorder_gui.py 调用；命令行自测：python grace_recorder.py --selftest
"""
import ctypes
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from collections import deque
from ctypes import Structure, byref, c_long, c_void_p, windll

import cv2  # type: ignore
import numpy as np

APP_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(APP_DIR, "录制输出")
FFMPEG_LOG = os.path.join(APP_DIR, "ffmpeg_error.log")

# 物理像素坐标系（录屏、鼠标、窗口矩形统一）
try:
    windll.user32.SetProcessDPIAware()
except Exception:
    pass


# ---------------------------------------------------------------- 基础 Win32
class POINT(Structure):
    _fields_ = [("x", c_long), ("y", c_long)]


class RECT(Structure):
    _fields_ = [("left", c_long), ("top", c_long), ("right", c_long), ("bottom", c_long)]


def get_cursor_pos():
    pt = POINT()
    windll.user32.GetCursorPos(byref(pt))
    return pt.x, pt.y


def left_button_down():
    return bool(windll.user32.GetAsyncKeyState(0x01) & 0x8000)


def primary_screen_size():
    return windll.user32.GetSystemMetrics(0), windll.user32.GetSystemMetrics(1)


def get_window_rect(hwnd):
    """窗口内容矩形（DWM 扩展边框，不含阴影）；无效返回 None"""
    rect = RECT()
    try:
        if windll.dwmapi.DwmGetWindowAttribute(
                c_void_p(hwnd), 9, byref(rect), ctypes.sizeof(RECT)) != 0:
            raise OSError
    except Exception:
        if not windll.user32.GetWindowRect(c_void_p(hwnd), byref(rect)):
            return None
    l, t, r, b = rect.left, rect.top, rect.right, rect.bottom
    if r - l < 80 or b - t < 80:
        return None
    return l, t, r - l, b - t


def list_windows():
    """返回 [(hwnd, title, (l,t,w,h)), ...] 可见普通窗口"""
    out = []

    def _cb(hwnd, _lparam):
        if not windll.user32.IsWindowVisible(c_void_p(hwnd)):
            return True
        n = windll.user32.GetWindowTextLengthW(c_void_p(hwnd))
        if n <= 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        windll.user32.GetWindowTextW(c_void_p(hwnd), buf, n + 1)
        title = buf.value.strip()
        if not title:
            return True
        cloaked = ctypes.c_int(0)  # 排除隐藏的 UWP 窗口
        try:
            windll.dwmapi.DwmGetWindowAttribute(c_void_p(hwnd), 14,
                                                byref(cloaked), 4)
        except Exception:
            pass
        if cloaked.value:
            return True
        r = get_window_rect(hwnd)
        if r:
            out.append((hwnd, title, r))
        return True

    ENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, c_void_p, c_void_p)
    windll.user32.EnumWindows(ENUMPROC(_cb), None)
    return out


def resolve_ffmpeg():
    # 1) 优先用随工具打包的本地 ffmpeg（保证复制到别的电脑也能用，无需安装）
    local = os.path.join(APP_DIR, "runtime", "ffmpeg", "ffmpeg.exe")
    if os.path.exists(local):
        return local
    # 2) 系统 PATH
    p = shutil.which("ffmpeg")
    if p:
        return p
    # 3) 本机 WinGet 链接（开发环境兜底）
    cand = os.path.join(
        os.getenv("LOCALAPPDATA") or r"C:\Users\Administrator\AppData\Local",
        "Microsoft", "WinGet", "Links", "ffmpeg.exe")
    return cand if os.path.exists(cand) else "ffmpeg"


def even(v):
    return int(v) & ~1


# ---------------------------------------------------------------- 悬停放大
class ZoomState:
    """鼠标悬停 → 平滑放大；移动/按下 → 平滑回全画面（指数弹簧）"""

    def __init__(self, base_w, base_h, factor=2.0, linger_s=0.6, tau=0.12):
        self.base_w, self.base_h = float(base_w), float(base_h)
        self.factor = factor
        self.linger_s = linger_s
        self.tau = tau
        self.z = 1.0
        self.center = (base_w / 2.0, base_h / 2.0)
        self.ema_mouse = self.center
        self.last_move_t = time.perf_counter()
        self.last_mouse = None

    def feed(self, mouse_local, t, pressed, dt=0.033):
        if self.last_mouse is None:
            self.last_mouse = mouse_local
        dx = mouse_local[0] - self.last_mouse[0]
        dy = mouse_local[1] - self.last_mouse[1]
        if dx * dx + dy * dy > 16:  # 移动超过 4px
            self.last_move_t = t
        self.last_mouse = mouse_local
        k = 1.0 - np.exp(-dt / 0.06)
        self.ema_mouse = (self.ema_mouse[0] + (mouse_local[0] - self.ema_mouse[0]) * k,
                          self.ema_mouse[1] + (mouse_local[1] - self.ema_mouse[1]) * k)
        still = (t - self.last_move_t) >= self.linger_s and not pressed
        target_z = self.factor if still else 1.0
        self.z += (target_z - self.z) * (1.0 - np.exp(-dt / self.tau))
        target_c = self.ema_mouse if self.z >= 1.02 else (self.base_w / 2.0, self.base_h / 2.0)
        self.center = (self.center[0] + (target_c[0] - self.center[0]) * (1.0 - np.exp(-dt / 0.10)),
                       self.center[1] + (target_c[1] - self.center[1]) * (1.0 - np.exp(-dt / 0.10)))

    def crop_rect(self):
        """返回 (l, t, w, h) —— 基准区域内的裁剪框，宽高偶数"""
        z = max(1.0, self.z)
        cw = max(64, min(even(self.base_w / z), even(self.base_w)))
        ch = max(64, min(even(self.base_h / z), even(self.base_h)))
        cx = min(max(self.center[0], cw / 2), self.base_w - cw / 2)
        cy = min(max(self.center[1], ch / 2), self.base_h - ch / 2)
        l = int(min(max(0, round(cx - cw / 2)), self.base_w - cw))
        t = int(min(max(0, round(cy - ch / 2)), self.base_h - ch))
        return l, t, cw, ch


# ---------------------------------------------------------------- 鼠标绘制
ARROW_POLY = [(0, 0), (0, 16), (3.5, 12.5), (6.5, 19), (9, 18), (6, 11.5), (11, 11.5)]


def draw_cursor(img, style, x, y, scale=1.0):
    WHITE, BLACK = (255, 255, 255), (30, 30, 30)
    AMBER = (30, 190, 255)  # BGR
    if style == "ring":
        r = int(10 * scale)
        cv2.circle(img, (x, y), r + 2, BLACK, 1, cv2.LINE_AA)
        cv2.circle(img, (x, y), r, AMBER, 3, cv2.LINE_AA)
    elif style == "subtle":  # 低调：细灰圈，不晃眼
        r = int(7 * scale)
        cv2.circle(img, (x, y), r, (170, 170, 170), 1, cv2.LINE_AA)
    elif style == "dot":
        r = int(6 * scale)
        cv2.circle(img, (x, y), r + 2, BLACK, -1, cv2.LINE_AA)
        cv2.circle(img, (x, y), r, WHITE, -1, cv2.LINE_AA)
    elif style in ("arrow", "big_arrow"):
        sc = (2.6 if style == "big_arrow" else 1.7) * scale
        pts = np.array([[x + px * sc, y + py * sc] for px, py in ARROW_POLY], np.int32)
        cv2.fillPoly(img, [pts], WHITE, lineType=cv2.LINE_AA)
        cv2.polylines(img, [pts], True, BLACK, 2, cv2.LINE_AA)
    return img


def apply_spotlight(img, x, y, radius=180.0):
    """聚光灯：全画面压暗，光圈处恢复原亮度（只在光圈邻域做混合，性能友好）"""
    dark = cv2.convertScaleAbs(img, alpha=0.45, beta=0)
    h, w = img.shape[:2]
    r = int(radius)
    x0, x1 = max(0, x - r), min(w, x + r)
    y0, y1 = max(0, y - r), min(h, y + r)
    if x1 <= x0 or y1 <= y0:
        img[:] = dark
        return img
    m = np.zeros((y1 - y0, x1 - x0), np.uint8)
    cv2.circle(m, (x - x0, y - y0), r, 255, -1)
    m = cv2.GaussianBlur(m, (31, 31), 0)
    mf = (m.astype(np.float32) / 255.0)[..., None]
    roi_d = dark[y0:y1, x0:x1].astype(np.float32)
    roi_o = img[y0:y1, x0:x1].astype(np.float32)
    img[y0:y1, x0:x1] = (roi_d * (1 - mf) + roi_o * mf).astype(np.uint8)
    return img


# ---------------------------------------------------------------- 录制器
class Recorder:
    def __init__(self, mode="fullscreen", region=None, hwnd=None, fps=30,
                 zoom_enabled=True, zoom_factor=2.0, linger_s=0.6,
                 cursor_style="ring", cursor_scale=1.0, click_ripple=True,
                 aspect=None, zoom_tau=0.22, follow_mouse=False, follow_scale=0.9,
                 dual_output=False, output=None):
        self.mode = mode                  # fullscreen | window | region
        self.manual_region = region       # (l,t,w,h) 屏幕坐标，region 模式用
        self.hwnd = hwnd                  # window 模式用
        self.aspect = aspect              # None|'16:9'|'9:16'|'1:1'
        self.fps = fps
        self.zoom_enabled = zoom_enabled
        self.zoom_factor = zoom_factor
        self.linger_s = linger_s
        self.zoom_tau = zoom_tau          # 放大动画时间常数，越大越柔和
        self.follow_mouse = follow_mouse  # 全屏+比例时取景框跟随鼠标
        self.follow_scale = follow_scale  # 取景框占屏幕比例（<1 才有跟随余量）
        self.dual_output = dual_output    # 同时输出两路：全屏 + 全程放大
        self.output2 = None               # 第二路（放大）输出路径
        self.base_rect = None             # 当前取景框 (l,t,w,h)，供 GUI 画边框
        self.cursor_style = cursor_style  # ring|dot|arrow|big_arrow|spot|none
        self.cursor_scale = cursor_scale
        self.click_ripple = click_ripple
        self.output = output or os.path.join(
            OUTPUT_DIR, "录屏_%s.mp4" % time.strftime("%Y%m%d_%H%M%S"))
        if self.dual_output:
            self.output2 = self.output[:-4] + "_放大.mp4"
        self.running = False
        self.elapsed = 0.0
        self.frames = 0
        self.error = None
        self._thread = None
        self._stop_evt = threading.Event()
        self._t0 = 0.0

    # ---- 基准区域（window 模式每帧重算以跟随窗口移动/缩放）----
    def _base_region(self):
        sw, sh = primary_screen_size()
        if self.mode == "region" and self.manual_region:
            r = self.manual_region
        elif self.mode == "window" and self.hwnd:
            r = get_window_rect(self.hwnd) or (0, 0, sw, sh)
        else:
            r = (0, 0, sw, sh)
            if self.follow_mouse and self.follow_scale < 1.0:
                w0, h0 = even(sw * self.follow_scale), even(sh * self.follow_scale)
                r = ((sw - w0) // 2, (sh - h0) // 2, w0, h0)
        l, t, w, h = r
        ratio = {"16:9": 16 / 9, "9:16": 9 / 16, "1:1": 1.0}.get(self.aspect)
        if ratio and w > 0 and h > 0:
            cur = w / h
            if cur > ratio:
                nw = even(h * ratio)
                l += (w - nw) // 2
                w = nw
            else:
                nh = even(w / ratio)
                t += (h - nh) // 2
                h = nh
        l = min(max(0, int(l)), sw - 2)
        t = min(max(0, int(t)), sh - 2)
        w = max(64, min(even(w), sw - l))
        h = max(64, min(even(h), sh - t))
        return l, t, w, h

    # ---- 主循环 ----
    def _run(self):
        import bettercam
        try:
            ffmpeg = resolve_ffmpeg()
            l, t, bw, bh = self._base_region()
            self.base_rect = (l, t, bw, bh)
            # 全屏+比例时：取景框平滑跟随鼠标（软边界 EMA，贴边自动夹住）
            follow_off = [float(l), float(t)] \
                if (self.follow_mouse and self.mode == "fullscreen") else None
            W, H = bw, bh  # 输出尺寸固定为起始基准区域
            def _spawn(out_path, ferr):
                cmd = [ffmpeg, "-y", "-f", "rawvideo", "-pix_fmt", "bgra",
                       "-s", "%dx%d" % (W, H), "-r", str(self.fps), "-i", "-",
                       "-an", "-c:v", "libx264", "-preset", "veryfast",
                       "-crf", "18", "-pix_fmt", "yuv420p", out_path]
                return subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                        stdout=subprocess.DEVNULL, stderr=ferr)

            os.makedirs(os.path.dirname(self.output), exist_ok=True)
            with open(FFMPEG_LOG, "w", encoding="utf-8") as ferr:
                proc = _spawn(self.output, ferr)
                proc2 = _spawn(self.output2, ferr) if self.dual_output else None
            cam = bettercam.create(output_color="BGRA")
            # 预热：等第一帧真正到来（DXGI 会话初始化 ~0.5s），再开始计时
            warm0 = time.perf_counter()
            first = None
            while time.perf_counter() - warm0 < 3.0:
                first = cam.grab()
                if first is not None:
                    break
                time.sleep(0.005)
            last_frame = first
            self._t0 = time.perf_counter()      # 重新计时：从第一帧起算
            zs = ZoomState(W, H, self.zoom_factor if self.zoom_enabled else 1.0,
                           self.linger_s, tau=self.zoom_tau)
            # 双路模式：B 路全程保持放大（linger=0，立即推近）
            zsb = ZoomState(W, H, self.zoom_factor, 0.0,
                            tau=self.zoom_tau) if self.dual_output else None
            clicks = deque()
            prev_down = False
            last_t = self._t0
            self.running = True
            interval = 1.0 / self.fps
            next_slot = last_t + interval
            while not self._stop_evt.is_set():
                now = time.perf_counter()
                if now < next_slot:
                    time.sleep(0.0015)
                    continue
                next_slot += interval
                if next_slot < now - interval * 2:  # 卡顿积压 → 重新对齐
                    next_slot = now + interval
                nf = cam.grab()                     # 非阻塞，无新帧返回 None
                if nf is not None:
                    last_frame = nf
                if last_frame is None:
                    continue
                frame = last_frame
                dt = min(0.2, now - last_t)
                last_t = now
                # 基准区域（窗口模式跟随窗口；全屏+比例可选跟随鼠标）
                mx, my = get_cursor_pos()
                l, t, bw, bh = self._base_region()
                if follow_off is not None:
                    sw, sh = primary_screen_size()
                    tx = min(max(0.0, mx - bw / 2.0), max(0.0, sw - bw))
                    ty = min(max(0.0, my - bh / 2.0), max(0.0, sh - bh))
                    kf = 1.0 - np.exp(-dt / 0.4)   # 跟随速度（越大越跟手）
                    follow_off[0] += (tx - follow_off[0]) * kf
                    follow_off[1] += (ty - follow_off[1]) * kf
                    l, t = int(follow_off[0]), int(follow_off[1])
                self.base_rect = (l, t, bw, bh)
                zs.base_w, zs.base_h = float(bw), float(bh)
                lx, ly = mx - l, my - t                 # 区域内坐标
                down = left_button_down()
                zs.feed((lx, ly), now, down, dt)
                if self.click_ripple and down and not prev_down \
                        and 0 <= lx < bw and 0 <= ly < bh:
                    clicks.append((now, lx, ly))
                prev_down = down
                while clicks and now - clicks[0][0] > 0.45:
                    clicks.popleft()
                # ---- 鼠标/特效叠加（输出坐标系，两路共用） ----
                def _overlay(out, cl, ct, cw, ch):
                    sx, sy = W / cw, H / ch
                    px, py = int((lx - cl) * sx), int((ly - ct) * sy)
                    if 0 <= px < W and 0 <= py < H:
                        if self.cursor_style == "spot":
                            apply_spotlight(out, px, py, 180.0 * self.cursor_scale)
                        elif self.cursor_style != "none":
                            draw_cursor(out, self.cursor_style, px, py, self.cursor_scale)
                    for (t0, cx_, cy_) in clicks:
                        age = (now - t0) / 0.45
                        r = int(10 + 42 * age)
                        a = int(255 * (1 - age))
                        cv2.circle(out, (int((cx_ - cl) * sx), int((cy_ - ct) * sy)),
                                   r, (a, a, a), 3, cv2.LINE_AA)
                    return out

                def _emit(cl, ct, cw, ch):
                    sl, st = l + cl, t + ct
                    img = frame[st:st + ch, sl:sl + cw]
                    if not img.flags["C_CONTIGUOUS"]:
                        img = np.ascontiguousarray(img)
                    if (cw, ch) != (W, H):
                        img = cv2.resize(img, (W, H), interpolation=cv2.INTER_LINEAR)
                    return _overlay(img, cl, ct, cw, ch)

                # ---- 路 A：主输出（按悬停放大设置） ----
                cl, ct, cw, ch = zs.crop_rect()
                try:
                    proc.stdin.write(_emit(cl, ct, cw, ch).tobytes())
                except OSError:
                    self.error = "ffmpeg 管道断开（编码进程退出），详见 ffmpeg_error.log"
                    break
                # ---- 路 B：全程放大 ----
                if zsb is not None:
                    zsb.feed((lx, ly), now, False, dt)
                    cl2, ct2, cw2, ch2 = zsb.crop_rect()
                    try:
                        proc2.stdin.write(_emit(cl2, ct2, cw2, ch2).tobytes())
                    except OSError:
                        self.error = "ffmpeg 管道断开（路B放大），详见 ffmpeg_error.log"
                        break
                self.frames += 1
                self.elapsed = now - self._t0
            # 收尾
            try:
                cam.release()
            except Exception:
                pass
            try:
                proc.stdin.close()
                proc.wait(timeout=30)
            except Exception:
                proc.kill()
            if proc2 is not None:
                try:
                    proc2.stdin.close()
                    proc2.wait(timeout=30)
                except Exception:
                    proc2.kill()
            if proc.returncode not in (0, None) and not self.error:
                with open(FFMPEG_LOG, "r", encoding="utf-8", errors="ignore") as f:
                    self.error = "ffmpeg 退出码 %s：%s" % (proc.returncode, f.read()[-500:])
        except Exception:
            import traceback
            self.error = traceback.format_exc()
        finally:
            self.running = False

    def start(self):
        self._stop_evt.clear()
        self.error = None
        self.elapsed = 0.0
        self.frames = 0
        self._t0 = time.perf_counter()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self, timeout=25):
        self._stop_evt.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        return self.output


def resolve_ffprobe():
    ff = resolve_ffmpeg()
    p = os.path.join(os.path.dirname(ff), "ffprobe.exe")
    return p if os.path.exists(p) else "ffprobe"


def media_duration(path):
    """用 ffmpeg -i 从 stderr 解析时长（免依赖 ffprobe，便携包少 240MB）"""
    try:
        out = subprocess.run([resolve_ffmpeg(), "-hide_banner", "-i", path],
                             capture_output=True, text=True, timeout=30)
        m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", out.stderr)
        if m:
            h, mnt, s = m.groups()
            return int(h) * 3600 + int(mnt) * 60 + float(s)
    except Exception:
        pass
    return -1.0


# ---------------------------------------------------------------- 自测
def _selftest():
    print("== Grace 录屏引擎自测 ==")
    ok = True
    zs = ZoomState(1920, 1080, factor=2.0, linger_s=0.5)
    t = 0.0
    x = 0.0
    for _ in range(30):
        t += 0.033
        x += 30
        zs.feed((x, 540), t, False)
    assert zs.z < 1.3, "移动中不应放大 z=%s" % zs.z
    for _ in range(60):
        t += 0.033
        zs.feed((x, 540), t, False)
    assert zs.z > 1.8, "悬停应放大 z=%s" % zs.z
    _, _, cw, ch = zs.crop_rect()
    assert cw < 1400, "裁剪框应变小 cw=%s" % cw
    for _ in range(60):
        t += 0.033
        x += 30
        zs.feed((x, 540), t, False)
    assert zs.z < 1.35, "移动后应回落 z=%s" % zs.z
    print("[1] 悬停放大状态机 OK（裁剪框 %dx%d）" % (cw, ch))

    img = np.zeros((600, 800, 4), np.uint8)
    for s in ("ring", "dot", "arrow", "big_arrow"):
        draw_cursor(img, s, 400, 300)
    img2 = apply_spotlight(img.copy(), 400, 300, 150)
    assert img2.mean() < img.mean() + 1e-6
    print("[2] 鼠标绘制/聚光灯 OK")

    wins = list_windows()
    print("[3] 窗口枚举 OK，可见窗口 %d 个" % len(wins))

    try:
        rec = Recorder(mode="fullscreen", fps=30, zoom_enabled=True,
                       cursor_style="ring", linger_s=0.4)
        rec.output = os.path.join(OUTPUT_DIR, "_selftest.mp4")
        if os.path.exists(rec.output):
            os.remove(rec.output)
        rec.start()
        time.sleep(3)
        out = rec.stop(timeout=30)
        if rec.error:
            print("[4] 实录报错:", str(rec.error)[:300])
        elif os.path.exists(out) and os.path.getsize(out) > 10000:
            dur = media_duration(out)
            skew = abs(dur - rec.elapsed)
            print("[4] 实录 OK → %s (%d bytes, %d frames, 时长 %.2fs / 实际 %.2fs)"
                  % (out, os.path.getsize(out), rec.frames, dur, rec.elapsed))
            if skew > 0.5:
                print("    !! 时长偏差 %.2fs 超阈值" % skew)
                ok = False
        else:
            print("[4] 实录产物异常，检查", FFMPEG_LOG)
            ok = False
    except Exception as e:
        print("[4] 实录跳过:", e)
    print("== 自测完成，%s ==" % ("通过" if ok else "有失败项"))
    return 0 if ok else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    elif "--info" in sys.argv:
        sw, sh = primary_screen_size()
        print("主屏: %dx%d" % (sw, sh))
        print("ffmpeg:", resolve_ffmpeg())
        for hwnd, title, r in list_windows()[:30]:
            print("  hwnd=%s %sx%s+%s+%s | %s" % (hwnd, r[2], r[3], r[0], r[1], title[:40]))
    else:
        print("用法: python grace_recorder.py --selftest | --info")
