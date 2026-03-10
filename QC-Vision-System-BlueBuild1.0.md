# QC-Vision-System-BlueBuild1.0 - 核心复刻文档

## 1. 项目概述 (Project Overview)
本系统名作 **QC Vision 在线视检系统**。它是一个基于人工智能与计算机视觉算法（OpenCV）的工业级产品外观瑕疵检测 Web 桌面混合应用。系统通过比对待测产品图像与合格的标准基准图像，自动框选并用红圈标出不一致的缺陷区域。

**核心功能目标：**
- **双模工作流**：支持使用本地静态图片的**手动检测模式**，以及调用物理硬件摄像头的**在线检测模式**。
- **动态 ROI (Region of Interest)**：允许用户在基准图上通过鼠标框选特定区域，检测算法将仅对比该区域内的图像（遮蔽不必要的背景干扰）。
- **倒计时自动抓拍**：在 Camera 模式下，提供 5 秒倒计时读秒，结束后静默抓拍并立刻比对。
- **单文件便携发版 (Standalone EXE)**：支持通过 PyInstaller 将所有 Python 后端环境、算法模型和 HTML 前端一键打包为免安装的单文件 `.exe`。

---

## 2. 技术栈 (Tech Stack)
- **后端 (Backend)**: Python 3.x, FastAPI (提供 RESTful API), Uvicorn (ASGI 服务器)
- **视觉算法 (Computer Vision)**: OpenCV (`opencv-python`), Numpy, Scikit-Image (`skimage.metrics.structural_similarity` 用于 SSIM 差异计算)
- **前端 (Frontend)**: 原生 HTML5 Canvas, JS (Vanilla ES6+), 纯 CSS3 (无任何重量级如 Vue/React 或 Tailwind 等包袱代码)。
- **打包工具**: PyInstaller

**核心依赖 (`requirements.txt`)**
```txt
fastapi
uvicorn
opencv-python
numpy
scikit-image
python-multipart
pyinstaller
```

---

## 3. 目录与架构设计 (Directory Structure)
复刻该项目必须严谨维持以下目录层级结构，特别是为了适配 PyInstaller 打包时对静态文件 `_MEIPASS` 的寻址机制。

```
QC-AI-test-APP/
│
├── backend/                  # 后端及算法层
│   ├── __init__.py
│   ├── main.py               # FastAPI 路由控制器与 Web 服务器顶层
│   └── vision.py             # 纯 OpenCV 图像处理逻辑、SSIM比对核心类
│
├── frontend/                 # 纯静态前端层 (被 main.py 挂载)
│   ├── index.html            # 单页面应用 DOM，分为欢迎、手动、在线三大卡片视图
│   ├── style.css             # Glassmorphism (毛玻璃) 现代工业深色 UI、自适应网格
│   └── app.js                # Canvas ROi框选交互、API请求、模式切换逻辑
│
├── requirements.txt          # Python 包依赖
├── run_app.py                # PyInstaller 入口专用重写文件（禁用热重载、带多进程支持）
├── build_exe.bat             # 一键自动打包为 Standalone exe 的批处理脚本
└── start.bat                 # 纯源码环境下的本地一键测试脚本
```

---

## 4. 核心逻辑解密 (Core Implementation Details) - 供 AI 复刻参考

### 4.1 后端算法 - `vision.py` 的关键流程
- **核心类**: `VisionSystem`。需要在内存中长期维护状态：`reference_image` (目前的标准图), `rois` (人工框出的感兴趣区列表), 以及 `cv2.VideoCapture` 实例。
- **图像比对算法路线**:
  1. 获取基准图和待测图，统一 `cv2.resize` 缩放至同一尺寸 (如 800x600)。
  2. 转换为灰度图 (`cv2.cvtColor`) 并应用高斯模糊 (`cv2.GaussianBlur`) 去噪。
  3. **掩膜处理 (Masking)**: 如果用户画了 ROI 框，则生成纯黑 Mask，仅把 ROI 区域填白。利用 `cv2.bitwise_and` 把基准和待测图裁切得只剩下 ROI 区域有内容。
  4. 利用 SIFT/ORB 提取特征点，结合 Flann/BFMatcher 计算偏移矩阵 `cv2.findHomography`，对待测图做 `cv2.warpPerspective` **对齐 (Alignment)**。
  5. 调用 **SSIM (结构相似性)** 生成差异图 (`diff`)。将差值乘以 255 转为标准像素级差异。
  6. 设定严格的二值化阈值 (`cv2.threshold` 如 thresh=30-50)。
  7. 寻找瑕疵轮廓 `cv2.findContours`，丢弃过小的早点，针对合格的瑕疵轮廓画红色粗实线圆圈或外接矩形标出缺陷。返回合成后的全图，并将状态标记为 "FAIL"。如果找不到大轮廓则标为 "PASS"。

