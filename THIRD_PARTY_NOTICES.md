# Third-Party Notices / 第三方组件许可

本工具基于以下优秀的开源项目构建，在此致谢。

| 组件 | 许可证 | 来源 |
|---|---|---|
| bettercam | MIT | https://github.com/RootKit-Org/BetterCam |
| numpy | BSD-3-Clause (and 0BSD, MIT, Zlib, CC0-1.0) | https://github.com/numpy/numpy |
| opencv-python-headless | Apache 2.0 | https://github.com/opencv/opencv-python |
| comtypes | MIT | https://github.com/enthought/comtypes |
| FFmpeg (便携包内置) | GPL v3 | https://github.com/GyanD/codexffmpeg/releases |

说明：

- `bettercam`：DXGI Desktop Duplication 屏幕抓取库（dxcam 的改进分支），MIT 许可。
- `numpy`：数值计算基础库，BSD-3-Clause 系许可。
- `opencv-python-headless`：OpenCV 的无 GUI 预编译包，Apache 2.0 许可；OpenCV 本身包含其第三方组件许可，见包内 `LICENSE-3RD-PARTY.txt`。
- `comtypes`：Python COM 接口库，MIT 许可。
- **FFmpeg**：便携版压缩包内附带的 `ffmpeg.exe` 来自 gyan.dev 的 full build（启用 GPL 组件，GPL v3 许可）。FFmpeg 项目源码与对应构建可从上表链接获取；本仓库的 Python/配置代码以 MIT 发布，FFmpeg 二进制文件按其自身 GPL v3 许可分发。

各 Python 包的完整许可文本以 PyPI 分发包内的 LICENSE 文件为准。
