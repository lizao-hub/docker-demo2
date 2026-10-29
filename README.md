# 无人机直播本地模拟（Windows 推流 + 容器平台）

```text
Windows FFmpeg ──RTMP──▶ MediaMTX(drone1)
                              │
                              ├──WebRTC/WHEP──▶ 浏览器（原画）
                              │
                              └──RTSP──▶ worker 容器 ──RTMP──▶ drone1_yolo
                                                              │
                                                     WebRTC/WHEP
                                                              ▼
                                                         浏览器（检测）

浏览器 :8080 ──/api──▶ frontend(nginx) ──▶ backend ──Docker socket──▶ worker
```

推流端模拟真实的机场/无人机：**在 Windows 上独立运行，不由平台启动**。
平台（前端 + 后端）只管理 AI 算法容器，视频始终由浏览器直接连 MediaMTX。

worker 目前用 numpy 模拟 YOLO 输出（随机框 + 置信度），不依赖 torch、CUDA
和 `best.pt`；换成真模型时只替换 `worker/src/drone_worker/mock.py`。

## 前置条件

- WSL2 Ubuntu，Docker + Compose 可用；
- Windows 侧 FFmpeg 在 `PATH` 中（实测 9.0.2）；
- 视频文件 `assets/drone.mp4`。

## 启动

### 1. WSL：启动平台

```bash
cd /home/lizao/docker-demo2
docker compose up -d --build
docker compose ps
```

会启动 `mediamtx`、`backend`、`frontend`、`worker` 四个容器。

### 2. Windows：启动模拟推流

```powershell
cd E:\Pycharm\docker-demo2
powershell -ExecutionPolicy Bypass -File scripts\push-windows.ps1
```

也可以运行 `scripts\push-windows.cmd`。脚本会循环推 `assets\drone.mp4`，
断开后每 2 秒自动重试。

### 3. 打开控制台

```text
http://localhost:8080
```

推流没起来时页面显示“等待信号源”；推流上线后自动播放原画。

## 页面行为

- 默认播放原画 `drone1`，推流上线后自动出现画面。
- 「启动算法」启动 worker 容器，画面切到 `drone1_yolo`。
- 「停止算法」停止容器，自动切回原画。
- 信号源未上线时「启动算法」不可用。
- 页面不控制推流；推流由 Windows 侧的设备模拟脚本负责。

## 服务与端口

| 服务 | 端口 | 说明 |
| --- | --- | --- |
| frontend | 8080 | nginx + Vue 静态文件，反代 `/api` |
| backend | 8000 | FastAPI 控制 API（内部用） |
| mediamtx | 1935 / 8554 / 8889 / 9997 | RTMP / RTSP / WebRTC / API |
| worker | 无 | 拉 `drone1`、画框、推 `drone1_yolo` |

所有服务都用 `network_mode: host`：

- MediaMTX 需要它来避免 WSL2 下 WebRTC/UDP 的 NAT 问题；
- Windows FFmpeg 通过 `localhost:1935` 推流；
- 其余服务用 `127.0.0.1` 互访最简单。

## 直接调 API

只有算法启停：

```bash
curl -s http://127.0.0.1:8000/api/status

curl -s -X POST http://127.0.0.1:8000/api/algorithm/start
curl -s -X POST http://127.0.0.1:8000/api/algorithm/stop
```

## 前端开发模式（可选）

后端仍在容器里，Vite 只负责热更新：

```powershell
cd E:\Pycharm\docker-demo2\frontend
npm install
npm run dev
```

打开 `http://127.0.0.1:5173`，`/api` 会代理到 `127.0.0.1:8000`。

改完后重建前端容器：

```bash
docker compose build frontend
docker compose up -d frontend
```

## 配置

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `MEDIAMTX_API` | `http://127.0.0.1:9997` | backend 查流状态 |
| `WORKER_CONTAINER` | `drone-worker` | backend 控制的容器名 |
| `DRONE_SOURCE` | `rtsp://127.0.0.1:8554/drone1` | worker 拉流地址 |
| `DRONE_DEST` | `rtmp://127.0.0.1:1935/drone1_yolo` | worker 推流地址 |

推流参数在 `scripts/push-windows.ps1` 里改（分辨率、帧率、码率、地址）。

前端构建默认用 npmmirror；需要换源时：

```bash
docker compose build --build-arg NPM_REGISTRY=https://registry.npmjs.org frontend
```

## 验证

```bash
docker compose ps
docker logs --tail 20 drone-backend
docker logs --tail 20 drone-worker

curl -s http://127.0.0.1:8000/api/status
curl -s http://127.0.0.1:8080/api/status
```

Windows 侧确认流可读：

```powershell
ffprobe -v error -rtsp_transport tcp -show_streams rtsp://localhost:8554/drone1
ffprobe -v error -rtsp_transport tcp -show_streams rtsp://localhost:8554/drone1_yolo
```

## 排障

| 现象 | 处理 |
| --- | --- |
| 页面一直“等待信号源” | 检查 Windows 推流脚本是否在跑、`localhost:1935` 是否可达 |
| 启动算法报“信号源未上线” | 先让 `drone1` 上线再点，或直接调 API |
| 启动算法报“容器不存在” | `docker compose down` 删掉了 worker，重新 `up -d` |
| 8080 / 8000 被占用 | 改 nginx `listen` 和 backend 端口，同步改 nginx 反代 |
| backend 日志 permission denied | Docker socket 权限问题，确认容器以 root 运行 |
| 页面能开但黑屏 | 检查 8889 是否可达；MediaMTX 的 WebRTC TCP 兜底是否在监听 |

## 停止

```bash
docker compose down
```

Windows 推流窗口按 `Ctrl+C`，或直接关闭窗口。

## 安全说明

backend 挂载了 `/var/run/docker.sock`，等于拥有宿主机 Docker 控制权。
本项目只监听本机、仅用于演示；不要把这个 compose 直接暴露到公网。

## 目录

```text
assets/                 本地视频（不入库）
deploy/mediamtx/        MediaMTX 配置
scripts/                Windows 推流脚本（设备模拟）
worker/                 YOLO 模拟端（uv 项目 + Dockerfile）
backend/                控制 API（FastAPI + Docker SDK）
frontend/               Vue 3 + Vite + nginx
docs/                   需求文档
```
