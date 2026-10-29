# -*- coding: utf-8 -*-
"""
Grace 录屏工具 GUI v1.0
功能：全屏/窗口/区域录制、16:9 与手机 9:16 比例、鼠标悬停自动放大、
     自定义鼠标样式、点击涟漪、倒计时、全局停止热键 Ctrl+Shift+X
运行：项目 .venv 下的 pythonw.exe（双击 启动录屏工具.bat）
"""
import ctypes
import os
import queue
import subprocess
import sys
import threading
import time
import traceback

import grace_recorder as eng

# DPI 感知必须在创建 Tk 之前
try:
    ctypes.windll.user32.SetProcessDPIAware()
except Exception:
    pass

import tkinter as tk
from tkinter import messagebox, ttk

APP_TITLE = "佛山海猫录屏工具"
VERSION = "1.4"
BG, PANEL, INK, SUB = "#16181d", "#1f232b", "#e8eaf0", "#9aa3b2"
ACCENT, WARN = "#e5484d", "#f5a623"
FONT = ("Microsoft YaHei UI", 10)
FONT_B = ("Microsoft YaHei UI", 10, "bold")
FONT_S = ("Microsoft YaHei UI", 9)

STOP_HOTKEY_ID = 1
MOD_CONTROL, MOD_SHIFT = 0x0002, 0x0004
VK_X = 0x58


