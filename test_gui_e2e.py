# -*- coding: utf-8 -*-
"""GUI 端到端测试：构建 App → PrintWindow 截图 → 真实录制 3s → 校验产物 → 截图 → 销毁"""
import ctypes
import glob
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cv2  # type: ignore
import numpy as np
import tkinter as tk

import grace_recorder as eng
import grace_recorder_gui as gui

APP_DIR = os.path.dirname(os.path.abspath(__file__))
SHOT1 = os.path.join(APP_DIR, "_gui_shot1.png")
SHOT2 = os.path.join(APP_DIR, "_gui_shot2.png")


def shot(hwnd, path):
    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    from ctypes import byref

    class BMIH(ctypes.Structure):
        _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_long),
                    ("biHeight", ctypes.c_long), ("biPlanes", ctypes.c_uint16),
                    ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
                    ("biSizeImage", ctypes.c_uint32), ("biXPelsPerMeter", ctypes.c_long),
                    ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", ctypes.c_uint32),
                    ("biClrImportant", ctypes.c_uint32)]

    rc = eng.RECT()
    user32.GetWindowRect(ctypes.c_void_p(hwnd), byref(rc))
    w, h = rc.right - rc.left, rc.bottom - rc.top
    hdc = user32.GetDC(0)
    mem = gdi32.CreateCompatibleDC(hdc)
    hbmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    gdi32.SelectObject(mem, hbmp)
    user32.PrintWindow(ctypes.c_void_p(hwnd), mem, 2)  # PW_RENDERFULLCONTENT
    bmi = BMIH()
    bmi.biSize, bmi.biWidth, bmi.biHeight = ctypes.sizeof(BMIH), w, -h
    bmi.biPlanes, bmi.biBitCount = 1, 32
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(mem, hbmp, 0, h, buf, byref(bmi), 0)
    arr = np.frombuffer(buf, np.uint8).reshape(h, w, 4)
    ok_img, enc = cv2.imencode(".png", cv2.cvtColor(arr, cv2.COLOR_BGRA2BGR))
    if ok_img:
        enc.tofile(path)  # imwrite 不支持中文路径，用 tofile
    gdi32.DeleteObject(hbmp)
    gdi32.DeleteDC(mem)
    user32.ReleaseDC(0, hdc)
    return os.path.exists(path) and os.path.getsize(path) > 5000


def main():
    root = tk.Tk()
    app = gui.App(root)
    result = {}

    def get_top_hwnd():
        wid = int(root.winfo_id())
        return ctypes.windll.user32.GetParent(ctypes.c_void_p(wid)) or wid

    def step_shot_and_start():
        result["shot1"] = shot(get_top_hwnd(), SHOT1)
        app.var_cd.set("0")
        app._start()

    def step_stop():
        if app.recorder and app.recorder.running:
            app._stop()
        result["shot2"] = shot(get_top_hwnd(), SHOT2)

    def step_verify():
        files = sorted(glob.glob(os.path.join(eng.OUTPUT_DIR, "录屏_*.mp4")),
                       key=os.path.getmtime)
        ok = bool(result.get("shot1")) and bool(result.get("shot2"))
        if files:
            out = files[-1]
            dur = eng.media_duration(out)
            size = os.path.getsize(out)
            print("E2E 产物: %s  %.2fs  %d bytes" % (os.path.basename(out), dur, size))
            ok = ok and size > 10000 and 2.0 < dur < 4.5
        else:
            print("E2E 产物: 无")
            ok = False
        print("E2E 截图: shot1=%s shot2=%s" % (result.get("shot1"), result.get("shot2")))
        print("E2E 结果:", "PASS" if ok else "FAIL")
        root.destroy()
        sys.exit(0 if ok else 1)

    root.after(900, step_shot_and_start)
    root.after(4600, step_stop)
    root.after(6200, step_verify)
    root.mainloop()


if __name__ == "__main__":
    main()