### 4.2 后端接口 - `main.py` 的路由表
- Web 服务器必须绕过跨域限制 (CORS)。静态目录采用 `sys._MEIPASS` 兼容语法挂载至根路径 `/`。
- `GET /api/status`: 健康检查
- `GET /video_feed`: `StreamingResponse` 返回 MJPEG 流。读取摄像头 `yield` 循环生成 multipart frames。
- `POST /upload_reference`: 接收表单图片并存入 `vision_system`
- `POST /set_roi`: 接收 JSON 的 ROI 数组
- `POST /start_camera` / `POST /stop_camera`: 手动控制硬件开关，避免后台常驻抢占资源。
- `POST /inspect`: 接收测试图片单帧 -> 走对比
- `POST /capture_reference` / `POST /capture_and_inspect`: 调用 OpenCV 在内存抓取一帧图像 -> 转为字节数组 -> 直接丢入比对管道并返回 base64 形式的结果 JSON。

### 4.3 前端样式 - `style.css` 防坑指南
- 页面必须暗黑工业风。使用 CSS Variables 管理基色系 (如 `--bg-color: #121212`, `--accent-color: #007bff`, `--success-color: #00C851`)。
- **图像拉伸变形雷区**: 处理 `div.image-container` 时，必须设置 `flex-grow: 1; display: flex; align-items: center; justify-content: center; overflow: hidden;`，内部包含的 `<img />` 和 `<canvas />` **必须** 强制设定 `width: 100%; height: 100%; object-fit: contain; display: block;`。绝不可以用内联 HTML 宽高覆盖。这是保持图片真实长宽比且不溢出的关键。

### 4.4 前端交互 - `app.js` 难点与闭包
- **导航切换**: 页面包含 `welcome-screen`, `manual-mode-screen` 和 `camera-mode-screen` 三个 DIV。通过操纵 `display: flex/none` 实现页面切换。由 `isOffline` 等全局标志位阻断无网络情况下的错误点击。
- **Canvas ROI 框选漂移问题 (极易出错)**: 
  由于图像是 `object-fit: contain` 的，其实际渲染的中心坐标和宽高并不等于包裹它的 DOM 元素的宽高。必须利用原生 `new Image()` 对象获取内部原始分辨率，计算出 `比率 (ratio) = min(canvasW/imgW, canvasH/imgH)`。然后计算出**图像基于画布产生的边框留白偏移 (OffsetX / OffsetY)**。用户用鼠标获取的 `clientX/Y` 需要先扣掉画布偏移量，再除以缩放 ratio，才能换算成送入后端的 1:1 坐标！
- **重置与垃圾回收**: 点击“下一个测试”时，仅清除右侧 Result DOM；点击“重置系统”，不仅要重置左右所有 DOM、绘制层 ctx，还必须 Fetch 调用一次后端的 `POST /reset` 将内存中的历史图片和坐标数组统统归零。

### 4.5. 终极发版 - 怎么变成单文件？
- 编写 `run_app.py` 并且 **必须注入 `multiprocessing.freeze_support()`**，否则 Windows 打包出来的 exe 只要利用到了 uvicorn 进程池就会报错导致闪退。然后启动 Thread 调用 WebBrowser 自动弹窗。
- 打包命令：
  ```cmd
  pyinstaller --name "QC_Vision_System" --add-data "frontend;frontend" --onefile run_app.py
  ```
  AI 需自动生成此配置文件或脚本以便用户无脑点击。最终形成一个可在任何纯净 Windows PC 双击跑起来并自启浏览器的“本地虚拟网页程序”。

---
<*文档由 AI 生成并归档。新介入大模型的 Prompt: 请严格遵循此文档的业务闭环与接口说明复刻 QC-Vision-System。*>