class App:
    def __init__(self, root):
        self.root = root
        self._set_icon()
        self.recorder = None
        self.msg_q = queue.Queue()
        self.hwnd_hotkey = None
        self.border_ov = None      # 取景边框窗口
        self._ov_cv = None
        self._ov_size = None
        self.float_bar = None      # 悬浮停止条
        self._float_lbl = None
        self._build_ui()
        self._register_hotkey()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(120, self._poll)
        self.root.after(400, self._tick)
        self.root.after(400, self._sync_border)

    # ---------------------------------------------------------------- UI
    def _build_ui(self):
        self.root.title("%s v%s" % (APP_TITLE, VERSION))
        self.root.configure(bg=BG)
        sw, sh = eng.primary_screen_size()
        w, h = 560, 800
        self.root.geometry("%dx%d+%d+%d" % (w, h, (sw - w) // 2, (sh - h) // 2))
        self.root.minsize(w, 560)
        self.root.resizable(True, True)

        head = tk.Frame(self.root, bg=BG)
        head.pack(fill="x", padx=18, pady=(14, 4))
        tk.Label(head, text="● 录屏", font=("Microsoft YaHei UI", 16, "bold"),
                 fg=INK, bg=BG).pack(side="left")
        tk.Label(head, text="悬停可选自动放大 · 佛山海猫出品 iSeacat.cn", font=FONT_S,
                 fg=SUB, bg=BG).pack(side="left", padx=10, pady=(8, 0))

        # ---- 可滚动内容区（内容变多后鼠标滚轮上下滚） ----
        body_host = tk.Frame(self.root, bg=BG)
        body_host.pack(fill="both", expand=True, padx=10, pady=(4, 0))
        self._cv = tk.Canvas(body_host, bg=BG, highlightthickness=0)
        sb = tk.Scrollbar(body_host, orient="vertical", command=self._cv.yview,
                          bg=PANEL, troughcolor=BG, relief="flat", width=10)
        self._cv.configure(yscrollcommand=sb.set)
        self._cv.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        body = tk.Frame(self._cv, bg=PANEL)
        body.bind("<Configure>",
                  lambda e: self._cv.configure(scrollregion=self._cv.bbox("all")))
        self._cv.create_window((0, 0), window=body, anchor="nw")
        self._cv.bind_all("<MouseWheel>", self._on_wheel)

        def section(text):
            f = tk.Frame(body, bg=PANEL)
            f.pack(fill="x", padx=14, pady=(10, 2))
            tk.Label(f, text=text, font=FONT_B, fg=ACCENT, bg=PANEL).pack(anchor="w")
            return f

        def radio(parent, var, values, cmds=None):
            f = tk.Frame(parent, bg=PANEL)
            f.pack(anchor="w", pady=2)
            for text, val in values:
                tk.Radiobutton(f, text=text, value=val, variable=var,
                               font=FONT, fg=INK, bg=PANEL, selectcolor="#2a2f3a",
                               activebackground=PANEL, activeforeground=INK,
                               highlightthickness=0, command=cmds).pack(side="left", padx=(0, 14))
            return f

        # 1 录制范围
        f1 = section("1 · 录制范围")
        self.var_mode = tk.StringVar(value="fullscreen")
        radio(f1, self.var_mode, [("全屏", "fullscreen"), ("指定窗口", "window"),
                                  ("框选区域", "region")], self._on_mode)
        fr = tk.Frame(f1, bg=PANEL)
        fr.pack(anchor="w", pady=(2, 0))
        tk.Button(fr, text="选择窗口…", font=FONT_S, fg=INK, bg="#2a2f3a",
                  activebackground="#3a4150", activeforeground=INK,
                  relief="flat", padx=10, command=self._pick_window).pack(side="left")
        tk.Button(fr, text="框选区域…", font=FONT_S, fg=INK, bg="#2a2f3a",
                  activebackground="#3a4150", activeforeground=INK,
                  relief="flat", padx=10, command=self._pick_region).pack(side="left", padx=8)
        self.lbl_range = tk.Label(f1, text="当前：全屏", font=FONT_S, fg=SUB, bg=PANEL)
        self.lbl_range.pack(anchor="w", pady=(4, 0))
        self.var_dual = tk.BooleanVar(value=False)
        tk.Checkbutton(f1, text="同时输出两路视频：①全屏画面 ②全程放大（鼠标在哪就持续放大哪）",
                       variable=self.var_dual, font=FONT_S, fg=INK, bg=PANEL,
                       selectcolor="#2a2f3a", activebackground=PANEL,
                       activeforeground=INK, highlightthickness=0).pack(anchor="w", pady=(6, 0))

        # 2 画面比例
        f2 = section("2 · 画面比例")
        self.var_aspect = tk.StringVar(value="none")
        radio(f2, self.var_aspect, [("原始", "none"), ("16:9 横屏", "16:9"),
                                    ("9:16 手机竖屏", "9:16"), ("1:1 方形", "1:1")])
        fc = tk.Frame(f2, bg=PANEL)
        fc.pack(anchor="w", pady=(4, 0))
        self.var_follow = tk.BooleanVar(value=True)
        tk.Checkbutton(fc, text="取景框跟随鼠标（全屏＋比例时生效）", variable=self.var_follow,
                       font=FONT, fg=INK, bg=PANEL, selectcolor="#2a2f3a",
                       activebackground=PANEL, activeforeground=INK,
                       highlightthickness=0).pack(anchor="w")
        self.var_border = tk.BooleanVar(value=True)
        tk.Checkbutton(fc, text="屏幕上显示取景边框（提醒范围，不录进视频）", variable=self.var_border,
                       font=FONT, fg=INK, bg=PANEL, selectcolor="#2a2f3a",
                       activebackground=PANEL, activeforeground=INK,
                       highlightthickness=0).pack(anchor="w")
        fs = tk.Frame(fc, bg=PANEL)
        fs.pack(anchor="w", pady=(2, 0))
        tk.Label(fs, text="取景框大小", font=FONT_S, fg=SUB, bg=PANEL).pack(side="left")
        self.var_fscale = tk.StringVar(value="0.9")
        for txt, v in (("满屏", "1.0"), ("90%", "0.9"), ("80%", "0.8")):
            tk.Radiobutton(fs, text=txt, value=v, variable=self.var_fscale,
                           font=FONT_S, fg=INK, bg=PANEL, selectcolor="#2a2f3a",
                           activebackground=PANEL, activeforeground=INK,
                           highlightthickness=0).pack(side="left", padx=(0, 10))

        # 3 鼠标悬停放大
        f3 = section("3 · 鼠标悬停自动放大")
        self.var_zoom = tk.BooleanVar(value=True)
        tk.Checkbutton(f3, text="鼠标停下时自动推近镜头，移动时拉回", variable=self.var_zoom,
                       font=FONT, fg=INK, bg=PANEL, selectcolor="#2a2f3a",
                       activebackground=PANEL, activeforeground=INK,
                       highlightthickness=0).pack(anchor="w")
        fz = tk.Frame(f3, bg=PANEL)
        fz.pack(anchor="w", pady=(2, 0))
        tk.Label(fz, text="放大倍数", font=FONT_S, fg=SUB, bg=PANEL).pack(side="left")
        self.var_zoomf = tk.StringVar(value="2.0")
        for v in ("1.5", "2.0", "2.5", "3.0"):
            tk.Radiobutton(fz, text=v + "x", value=v, variable=self.var_zoomf,
                           font=FONT_S, fg=INK, bg=PANEL, selectcolor="#2a2f3a",
                           activebackground=PANEL, activeforeground=INK,
                           highlightthickness=0).pack(side="left", padx=(0, 10))
        fz2 = tk.Frame(f3, bg=PANEL)
        fz2.pack(anchor="w", pady=(0, 0))
        tk.Label(fz2, text="停留触发", font=FONT_S, fg=SUB, bg=PANEL).pack(side="left")
        self.var_linger = tk.StringVar(value="0.6")
        for v in ("0.4", "0.6", "1.0", "1.5", "2", "3"):
            tk.Radiobutton(fz2, text=v + "s", value=v, variable=self.var_linger,
                           font=FONT_S, fg=INK, bg=PANEL, selectcolor="#2a2f3a",
                           activebackground=PANEL, activeforeground=INK,
                           highlightthickness=0).pack(side="left", padx=(0, 10))
        fz3 = tk.Frame(f3, bg=PANEL)
        fz3.pack(anchor="w", pady=(2, 0))
        tk.Label(fz3, text="放大速度", font=FONT_S, fg=SUB, bg=PANEL).pack(side="left")
        self.var_zspeed = tk.StringVar(value="0.45")
        for txt, v in (("柔和（推荐）", "0.45"), ("平滑", "0.28"), ("快速", "0.12")):
            tk.Radiobutton(fz3, text=txt, value=v, variable=self.var_zspeed,
                           font=FONT_S, fg=INK, bg=PANEL, selectcolor="#2a2f3a",
                           activebackground=PANEL, activeforeground=INK,
                           highlightthickness=0).pack(side="left", padx=(0, 10))

        # 4 鼠标样式
        f4 = section("4 · 鼠标样式（录制中替换系统指针）")
        self.var_cursor = tk.StringVar(value="ring")
        radio(f4, self.var_cursor,
              [("高亮圆环", "ring"), ("低调小圈", "subtle"), ("大箭头", "big_arrow"),
               ("圆点", "dot"), ("聚光灯", "spot"), ("不显示", "none")])
        fk = tk.Frame(f4, bg=PANEL)
        fk.pack(anchor="w", pady=(2, 0))
        self.var_ripple = tk.BooleanVar(value=True)
        tk.Checkbutton(fk, text="点击时显示涟漪扩散", variable=self.var_ripple,
                       font=FONT, fg=INK, bg=PANEL, selectcolor="#2a2f3a",
                       activebackground=PANEL, activeforeground=INK,
                       highlightthickness=0).pack(side="left")

        # 5 其他
        f5 = section("5 · 其他")
        self.var_autopen = tk.BooleanVar(value=True)
        tk.Checkbutton(f5, text="结束后自动打开输出文件夹", variable=self.var_autopen,
                       font=FONT, fg=INK, bg=PANEL, selectcolor="#2a2f3a",
                       activebackground=PANEL, activeforeground=INK,
                       highlightthickness=0).pack(anchor="w", pady=(4, 0))
        fo = tk.Frame(f5, bg=PANEL)
        fo.pack(anchor="w")
        tk.Label(fo, text="帧率", font=FONT_S, fg=SUB, bg=PANEL).pack(side="left")
        self.var_fps = tk.StringVar(value="30")
        for v in ("24", "30", "60"):
            tk.Radiobutton(fo, text=v, value=v, variable=self.var_fps,
                           font=FONT_S, fg=INK, bg=PANEL, selectcolor="#2a2f3a",
                           activebackground=PANEL, activeforeground=INK,
                           highlightthickness=0).pack(side="left", padx=(0, 10))
        tk.Label(fo, text="倒计时", font=FONT_S, fg=SUB, bg=PANEL).pack(side="left", padx=(14, 0))
        self.var_cd = tk.StringVar(value="3")
        for v in ("0", "3", "5"):
            tk.Radiobutton(fo, text=v + "s", value=v, variable=self.var_cd,
                           font=FONT_S, fg=INK, bg=PANEL, selectcolor="#2a2f3a",
                           activebackground=PANEL, activeforeground=INK,
                           highlightthickness=0).pack(side="left", padx=(0, 10))

        # 操作区
        fa = tk.Frame(self.root, bg=BG)
        fa.pack(fill="x", padx=14, pady=6)
        self.btn_start = tk.Button(fa, text="●  开始录制", font=("Microsoft YaHei UI", 12, "bold"),
                                   fg="white", bg=ACCENT, activebackground="#f05b60",
                                   activeforeground="white", relief="flat", padx=26, pady=8,
                                   cursor="hand2", command=self._start)
        self.btn_start.pack(side="left")
        self.btn_stop = tk.Button(fa, text="■  停止  (Ctrl+Shift+X)", font=("Microsoft YaHei UI", 12, "bold"),
                                  fg="white", bg="#3a4150", activebackground="#4a5262",
                                  activeforeground="white", relief="flat", padx=20, pady=8,
                                  cursor="hand2", state="disabled", command=self._stop)
        self.btn_stop.pack(side="left", padx=10)
        self.btn_open = tk.Button(fa, text="打开输出文件夹", font=FONT_S, fg=INK, bg="#2a2f3a",
                                  activebackground="#3a4150", activeforeground=INK,
                                  relief="flat", padx=10, command=self._open_out)
        self.btn_open.pack(side="right")

        self.lbl_status = tk.Label(self.root, text="就绪 · 输出到 录制输出 文件夹",
                                   font=FONT_S, fg=SUB, bg=BG, anchor="w")
        self.lbl_status.pack(fill="x", padx=18, pady=(0, 10))
        self._on_mode()

    def _on_wheel(self, e):
        try:
            self._cv.yview_scroll(-1 * (e.delta // 120), "units")
        except Exception:
            pass

    # ---------------------------------------------------------------- 选择
    def _on_mode(self, *_):
        m = self.var_mode.get()
        self.lbl_range.config(text={"fullscreen": "当前：整个主屏",
                                    "window": "当前：未选择窗口（点「选择窗口…」）",
                                    "region": "当前：未框选（点「框选区域…」）"}[m])

    def _pick_window(self):
        wins = eng.list_windows()
        top = tk.Toplevel(self.root)
        top.title("选择要录制的窗口")
        top.configure(bg=PANEL)
        top.geometry("520x420+%d+%d" % (self.root.winfo_x() + 20, self.root.winfo_y() + 40))
        top.transient(self.root)
        lb = tk.Listbox(top, font=FONT, fg=INK, bg="#12141a", selectbackground=ACCENT,
                        relief="flat", highlightthickness=0)
        lb.pack(fill="both", expand=True, padx=12, pady=12)
        for hwnd, title, r in wins:
            lb.insert("end", "%s  [%dx%d]" % (title[:56], r[2], r[3]))
        lb.selection_set(0)

        def confirm(_=None):
            sel = lb.curselection()
            if sel:
                self.hwnd_sel = wins[sel[0]][0]
                self.var_mode.set("window")
                self.lbl_range.config(text="当前窗口：%s" % wins[sel[0]][1][:44])
            top.destroy()
        lb.bind("<Double-Button-1>", confirm)
        tk.Button(top, text="确定", font=FONT, fg="white", bg=ACCENT, relief="flat",
                  padx=16, command=confirm).pack(pady=(0, 12))

    def _pick_region(self):
        sw, sh = eng.primary_screen_size()
        ov = tk.Toplevel(self.root)
        ov.overrideredirect(True)
        ov.geometry("%dx%d+0+0" % (sw, sh))
        ov.attributes("-alpha", 0.22)
        ov.configure(bg="black", cursor="crosshair")
        cv = tk.Canvas(ov, bg="black", highlightthickness=0)
        cv.pack(fill="both", expand=True)
        state = {"x0": 0, "y0": 0, "rect": None}

        def down(e):
            state.update(x0=e.x, y0=e.y, rect=None)
        def move(e):
            if state["rect"]:
                cv.delete(state["rect"])
            ratio = {"16:9": 16 / 9, "9:16": 9 / 16, "1:1": 1.0}.get(self.var_aspect.get())
            x1, y1 = e.x, e.y
            if ratio:
                wpx, hpx = abs(x1 - state["x0"]), abs(y1 - state["y0"])
                if wpx / max(hpx, 1) > ratio:
                    wpx = int(hpx * ratio)
                else:
                    hpx = int(wpx / ratio)
                x1 = state["x0"] + (wpx if e.x >= state["x0"] else -wpx)
                y1 = state["y0"] + (hpx if e.y >= state["y0"] else -hpx)
            state["rect"] = cv.create_rectangle(state["x0"], state["y0"], x1, y1,
                                                outline=WARN, width=2)
        def up(e):
            x0, y0 = state["x0"], state["y0"]
            x1, y1 = e.x, e.y
            l, t = min(x0, x1), min(y0, y1)
            w, h = abs(x1 - x0), abs(y1 - y0)
            ov.destroy()
            if w >= 64 and h >= 64:
                self.region_sel = (l, t, w, h)
                self.var_mode.set("region")
                self.lbl_range.config(text="当前区域：%dx%d  起点(%d,%d)" % (w, h, l, t))
        cv.bind("<ButtonPress-1>", down)
        cv.bind("<B1-Motion>", move)
        cv.bind("<ButtonRelease-1>", up)
        cv.bind("<Escape>", lambda e: ov.destroy())
        ov.focus_force()

    # ---------------------------------------------------------------- 录制
    def _collect_cfg(self):
        kwargs = dict(
            mode=self.var_mode.get(),
            fps=int(self.var_fps.get()),
            zoom_enabled=self.var_zoom.get(),
            zoom_factor=float(self.var_zoomf.get()),
            linger_s=float(self.var_linger.get()),
            cursor_style=self.var_cursor.get(),
            click_ripple=self.var_ripple.get(),
            aspect=self.var_aspect.get(),
            zoom_tau=float(self.var_zspeed.get()),
            follow_mouse=self.var_follow.get(),
            follow_scale=float(self.var_fscale.get()),
            dual_output=self.var_dual.get(),
        )
        if kwargs["mode"] == "window":
            hwnd = getattr(self, "hwnd_sel", None)
            if not hwnd:
                messagebox.showwarning(APP_TITLE, "请先点「选择窗口…」选择一个窗口")
                return None
            kwargs["hwnd"] = hwnd
        elif kwargs["mode"] == "region":
            region = getattr(self, "region_sel", None)
            if not region:
                messagebox.showwarning(APP_TITLE, "请先点「框选区域…」框选范围")
                return None
            kwargs["region"] = region
        if kwargs["aspect"] != "none" and kwargs["mode"] != "fullscreen":
            pass  # 区域/窗口模式下按比例中心裁切
        return eng.Recorder(**kwargs)

    def _start(self):
        if self.recorder and self.recorder.running:
            return
        rec = self._collect_cfg()
        if not rec:
            return
        self.recorder = rec
        cd = int(self.var_cd.get())
        self.btn_start.config(state="disabled")
        if cd > 0:
            self.lbl_status.config(text="%d 秒后开始录制…" % cd, fg=WARN)

        def countdown(n):
            if n > 0:
                self.lbl_status.config(text="%d 秒后开始录制…" % n, fg=WARN)
                self.root.after(1000, countdown, n - 1)
                return
            self.root.withdraw()
            time.sleep(0.25)
            rec.start()
            self._show_float_bar()
            self.btn_stop.config(state="normal", bg=ACCENT)
            self.lbl_status.config(text="● 录制中… 停止：Ctrl+Shift+X 或点停止按钮", fg=ACCENT)
        countdown(cd)

    def _stop(self):
        if not self.recorder:
            return
        self._hide_float_bar()
        self.btn_stop.config(state="disabled")
        out = self.recorder.stop()
        if self.recorder.error:
            self.lbl_status.config(text="录制出错：%s" % str(self.recorder.error)[:80], fg=WARN)
            messagebox.showerror(APP_TITLE, "录制出错：\n%s" % self.recorder.error)
        else:
            msg = "完成：%s（%.1f 秒 / %d 帧）" % (os.path.basename(out),
                                                 self.recorder.elapsed, self.recorder.frames)
            if self.recorder.output2:
                msg += " + %s（全程放大）" % os.path.basename(self.recorder.output2)
            self.lbl_status.config(text=msg, fg="#7ee787")
            if self.var_autopen.get():
                self._open_out()
        self.btn_start.config(state="normal")
        self._bring_to_front()
        self.recorder = None

    def _bring_to_front(self):
        """把主窗口拉回前台（停止录制后 / 再次双击图标时）"""
        try:
            self.root.state("normal")
            self.root.deiconify()
            self.root.lift()
            self.root.attributes("-topmost", True)
            self.root.after(300, lambda: self.root.attributes("-topmost", False))
            self.root.focus_force()
        except Exception:
            pass

    # ------------------------------------------------ 取景边框（屏幕提醒）
    def _make_overlay(self, w, h, l, t):
        ov = tk.Toplevel(self.root)
        ov.overrideredirect(True)
        ov.attributes("-topmost", True)
        TC = "#010101"                      # 透明键色：内部全透明，只露边线
        ov.configure(bg=TC)
        try:
            ov.attributes("-transparentcolor", TC)
        except Exception:
            pass
        cv = tk.Canvas(ov, bg=TC, highlightthickness=0)
        cv.pack(fill="both", expand=True)
        cv.create_rectangle(1, 1, max(2, w - 2), max(2, h - 2),
                            outline=WARN, width=3)
        ov.geometry("%dx%d+%d+%d" % (w, h, int(l), int(t)))
        ov.update_idletasks()
        try:  # 点击穿透 + 不进 Alt-Tab + 不被录进视频(WDA_EXCLUDEFROMCAPTURE)
            u32 = ctypes.windll.user32
            wid = ov.winfo_id()   # 注意：winfo_id() 本身就是 int，不能再 int(...,0)
            hwnd = u32.GetAncestor(ctypes.c_void_p(wid), 2) or wid
            ex = u32.GetWindowLongW(ctypes.c_void_p(hwnd), -20)
            u32.SetWindowLongW(ctypes.c_void_p(hwnd), -20,
                               ex | 0x20 | 0x80 | 0x08000000)
            u32.SetWindowDisplayAffinity(ctypes.c_void_p(hwnd), 0x11)
        except Exception:
            pass
        self._ov_cv = cv
        self._ov_size = (w, h)
        return ov

    def _sync_border(self):
        """录制中每 90ms 把边框对齐到引擎的取景框位置"""
        try:
            rec = self.recorder
            active = (rec and rec.running and self.var_border.get()
                      and rec.mode == "fullscreen" and rec.aspect not in (None, "none")
                      and rec.base_rect)
            if not active:
                if self.border_ov:
                    self.border_ov.destroy()
                    self.border_ov = self._ov_cv = None
                return
            l, t, w, h = rec.base_rect
            if not self.border_ov:
                self.border_ov = self._make_overlay(w, h, l, t)
            elif self._ov_size != (w, h):
                self._ov_cv.delete("all")
                self._ov_cv.create_rectangle(1, 1, max(2, w - 2), max(2, h - 2),
                                             outline=WARN, width=3)
                self._ov_size = (w, h)
            self.border_ov.geometry("%dx%d+%d+%d" % (w, h, int(l), int(t)))
        except Exception:
            self.border_ov = self._ov_cv = None
        finally:
            self.root.after(90, self._sync_border)

    # ------------------------------------------------ 悬浮停止条（录制中）
    def _show_float_bar(self):
        if self.float_bar:
            return
        fb = tk.Toplevel(self.root)
        fb.overrideredirect(True)
        fb.attributes("-topmost", True)
        fb.configure(bg="#0f1115")
        sw, sh = eng.primary_screen_size()
        w, h = 150, 34
        fb.geometry("%dx%d+%d+%d" % (w, h, sw - w - 28, sh - h - 28))
        row = tk.Frame(fb, bg="#0f1115")
        row.pack(expand=True, fill="both")
        lbl = tk.Label(row, text="● 0s", font=("Microsoft YaHei UI", 9),
                       fg="#e8eaf0", bg="#0f1115")
        lbl.pack(side="left", padx=(10, 4))
        tk.Button(row, text="停止", font=("Microsoft YaHei UI", 9, "bold"),
                  fg="white", bg=ACCENT, activebackground="#f05b60",
                  activeforeground="white", relief="flat", padx=8, pady=0,
                  cursor="hand2", command=self._stop).pack(side="right", padx=(0, 8))
        # 整条可拖动
        drag = {"x": None, "y": None}

        def press(e):
            drag.update(x=e.x, y=e.y)

        def move(e):
            if drag["x"] is not None:
                fb.geometry("+%d+%d" % (fb.winfo_x() + e.x - drag["x"],
                                        fb.winfo_y() + e.y - drag["y"]))

        for wd in (fb, row, lbl):
            wd.bind("<ButtonPress-1>", press)
            wd.bind("<B1-Motion>", move)
        try:  # 工具窗口不抢焦点 + 不录进视频（保留可点击，不加穿透）
            u32 = ctypes.windll.user32
            wid = fb.winfo_id()   # winfo_id() 本身是 int
            hwnd = u32.GetAncestor(ctypes.c_void_p(wid), 2) or wid
            ex = u32.GetWindowLongW(ctypes.c_void_p(hwnd), -20)
            u32.SetWindowLongW(ctypes.c_void_p(hwnd), -20, ex | 0x80 | 0x08000000)
            u32.SetWindowDisplayAffinity(ctypes.c_void_p(hwnd), 0x11)
        except Exception:
            pass
        self.float_bar = fb
        self._float_lbl = lbl
        self.root.after(500, self._float_tick)

    def _hide_float_bar(self):
        if self.float_bar:
            try:
                self.float_bar.destroy()
            except Exception:
                pass
            self.float_bar = None
            self._float_lbl = None

    def _float_tick(self):
        if not self.float_bar:
            return
        rec = self.recorder
        if rec and rec.running and self._float_lbl:
            try:
                self._float_lbl.config(text="● %ds" % rec.elapsed)
            except Exception:
                pass
        self.root.after(500, self._float_tick)

    def _set_icon(self):
        """窗口/任务栏图标：优先低像素 ico（48x48），退回 png"""
        for cand in (os.path.join(eng.APP_DIR, "app_icon.ico"),
                     os.path.join(eng.APP_DIR, "app_icon.png")):
            if not os.path.exists(cand):
                continue
            try:
                if cand.lower().endswith(".ico"):
                    self.root.iconbitmap(cand)
                else:
                    img = tk.PhotoImage(file=cand)
                    self.root.iconphoto(True, img)
                    self._icon_img = img  # 防 GC
                break
            except Exception:
                pass

    def _open_out(self):
        os.makedirs(eng.OUTPUT_DIR, exist_ok=True)
        subprocess.Popen('explorer "%s"' % eng.OUTPUT_DIR)

    def _tick(self):
        if self.recorder and self.recorder.running:
            self.lbl_status.config(
                text="● 录制中  %.0f 秒  |  停止：Ctrl+Shift+X" % self.recorder.elapsed,
                fg=ACCENT)
        self.root.after(400, self._tick)

    def _poll(self):
        try:
            while True:
                msg = self.msg_q.get_nowait()
                if msg == "hotkey_stop" and self.recorder and self.recorder.running:
                    self._stop()
        except queue.Empty:
            pass
        self.root.after(120, self._poll)

    # ---------------------------------------------------------------- 热键
    def _register_hotkey(self):
        import ctypes.wintypes as wt

        def hot_loop():
            msg = wt.MSG()
            while True:  # 每次触发后重新注册，保证第二次录制热键仍有效
                if not eng.windll.user32.RegisterHotKey(
                        None, STOP_HOTKEY_ID, MOD_CONTROL | MOD_SHIFT, VK_X):
                    time.sleep(1)
                    continue
                while eng.windll.user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                    if msg.message == 0x0312:  # WM_HOTKEY
                        self.msg_q.put("hotkey_stop")
                        eng.windll.user32.UnregisterHotKey(None, STOP_HOTKEY_ID)
                        break
        threading.Thread(target=hot_loop, daemon=True).start()

    def _on_close(self):
        if self.recorder and self.recorder.running:
            if not messagebox.askyesno(APP_TITLE, "正在录制，确定停止并退出？"):
                return
            self.recorder.stop()
        self._hide_float_bar()
        try:
            eng.windll.user32.UnregisterHotKey(None, STOP_HOTKEY_ID)
        except Exception:
            pass
        self.root.destroy()


def _trace(msg):
    try:
        with open(os.path.join(eng.APP_DIR, "startup_trace.log"), "a", encoding="utf-8") as f:
            f.write(time.strftime("[%H:%M:%S] ") + msg + "\n")
    except Exception:
        pass


def main():
    _trace("main 进入")
    import ctypes.wintypes  # noqa: F401  (MSG 需要)
    # 单实例（use_last_error 才能可靠读 GetLastError）
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateMutexW(None, False, "Global\\GraceRecorder")
    err = ctypes.get_last_error()
    _trace("mutex err=%s" % err)
    if err == 183:  # ERROR_ALREADY_EXISTS
        # 已有实例在跑：发信号让它把窗口拉回前台，而不是让用户干找
        k2 = ctypes.WinDLL("kernel32", use_last_error=True)
        h = k2.OpenEventW(0x0002, False, "Global\\GraceRecorderShow")  # EVENT_MODIFY_STATE
        if h:
            k2.SetEvent(ctypes.c_void_p(h))
            return
        root = tk.Tk()
        root.withdraw()
        messagebox.showinfo(APP_TITLE, "Grace 录屏工具已经在运行了")
        return
    root = tk.Tk()
    _trace("Tk 创建成功")
    app = App(root)
    _trace("App 构建成功，进入 mainloop")
    app._bring_to_front()   # 启动即弹到前台，避免被其他窗口压住"找不到"
    _start_show_watcher(app)
    root.report_callback_exception = lambda *a: _log_crash(a)
    root.mainloop()
    _trace("mainloop 退出")


def _start_show_watcher(app):
    """监听「把窗口调到前台」的命名事件（双击图标第二次时触发）"""
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    h = k32.CreateEventW(None, False, False, "Global\\GraceRecorderShow")
    if not h:
        return

    def loop():
        while True:
            if k32.WaitForSingleObject(ctypes.c_void_p(h), 0xFFFFFFFF) == 0:
                try:
                    app.root.after(0, app._bring_to_front)
                except Exception:
                    return

    threading.Thread(target=loop, daemon=True).start()


def _log_crash(exc_info):
    log = os.path.join(eng.APP_DIR, "crash.log")
    with open(log, "a", encoding="utf-8") as f:
        f.write(time.strftime("[%Y-%m-%d %H:%M:%S]\n") + "".join(traceback.format_exception(*exc_info)) + "\n")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        with open(os.path.join(eng.APP_DIR, "crash.log"), "a", encoding="utf-8") as f:
            f.write(time.strftime("[%Y-%m-%d %H:%M:%S] main\n") + traceback.format_exc() + "\n")
        raise
