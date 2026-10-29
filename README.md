# 佛山海猫录屏工具（iSeacat ScreenRecorder）

> 免费开源的 Screen Studio 替代 · Windows 录屏工具
> 鼠标停哪里，镜头就推到哪里——像专业软件一样"会运镜"

<img src="app_icon.png" width="96" alt="icon"/>

## ✨ 功能特性

- **三种录制范围**：全屏 / 指定窗口（自动跟随窗口移动缩放）/ 框选区域
- **画面比例**：原始 / 16:9 横屏 / 9:16 手机竖屏 / 1:1 方形，全屏+比例时取景框可平滑跟随鼠标
- **鼠标悬停自动放大**（招牌功能）：鼠标停下自动推近镜头（1.5x–3.0x 可调、触发时长可调、柔和/平滑/快速三档），移动时平滑拉回全景
- **自定义鼠标样式**：高亮圆环 / 低调小圈 / 大箭头 / 圆点 / 聚光灯 / 不显示，点击带涟漪扩散
- **双路输出**：一次录制同时出两路视频——①原画面 ②全程自动放大（剪辑时二选一）
- **其他**：24/30/60 fps、录制倒计时、全局热键 `Ctrl+Shift+X` 停止、悬浮进度条、屏幕取景边框提醒（不录进视频）、录完自动打开输出文件夹
- **输出**：MP4（H.264，CRF 18，yuv420p），无水印、无时长限制、完全本地处理

## 🚀 快速开始（免安装便携版）

1. 到 [Releases](../../releases) 下载便携版压缩包，解压到任意目录
2. 双击 `启动录屏工具.bat`
3. 点「● 开始录制」，成品在 `录制输出/` 文件夹（录完自动弹出）

> 要求：Windows 10/11 64 位。便携版自带 Python 运行时与 FFmpeg，目标电脑**无需安装任何东西**。

## 🛠 从源码运行

```bash
# 需要 Python 3.13（3.10+ 一般亦可）
pip install bettercam opencv-python-headless numpy comtypes
python grace_recorder_gui.py
```

FFmpeg 需在 PATH 中，或放一个 `ffmpeg.exe` 到 `runtime/ffmpeg/` 下（程序会优先使用）。

## 📦 一键自制便携包（可选）

```bash
python make_portable.py
```

脚本会自动：复制本机 Python 3.13 到 `runtime/python/` → 安装依赖包 → 准备 FFmpeg。
完成后**整个文件夹**可以随意复制到其他 Windows 电脑，双击 `启动录屏工具.bat` 即用
（拷贝时可排除 `.venv`、`__pycache__`、`*.log` 省空间）。

## 💡 使用技巧

- 录软件教程：选「全屏 + 16:9 + 悬停放大」，成片自带镜头语言
- 发手机短视频：选「9:16」，录屏内容自动居中裁切
- 「双路输出」先都录下来，后期想用哪路用哪路
- 悬停触发建议 0.6s；快速翻页面时用「快速」档放大速度

## ⚙️ 工作原理

```
bettercam (DXGI Desktop Duplication) 抓屏
   → OpenCV 处理（悬停放大裁剪 / 鼠标样式叠加 / 涟漪）
   → ffmpeg rawvideo 管道实时编码 H.264 MP4
```

纯本地运行，不联网、不上传任何数据。

## 📄 许可证

- 本项目代码：[MIT](LICENSE)
- 便携包内附带的 FFmpeg 为 GPL v3 构建（来自 [gyan.dev](https://www.gyan.dev/ffmpeg/builds/)），第三方组件许可见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)

---

佛山海猫 · iSeacat —— 每天分享一个 AI 玩法 🐱
