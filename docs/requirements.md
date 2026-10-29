# 无人机直播与 YOLO 检测本地模拟系统 —— 需求规格说明书

| 项目 | 内容 |
| --- | --- |
| 文档版本 | v0.5 |
| 文档状态 | 草案（待评审） |
| 编写日期 | 2026-10-28 |
| 适用阶段 | 本地模拟验证（M0–M5） |
| 关联文档 | `README.md`、`architecture.md`（待建）、`runbook.md`（待建） |

> 约定：本文用“必须（MUST）/应当（SHOULD）/可以（MAY）”区分强制程度；“本期”指本地模拟版本，“生产”指接入真实机场与公网服务器的版本。
>
> **实现变更（v0.5）**：推流改回 Windows 侧独立运行，模拟真实机场/无人机，平台不控制推流；前端只保留算法启停与观看。前后端仍运行在容器中，backend 通过 Docker socket 启停 worker。

## 0. 修订记录

| 版本 | 日期 | 说明 |
| --- | --- | --- |
| v0.1 | 2026-10-28 | 初稿：两条链路、本机模拟约束、接口与验收标准 |
| v0.2 | 2026-10-28 | 推流端改为 Windows FFmpeg（容器外）；`source` 容器降为可选 profile；G3 改为两个独立播放页 |
| v0.3 | 2026-10-28 | 移除 `services/source` 与 `.env.example`；默认 compose 仅保留 MediaMTX |
| v0.4 | 2026-10-28 | 前后端容器化；推流移入 backend 容器；backend 经 Docker socket 控制 worker；控制台 8080 |
| v0.5 | 2026-10-29 | 推流回到 Windows 侧独立运行；前端不再控制推流，只保留算法启停与观看 |

## 1. 背景与目标

### 1.1 背景

公司需要评估两项能力：

1. 无人机/机场的实时画面能在普通浏览器中低延迟查看，无需安装插件；
2. 在实时画面上叠加 YOLO 检测结果，为后续智能分析（人员、车辆、目标告警等）做技术验证。

完整生产链路依赖大疆机场、DJI Cloud API、公网流媒体服务器与公网 IP。当前不具备这些条件：

- 没有大疆无人机/机场，只有一段航拍视频可用于模拟；
- 开发机为 Windows 11 + WSL2 + Docker + 单张 RTX 4050 Laptop（6 GB 显存）；
- 没有公网 IP，浏览器与服务只能在本机回环或局域网内访问。

因此本期用“本地视频文件循环推流”替代机场推流，用“本机回环网络”替代公网，在同一台开发机上完整复现两条链路，并保留切换到真实机场/Cloud API 的接缝。

### 1.2 目标

| 编号 | 目标 |
| --- | --- |
| G1 | 链路 A（原画）：视频文件 → 流媒体服务器 → 浏览器 WebRTC 播放，端到端延迟 P95 ≤ 1 s。 |
| G2 | 链路 B（检测画）：视频文件 → 流媒体服务器 → YOLO 服务拉流、推理、画框、重新编码推流 → 流媒体服务器 → 浏览器，检测框与画面目标同步，相对原画附加延迟 ≤ 500 ms。 |
| G3 | 一条命令启动全部服务；浏览器通过两个独立播放页分别查看原画与检测画（P0）；单页并排对比作为 P1 增强。 |
| G4 | 结构上保留“替换为真实机场/DJI Cloud API”的接缝：替换视频源与控制适配层即可，播放端与 YOLO 服务不改。 |
| G5 | 产出可复现的代码、配置、运行手册与验收记录。 |

### 1.3 成功标准

在无无人机、无公网 IP 的条件下：

- 执行 `docker compose up -d` 后，浏览器能在 3 s 内看到原画；
- 原画与检测画可分别在两个独立页面播放，检测框稳定跟随目标，肉眼无明显滞后；P1 提供单页并排对比；
- 延迟、帧率、资源占用满足第 8 章指标；
- 断开视频源再恢复后，两条链路无需人工重启即可自动恢复；
- 按第 10.5 节替换推流端后，系统可接收真实机场推流。

### 1.4 非目标

以下内容本期不做，避免范围蔓延：

- 不接入真实大疆机场/无人机，不实现完整 DJI Cloud API（MQTT/HTTPS 全量协议）；
- 不实现 GB28181 信令与国标接入；
- 不做录像、回放、截图、告警推送、数据库存储；
- 不做用户体系、鉴权、租户隔离；
- 不做公网部署、HTTPS 证书、TURN/STUN、域名与反向代理；
- 不做模型训练、微调、数据集标注；
- 不做多路并发与 GPU 多卡调度（预留扩展点即可）；
- 不做移动端适配与 Safari/Firefox 全量兼容验证；
- 不引入 Kubernetes、消息队列、数据库等重型基础设施。

## 2. 术语

| 术语 | 说明 |
| --- | --- |
| 机场（Dock） | 大疆机场，负责无人机起降、充电与视频回传。本期由本地视频文件模拟。 |
| DJI Cloud API | 大疆上云 API，通过 MQTT/HTTPS 下发 `live_start`、`live_stop` 等直播指令。 |
| RTMP | 基于 TCP 的推流协议，默认端口 1935。 |
| RTSP | 基于 TCP/UDP 的流控制协议，默认端口 8554；本期 YOLO 拉流使用 TCP。 |
| WebRTC | 浏览器原生实时音视频协议，低延迟，无需插件。 |
| WHEP | WebRTC-HTTP Egress Protocol，浏览器通过 HTTP 与流媒体服务器完成 WebRTC 播放协商。 |
| HLS / LL-HLS | 基于 HTTP 的分片播放协议；LL-HLS 为低延迟变体，作为 WebRTC 的兜底。 |
| MediaMTX | 开源流媒体服务器，内置 RTSP/RTMP/HLS/WebRTC/SRT 与 WHEP。 |
| YOLO | 单阶段目标检测模型，本期使用 Ultralytics YOLO11 系列预训练模型。 |
| 端到端延迟 | 画面从源（视频文件当前帧）到浏览器显示的时间差。 |
| 附加延迟 | 检测画相对原画的延迟增量，即解码 + 推理 + 画框 + 编码 + 再分发的耗时。 |
| 玻璃到玻璃（glass-to-glass） | 从显示设备上的源画面到浏览器显示画面的总延迟。 |

## 3. 范围与假设

### 3.1 本期范围

| 类别 | 内容 |
| --- | --- |
| 视频源 | 本地视频文件循环推流；无文件时可用测试图案（带毫秒时钟）替代。 |
| 流媒体 | RTMP 接收、RTSP 分发、WebRTC/WHEP 播放、LL-HLS 兜底。 |
| 原画链路 | 浏览器播放原始流，支持自动重连与状态显示。 |
| 检测链路 | YOLO 拉流、逐帧推理、画框、H.264 编码、回推、浏览器播放。 |
| 编排 | Docker Compose 一键启动/停止；默认起 MediaMTX，worker 可本地跑或按 service 启动。 |
| 控制 | 本地 REST 控制 API，模拟 `live_start`/`live_stop` 语义。 |
| 观测 | 健康检查、容器日志、MediaMTX 与 YOLO 指标。 |
| 文档 | 需求、架构、运行手册、验收记录。 |

### 3.2 假设

| 编号 | 假设 | 影响 |
| --- | --- | --- |
| A1 | 用户提供一段 16:9 航拍视频，分辨率不高于 4K，时长 ≥ 30 s | 无视频时先用测试图案开发，不阻塞 |
| A2 | 浏览器为 Windows 上的 Chrome/Edge 最新稳定版 | WebRTC/WHEP 与 H.264 解码能力有保障 |
| A3 | 仅本机访问，不做鉴权 | 安全要求降级，生产必须补齐 |
| A4 | 单路视频流（1 路原画 + 1 路检测画） | 不验证并发与调度 |
| A5 | 检测使用 COCO 预训练权重，类别可按需过滤 | 不训练自定义模型 |
| A6 | MediaMTX/YOLO 运行在 WSL2 Docker；推流端使用 Windows FFmpeg | 推流命令在 Windows PowerShell 执行，其余在 WSL |
| A7 | 首次运行允许联网拉取镜像与模型，之后可离线 | 需提前缓存镜像/权重 |

## 4. 目标形态与本期模拟形态

| 维度 | 生产形态（目标） | 本期模拟形态 |
| --- | --- | --- |
| 视频源 | 大疆机场/无人机相机 | 本地视频文件由 **Windows FFmpeg** 循环推流（容器外） |
| 推流发起 | DJI Cloud API 下发 `live_start`，机场主动推流 | Windows PowerShell 脚本启动 FFmpeg 即推流；控制 API 模拟指令 |
| 控制通道 | MQTT/HTTPS + 设备拓扑 | 本地 REST + Compose |
| 流媒体服务器 | 公网服务器上的 MediaMTX/SRS/ZLMediaKit | WSL2 Docker 内的 MediaMTX |
| 浏览器访问 | 公司 PC → 公网域名/IP | Windows 浏览器 → `localhost` / WSL IP |
| 网络条件 | 公网 IP、带宽、NAT 穿透、TLS | 无公网 IP，仅本机回环 |
| 鉴权 | 必须（设备证书、Token、播放鉴权） | 无 |
| 规模 | 多机场、多路并发 | 单路 |
| 图像识别 | 独立 GPU 推理服务 | 同一台机器的 Docker GPU 容器 |

> 结论：本期验证的是“协议链路、延迟可行性、YOLO 叠加效果与部署形态”，不验证公网穿透、鉴权与大规模并发。

## 5. 运行环境与约束

### 5.1 实测环境

| 项 | 实测值 | 说明 |
| --- | --- | --- |
| 操作系统 | Windows 11（build 26200.9711） | 仅运行浏览器与编辑器 |
| WSL | WSL 2，Ubuntu 26.04.1 LTS，内核 6.18.54.1-1 | 所有容器与命令在此执行 |
| Docker | 29.7.2（WSL 内原生 Docker，systemd 管理） | Windows 侧无 Docker CLI |
| Docker Compose | v5.5.0 | 使用 `docker compose` 子命令 |
| GPU | NVIDIA GeForce RTX 4050 Laptop，6141 MiB | 支持 FP16 与 NVENC H.264 |
| 驱动 | 566.26（Windows 驱动透传至 WSL） | `nvidia-smi` 在 WSL 内可用 |
| 磁盘 | WSL 根分区约 953 GB 可用 | 镜像与模型空间充足 |
| FFmpeg | Windows 侧 9.0.2（gyan.dev full build）；WSL 内未安装 | 推流使用 Windows FFmpeg，MediaMTX/YOLO 仍运行在 WSL |
| 网络 | WSL IP `172.28.125.20`（每次启动可能变化），无公网 IP | 见 5.3 |
| 项目路径 | Windows `E:\Pycharm\docker-demo2`，WSL `/mnt/e/Pycharm/docker-demo2` | 见 5.4 |

### 5.2 环境缺口（开发前置任务）

| 编号 | 缺口 | 影响 | 处理 |
| --- | --- | --- | --- |
| E1 | 未安装 `nvidia-container-toolkit` | 容器内无法使用 GPU，YOLO 只能跑 CPU | M1 安装并用 `docker run --gpus all` 验证 |
| E2 | WSL 内无 FFmpeg | 不能在 WSL 直接推流 | 推流改用 Windows FFmpeg |
| E3 | 视频素材已提供 | `assets/drone.mp4`，640×368@24，H.264，85 s | 已可直接验证；真实机场素材后续替换 |
| E4 | 无公网 IP | 无法复现公网推流与外部访问 | 本期用本机回环模拟，生产差异见第 4 章 |
| E5 | WSL 与 Windows 文件系统跨挂载 | `/mnt/e` 上的大文件 I/O 较慢 | 视频/模型建议放 WSL 原生路径或 Docker volume |

### 5.3 网络可达性（WSL2 / 无公网 IP）

WSL2 默认使用 NAT 网络：WSL 有独立虚拟网卡与 IP，Windows 通过 `localhostForwarding` 把 WSL 内监听的 **TCP** 端口映射到 Windows 的 `localhost`；**UDP 不做 localhost 转发**。WebRTC 默认走 UDP，因此必须显式处理，否则浏览器会出现“信令成功但黑屏”。

| 访问路径 | TCP | UDP | 结论 |
| --- | --- | --- | --- |
| Windows 浏览器 → `localhost:<port>`（WSL 端口转发） | 可用 | 不可用 | WHEP 信令可用；ICE 必须走 TCP |
| Windows 浏览器 → WSL IP `172.28.x.x:<port>` | 可用 | 可用 | 可用于 UDP 媒体，但 IP 会变化 |
| WSL 内进程 → `localhost` | 可用 | 可用 | 容器间与自动化测试使用 |
| 局域网其他设备 → Windows | 需额外端口代理/防火墙 | 不可用 | 非本期目标 |

**推荐基线（按优先级）：**

1. **host 网络（本期默认）**：`mediamtx` 使用 `network_mode: host`，MediaMTX 直接绑定 WSL 网卡并广播当前 WSL IP；Windows 浏览器经 `localhost:8889` 打开播放页，媒体优先走 WSL IP 的 UDP，同时开启 TCP 8189 兜底。Windows FFmpeg 通过 `localhost:1935` 推流。该方案没有 Docker NAT/端口映射，是 WSL2 本地模拟最稳的组合。
2. **bridge + ICE/TCP + localhost**：MediaMTX 同时开启 `webrtcLocalUDPAddress` 与 `webrtcLocalTCPAddress`（均 `:8189`），并配置 `webrtcAdditionalHosts: [127.0.0.1]`；浏览器经 `localhost:8889` 完成 WHEP，媒体走 TCP 8189 的 localhost 转发。该方案不依赖会变化的 WSL IP，适合需要容器网络隔离时使用。
3. **bridge + WSL IP + UDP**：在 `webrtcAdditionalHosts` 中加入 WSL IP，浏览器访问 `http://<WSL_IP>:8889/...`，媒体走 UDP，延迟最低；需在启动脚本中动态获取 IP。
4. **WSL 镜像网络（可选）**：在 `%UserProfile%\.wslconfig` 中设置 `networkingMode=mirrored`，使 localhost 的 UDP 也可用；需注意 Hyper-V 防火墙提示与端口冲突。
5. **LL-HLS 兜底**：若 WebRTC 协商失败，播放页回退到 `http://localhost:8888/<stream>/index.m3u8`，延迟约 2–4 s。

> 该结论依据 MediaMTX 官方文档：WebRTC 可通过静态 TCP 端口建立连接；bridge 场景需同时映射 UDP/TCP 8189，并通过 `webrtcAdditionalHosts` 告知客户端可达地址。见第 17 节参考链接。

### 5.4 文件系统与性能约束

- Docker 运行在 WSL 内，不是 Docker Desktop；**所有 `docker compose` 命令必须在 WSL Ubuntu 中执行**。
- 项目位于 `/mnt/e/...`（DrvFs）。小文件读写、`inotify`、文件锁行为与原生 ext4 有差异；视频与模型建议复制到 WSL 原生路径（如 `~/drone-demo/assets`）或使用 Docker volume，避免推流卡顿。
- Windows 编辑器保存的 `.sh` 可能带 CRLF，导致容器内 `#!/bin/bash^M` 启动失败；仓库必须提交 `.gitattributes`，强制 `*.sh text eol=lf`，必要时在 CI/脚本中执行 `dos2unix`。
- 6 GB 显存为笔记本 GPU 上限，Windows 桌面、浏览器硬件加速会占用部分显存；YOLO 必须使用 `batch=1`、FP16，并限制模型规模。

### 5.5 其他约束

- 流媒体服务器只做协议转换与分发，**不得**在其中运行图像识别（职责分离）。
- 浏览器不能直接播放 RTSP/RTMP，必须由服务器转为 WebRTC/HLS。
- 本期所有端口仅绑定本机回环或 WSL 网卡，不得直接暴露到公网。
- 视频素材可能涉及隐私/版权，不得提交到代码仓库，`.gitignore` 必须排除 `assets/*.mp4`、`models/*.pt`。

## 6. 总体架构

### 6.1 组件

| 组件 | 技术 | 职责 | 是否本期 |
| --- | --- | --- | --- |
| 推流端（Windows FFmpeg） | Windows FFmpeg（容器外） | 读取本地视频，循环、转码、按实时速率推 RTMP | 是 |
| `mediamtx` | MediaMTX | 接收 RTMP，提供 RTSP 分发、WebRTC/WHEP、LL-HLS、控制 API 与指标 | 是 |
| `yolo` | Python + Ultralytics + FFmpeg | 拉 RTSP、解码、推理、画框、H.264 编码、回推 RTSP | 是 |
| `web` | Nginx + 原生 JS | 统一播放页（原画 + 检测画）、状态与延迟显示 | 是（P1） |
| `control` | FastAPI | 模拟 `live_start`/`live_stop`，返回播放地址，编排推流/yolo | 是（P1） |

### 6.2 链路 A：原画

```text
[Windows]
   FFmpeg（循环推流） ── RTMP 1935 ──▶  MediaMTX（WSL2 / Docker）
   浏览器 ◀── WebRTC 8889 / 8189 ────────────┘
                    │
                    └── RTSP 8554 / HLS 8888
```

1. Windows 侧运行 `scripts/push-windows.ps1`，FFmpeg 以 `-re` 按实时速率读取视频，转码为 H.264（无 B 帧），推 `rtmp://localhost:1935/drone1`（经 WSL 的 TCP 转发到达 MediaMTX）。
2. MediaMTX 建立路径 `drone1`，同时提供 RTSP、HLS、WebRTC 三种读取方式。
3. 浏览器加载 WHEP 客户端，向 MediaMTX 发送 SDP Offer；MediaMTX 返回 Answer 并建立 ICE 连接。
4. 媒体经 TCP/UDP 8189 传输，浏览器解码显示。服务器全程只做协议转换与转发。

### 6.3 链路 B：检测画

```text
[Windows 浏览器]
   │ ① WHEP 信令  http://localhost:8889/drone1_yolo/whep
   │ ② WebRTC 媒体  TCP 8189 / UDP 8189
   ▼
[WSL2 / Docker]
   MediaMTX /drone1_yolo  ──▶ 浏览器
      ▲
      │ RTSP 推流（H.264）
   yolo 服务（GPU）
      │ 解码 → YOLO 推理 → 画框 → 编码
      ▲
      │ RTSP 拉流（TCP）
   MediaMTX /drone1  ◀── RTMP ── Windows FFmpeg
```

1. 与链路 A 相同，Windows FFmpeg 推流到 MediaMTX 的 `drone1`。
2. `yolo` 服务以 RTSP/TCP 拉取 `rtsp://127.0.0.1:8554/drone1`。
3. 逐帧解码，送入 YOLO 推理，得到目标框、类别、置信度。
4. 在帧上绘制框与标签，编码为 H.264（优先 NVENC），推 `rtsp://127.0.0.1:8554/drone1_yolo`。
5. MediaMTX 将 `drone1_yolo` 通过 WebRTC 分发给浏览器。
6. 浏览器看到的是已叠加检测框的画面；原画链路不受影响。

### 6.4 组件职责边界

| 组件 | 必须做 | 不得做 |
| --- | --- | --- |
| 推流端（Windows FFmpeg） | 循环读取、转码、实时推流、断线重试 | 不做推理、不做分发 |
| `mediamtx` | 协议转换、路径管理、鉴权（生产）、分发 | 不做图像识别、不修改画面 |
| `yolo` | 拉流、推理、画框、编码、回推、自愈 | 不直接面向浏览器、不存储视频 |
| `web` | 播放、状态展示、错误提示 | 不参与媒体转发 |
| `control` | 启停编排、返回地址、模拟 DJI 语义 | 不承载媒体流 |

### 6.5 关键时序

**原画播放**

1. 浏览器 GET `http://localhost:8080/`，加载页面与 WHEP 客户端。
2. 页面探测 `GET http://localhost:9997/v3/paths/list`，确认 `drone1` 在线。
3. 页面 POST SDP Offer 到 `http://localhost:8889/drone1/whep`。
4. ICE 协商（TCP 候选优先），建立 PeerConnection。
5. `ontrack` 触发，`<video>` 播放；`getStats()` 周期刷新 FPS/RTT。
6. 路径消失时页面显示“信号中断”，并按 1/2/5 s 退避重连。

**检测流启动**

1. 推流成功，`drone1` 就绪。
2. `yolo` 拉流成功，加载模型（首次需下载/缓存）。
3. 首帧推理完成，推流 `drone1_yolo`，`/readyz` 返回 200。
4. 浏览器播放 `drone1_yolo`；若源中断，YOLO 保持重连，编码器随首帧恢复。

### 6.6 与原始设想的对应关系

| 原始设想 | 本文落点 | 本期处理 |
| --- | --- | --- |
| Cloud API 下发直播指令（MQTT/HTTPS） | FR-10 控制 API、10.4 指令模拟 | 用 REST 模拟，字段语义对齐，MQTT 留到生产 |
| 机场推 RTMP/RTSP/GB28181 | FR-01 视频源模拟 | 本期仅 RTMP；GB28181 明确不支持 |
| 流媒体服务器转协议 | FR-02 MediaMTX | RTMP 入、RTSP/HLS/WebRTC 出 |
| 浏览器 WebRTC 低延迟播放 | FR-03/FR-05、7.5 | WHEP + ICE/TCP 基线 |
| YOLO 拉流、推理、画框、再推流 | FR-04 | GPU 推理 + NVENC/libx264 |
| 服务器只做协议转换，不做识别 | 6.4 职责边界 | 强制约束 |
| 公网 IP 访问 | 第 4 章、10.5 | 本期本机回环，生产差异单列 |

## 7. 功能需求

### 7.1 优先级定义

| 优先级 | 含义 |
| --- | --- |
| P0 | MVP 必须；缺失则无法验收 |
| P1 | 本期应当完成；可在核心链路之后补 |
| P2 | 后续/生产增强；本期不做 |

### 7.2 需求清单

| 编号 | 名称 | 优先级 | 一句话描述 |
| --- | --- | --- | --- |
| FR-01 | 视频源模拟 | P0 | 循环推送本地视频或测试图案到 MediaMTX |
| FR-02 | 流媒体接入与分发 | P0 | RTMP 入、RTSP/HLS/WebRTC 出，路径隔离 |
| FR-03 | 原画播放 | P0 | 浏览器免插件播放 `drone1`，自动重连 |
| FR-04 | YOLO 推理与渲染 | P0 | 拉流、推理、画框、编码、回推 `drone1_yolo` |
| FR-05 | 检测画播放 | P0 | 浏览器播放 `drone1_yolo`，可与原画对比 |
| FR-06 | 检测参数配置 | P1 | 模型、置信度、IOU、类别、画框样式可配 |
| FR-07 | 断流自愈 | P0 | 源中断后两条链路自动恢复，无需重启容器 |
| FR-08 | 一键启动/停止 | P0 | Compose 启动 MediaMTX；worker 可选本地运行或 `--build worker` |
| FR-09 | 健康检查与指标 | P1 | `/healthz`、`/readyz`、Prometheus 指标 |
| FR-10 | 控制 API（DJI 适配层） | P1 | start/stop/list，返回播放地址，模拟 `live_start` |
| FR-11 | 统一控制台 | P1 | 单页并排播放原画与检测画 |
| FR-12 | 文档与脚本 | P0 | README、运行手册、验证脚本、验收记录 |
| FR-13 | 环境自检 | P0 | 启动前检查 Docker/GPU/端口/素材，给出可操作错误 |

### 7.3 FR-01 视频源模拟

| 项 | 要求 |
| --- | --- |
| 输入模式 | `file`：循环读取本地文件；`test`：生成带毫秒时钟的测试图案；`passthrough`：不启动推流，等待外部推流 |
| 循环 | 文件播放到结尾后循环推流（允许关键帧处轻微跳变），持续到停止 |
| 实时性 | 使用 `-re` 按源帧率读取，避免瞬间推完导致播放端加速 |
| 归一化 | 输出 1920×1080、25 fps、H.264、`yuv420p`、无 B 帧、GOP=25、约 4 Mbps；保持 16:9，必要时加黑边，不拉伸 |
| 音频 | 本期默认 `-an` 去掉音频，避免 WebRTC 音频编解码兼容问题；P2 再支持 Opus |
| 本期实现 | Windows FFmpeg 脚本 `scripts/push-windows.ps1` 负责循环推流与重试 |
| 失败处理 | 文件不存在时脚本报错退出；推流中断后脚本每 2 s 重试；容器回退方案用 `restart: unless-stopped` |
| 断线重试 | Windows 脚本在 FFmpeg 退出后 2 s 重启；不依赖容器重启 |
| 可配置 | 视频路径、推流地址、分辨率、帧率、码率、preset 通过 PowerShell 参数配置；容器方案用环境变量 |

**验收要点**：`ffprobe rtsp://localhost:8554/drone1` 能识别 H.264 1920×1080 25 fps；浏览器播放不加速、不花屏；断源后自动重连。

### 7.4 FR-02 流媒体接入与分发

| 项 | 要求 |
| --- | --- |
| 协议 | RTMP 推流（1935）、RTSP 拉流（8554）、HLS/LL-HLS（8888）、WebRTC/WHEP（8889）、WebRTC 媒体（8189 UDP+TCP） |
| 路径 | `drone1`（原画）、`drone1_yolo`（检测画）；路径不存在时返回明确状态而非挂起 |
| 鉴权 | 本期关闭，仅本机访问；生产必须启用发布/播放鉴权 |
| 跨域 | WHEP 允许来自 `http://localhost:8080` 的跨域请求（本地可临时 `*`） |
| HLS | 启用低延迟变体，分片 1 s，作为 WebRTC 失败时的兜底 |
| 状态接口 | 暴露 MediaMTX Control API（9997），供控制台查询路径在线状态 |
| 指标 | 暴露 `/metrics`（9998）供排障 |
| 职责 | 只做协议转换与分发，不得运行推理代码 |

**验收要点**：RTMP 推流后，RTSP、HLS、WebRTC 三种方式都能拉到同一画面；停止推流后路径状态变为离线。

### 7.5 FR-03 / FR-05 浏览器播放

| 项 | 要求 |
| --- | --- |
| 播放方式 | WebRTC（WHEP）优先；失败或 5 s 未出画时自动切 LL-HLS |
| 免插件 | 不依赖任何浏览器扩展、ActiveX、本地播放器 |
| 自动播放 | `<video muted autoplay playsinline>`，规避浏览器自动播放策略；提供手动播放按钮 |
| 重连 | 路径离线或 PeerConnection 断开时，按 1/2/5 s 退避重连，显示“重连中” |
| 状态 | 显示流名称、在线/离线、分辨率、帧率、RTT、缓冲区延迟（能取到则显示） |
| 对比 | 原画与检测画各有一个独立播放页，可并排两个窗口对比；P1 提供单页同屏对比 |
| 兼容 | Chrome/Edge 最新稳定版，窗口 1920×1080 下布局正常 |
| 错误提示 | 区分“流未启动”“WebRTC 协商失败”“浏览器不支持 H.264”等场景 |

**验收要点**：Chrome 打开后 3 s 内出画；拔掉源后页面提示离线，恢复后自动复播；检测画无插件播放。

### 7.6 FR-04 YOLO 推理与渲染

| 项 | 要求 |
| --- | --- |
| 拉流 | `rtsp://127.0.0.1:8554/drone1`，强制 TCP；设置低延迟参数（关闭缓冲、减小 probe） |
| 解码 | 逐帧解码；优先保证实时性，允许丢弃陈旧帧 |
| 模型 | Ultralytics YOLO11n（默认），可配置为 `yolo11s` 或其他同系列权重；COCO 80 类 |
| 推理 | `imgsz=640`、FP16、`batch=1`、`device=0`；置信度/IoU/类别过滤可配 |
| 画框 | 矩形框 + 类别名 + 置信度；颜色按类别稳定；线宽/字号随分辨率缩放；文字有底色保证可读 |
| 编码 | H.264、`yuv420p`、无 B 帧、GOP=25；优先 `h264_nvenc`，不可用时回退 `libx264 -preset ultrafast -tune zerolatency` |
| 推流 | `rtsp://127.0.0.1:8554/drone1_yolo`，断线自动重启编码器 |
| 背压 | 内部帧队列长度 ≤ 1；推理吞吐低于源帧率时丢帧，不累积延迟 |
| 自愈 | 源 EOF/网络错误后按 1/2/5 s 退避重连；编码失败重建 FFmpeg 进程 |
| 降级 | GPU 不可用时允许 `DEVICE=cpu` 降级运行（帧率下降但链路可用），P1 |
| 可观测 | `/healthz`、`/readyz`、`/metrics`；日志包含重连、丢帧、推理耗时 |
| 资源 | 显存 ≤ 4 GB，CPU 占用可控，连续运行无句柄/内存泄漏 |

**验收要点**：`ffprobe rtsp://localhost:8554/drone1_yolo` 有 H.264 视频；浏览器中框随目标移动，类别与置信度正确；遮挡/出画时框消失；源恢复后自动续播。

### 7.7 FR-06 检测参数配置

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `MODEL` | `yolo11n.pt` | 权重文件名或路径；挂载 `models/` 缓存 |
| `IMGSZ` | `640` | 推理输入尺寸 |
| `CONF` | `0.25` | 置信度阈值 |
| `IOU` | `0.45` | NMS IoU 阈值 |
| `CLASSES` | 空（全部） | 逗号分隔的类别 ID 或名称，如 `person,car,truck,bus` |
| `DEVICE` | `0` | `0` 表示第一块 GPU，`cpu` 表示 CPU |
| `HALF` | `true` | FP16 推理 |
| `DRAW_LABELS` | `true` | 是否绘制类别/置信度文本 |
| `BOX_THICKNESS` | 自动 | 线宽，默认按分辨率计算 |

**要求**：修改环境变量并重启 `yolo` 服务即可生效，无需改代码、无需重建镜像。类别过滤在推理后、绘制前执行，减少误检干扰。

### 7.8 FR-07 断流自愈

| 场景 | 期望行为 |
| --- | --- |
| Windows FFmpeg 停止 10 s | MediaMTX 路径离线；播放页显示“信号中断”；`yolo` 保持重连，不退出 |
| 重新运行 `push-windows.ps1` | `drone1` 重新上线；`yolo` 在 ≤10 s 内恢复拉流与推流；播放页自动复播 |
| `yolo` 崩溃 | Compose 自动重启容器；恢复后自动重新拉流 |
| MediaMTX 重启 | 推流脚本自动重试，`yolo` 自动重连，无需人工干预 |
| 网络抖动 | 短暂卡顿后恢复，允许一次关键帧等待，不出现永久黑屏 |

**约束**：自愈过程中不得产生无限重试风暴；退避上限 10 s；日志必须记录每次重连原因。

### 7.9 FR-08 一键启动/停止

| 命令 | 行为 |
| --- | --- |
| `docker compose up -d` | 只启动 mediamtx |
| `docker compose --profile yolo up -d` | 追加 yolo 服务 |
| `docker compose --profile control up -d` | 追加控制 API |
| `docker compose down` | 停止并移除容器；默认保留模型/视频卷 |
| `docker compose ps` | 展示健康状态 |
| `./scripts/doctor.sh` | 环境自检（Docker、Compose、GPU、端口、素材、CRLF） |

**要求**：所有服务配置 `restart: unless-stopped`；YOLO 只依赖流路径，不依赖推流方式；健康检查就绪后再标记 healthy；日志可在 `docker compose logs -f` 中查看。

### 7.10 FR-09 健康检查与指标

| 服务 | 端点 | 语义 |
| --- | --- | --- |
| `yolo` | `GET /healthz` | 进程存活，返回 200 |
| `yolo` | `GET /readyz` | 模型已加载且已处理首帧，返回 200；否则 503 |
| `yolo` | `GET /metrics` | Prometheus 文本格式 |
| `mediamtx` | `GET :9997/v3/paths/list` | 路径在线状态 |
| `mediamtx` | `GET :9998/metrics` | 连接数、字节数、错误数 |
| `web` | `GET /` | 静态页可访问 |

**YOLO 指标（至少）**：`yolo_frames_in_total`、`yolo_frames_out_total`、`yolo_frames_dropped_total`、`yolo_infer_seconds`（直方图）、`yolo_reconnects_total`、`yolo_last_frame_timestamp_seconds`。

### 7.11 FR-10 控制 API（DJI 适配层）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/v1/health` | 控制服务健康 |
| `GET` | `/api/v1/streams` | 列出流及状态、播放地址 |
| `POST` | `/api/v1/streams/{id}/start` | 启动推流与（可选）YOLO；幂等，已运行返回 200 |
| `POST` | `/api/v1/streams/{id}/stop` | 停止推流与 YOLO；幂等 |
| `GET` | `/api/v1/streams/{id}` | 单流状态 |
| `GET` | `/api/v1/capacity` | 模拟 `live_capacity`，返回可用路数与 GPU 状态 |

**状态机**：`idle → starting → running → degraded → stopped`，异常进入 `error`。

**响应示例**

```json
{
  "stream_id": "drone1",
  "state": "running",
  "urls": {
    "webrtc": "http://localhost:8889/drone1",
    "whep": "http://localhost:8889/drone1/whep",
    "hls": "http://localhost:8888/drone1/index.m3u8",
    "rtsp": "rtsp://localhost:8554/drone1"
  },
  "yolo": {
    "enabled": true,
    "stream_id": "drone1_yolo",
    "webrtc": "http://localhost:8889/drone1_yolo"
  }
}
```

**DJI 语义映射**

| DJI Cloud API | 本模拟 |
| --- | --- |
| `live_start`（`url_type`、`url`、`video_id`） | `POST /api/v1/streams/{id}/start` |
| `live_stop`（`video_id`） | `POST /api/v1/streams/{id}/stop` |
| `live_capacity` | `GET /api/v1/capacity` |
| MQTT `thing/product/{sn}/services` | P2 可选，用一个 MQTT 桥接器对接 |

**要求**：字段命名与 DJI 语义保持可映射；真实接入时替换适配层，不改播放端与 YOLO 服务。具体字段以 DJI Cloud API 官方文档为准，本期不实现完整协议。

### 7.12 FR-11 统一控制台

| 项 | 要求 |
| --- | --- |
| 布局 | 左右两路 `<video>`：左“原画”，右“YOLO 检测”；上方标题与在线状态 |
| 地址 | `http://localhost:8080/` |
| 同源策略 | WHEP 地址基于 `window.location.hostname` 拼接，兼容 localhost 与 WSL IP |
| 状态 | 每路显示在线/离线、分辨率、FPS、RTT、丢帧；数据来自 `getStats()` 与 MediaMTX API |
| 控制 | 提供“重连”“切换 HLS/WebRTC”按钮；P1 可加“启动/停止 YOLO” |
| 依赖 | 不依赖公网 CDN；`hls.js` 等静态资源本地化，保证离线可用 |
| 降级 | WebRTC 失败时自动切 HLS，并在界面提示原因 |

### 7.13 FR-12 文档与脚本

| 交付物 | 内容 |
| --- | --- |
| `README.md` | 5 分钟快速开始、端口说明、常见问题 |
| `docs/requirements.md` | 本文 |
| `docs/architecture.md` | 组件图、时序、数据流、关键决策 |
| `docs/runbook.md` | 启动/停止/排障/验收步骤 |
| `scripts/doctor.sh` | 环境自检 |
| `scripts/gen-test-video.sh` | 生成带毫秒时钟的测试视频 |
| `scripts/healthcheck.sh` | 检查所有 URL 与端口 |
| `scripts/soak.sh` | 2 小时稳定性测试 |
| `tests/` | 接口与 URL 冒烟测试 |

### 7.14 FR-13 环境自检

`scripts/doctor.sh` 必须逐项检查并给出可操作建议：

| 检查项 | 通过条件 | 失败提示 |
| --- | --- | --- |
| 运行位置 | 在 WSL 内执行 | 提示“请在 WSL Ubuntu 中运行，Windows 无 Docker CLI” |
| Docker | `docker info` 成功 | 提示启动 Docker |
| Compose | `docker compose version` 成功 | 提示安装插件 |
| GPU 驱动 | `nvidia-smi` 成功 | 提示安装 Windows NVIDIA 驱动 |
| 容器 GPU | `docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi` 成功 | 提示安装 `nvidia-container-toolkit` 并重启 Docker |
| 端口 | 1935/8554/8000/8001/8080/8189/8888/8889/9997/9998 未被占用 | 列出占用进程 |
| 视频素材 | `assets/drone.mp4` 存在且可解码 | 提示放置文件；无素材时可用测试视频 |
| 脚本换行 | 无 CRLF | 提示执行 `dos2unix` |

## 8. 非功能需求

| 编号 | 类别 | 指标 | 验证方法 |
| --- | --- | --- | --- |
| NFR-01 | 延迟（原画） | WebRTC 端到端中位数 ≤ 500 ms，P95 ≤ 1 s；HLS 兜底 ≤ 4 s | 测试图案毫秒时钟 + 手机拍照，见 13.2 |
| NFR-02 | 延迟（检测画） | 端到端 P95 ≤ 1.5 s；相对原画附加延迟 ≤ 500 ms | 同屏截图对比烧录时钟 |
| NFR-03 | 帧率 | 原画显示 ≥ 24 fps；检测画有效帧率 ≥ 15 fps，目标 20 fps；稳态丢帧率 < 20% | `getStats()` + YOLO 指标 |
| NFR-04 | 画质与编码 | H.264、`yuv420p`、无 B 帧、GOP 1 s、1080p25、约 4 Mbps；无花屏/绿屏 | `ffprobe` + 目视 |
| NFR-05 | 资源 | 显存 ≤ 4 GB；容器 CPU ≤ 6 核；内存 ≤ 6 GB | `nvidia-smi` + `docker stats` |
| NFR-06 | 稳定性 | 连续 2 h 无崩溃；内存增长 ≤ 10%；延迟漂移 ≤ 1 s；源重启 3 次均能自愈 | `scripts/soak.sh` |
| NFR-07 | 启动时间 | 镜像已就绪时 `up -d` 到可播放 ≤ 60 s；冷启动（含拉镜像/模型）≤ 10 min（视网络） | 计时 |
| NFR-08 | 浏览器兼容 | Chrome/Edge 最新稳定版；1920×1080 窗口；无需插件 | 手工验收 |
| NFR-09 | 安全 | 仅绑定回环/WSL 网卡；无默认口令；视频与模型不入库；不暴露公网 | `ss -lntup` + 仓库检查 |
| NFR-10 | 可维护性 | 视频路径、分辨率、码率通过 `push-windows.ps1` 参数配置；模型、阈值、类别通过 YOLO 环境变量配置；端口通过 MediaMTX 配置 | 修改参数/配置验证 |
| NFR-11 | 可移植性 | 支持 Linux x86_64 + NVIDIA Docker；Windows 通过 WSL2；不支持 ARM | 文档说明 + 部署验证 |
| NFR-12 | 日志 | 结构化、带时间戳与组件名；错误包含原因与重试次数；默认 INFO | 抽查日志 |

**补充说明**

- 延迟指标以本机回环为基准；生产公网会增加 RTT，需重新评估。
- “检测画有效帧率”指实际完成推理并输出的帧率，不是播放器显示帧率。
- 资源上限按单路 1080p25 估算；若源为 4K，必须先在推流端归一化到 1080p，避免解码与推理压力叠加。

## 9. 接口与配置

### 9.1 端口分配

| 端口 | 协议 | 组件 | 用途 | 暴露范围 |
| --- | --- | --- | --- | --- |
| 1935 | TCP | MediaMTX | RTMP 推流 | 本机/WSL |
| 8554 | TCP | MediaMTX | RTSP 拉流/推流 | 本机/WSL |
| 8888 | TCP | MediaMTX | HLS/LL-HLS | 浏览器 |
| 8889 | TCP | MediaMTX | WebRTC 播放页 + WHEP 信令 | 浏览器 |
| 8189 | UDP + TCP | MediaMTX | WebRTC 媒体（TCP 为 WSL2 关键） | 浏览器 |
| 9997 | TCP | MediaMTX | Control API | 内部/控制台 |
| 9998 | TCP | MediaMTX | Prometheus 指标 | 内部 |
| 8000 | TCP | control | 控制 API | 本机/控制台 |
| 8001 | TCP | yolo | 健康检查与指标 | 内部 |
| 8080 | TCP | web | 统一控制台 | 浏览器 |

> 端口冲突时修改 `deploy/mediamtx/mediamtx.yml` 或 compose 映射；文档、脚本与播放页中的 URL/端口必须保持一致。
>
> 本期 `mediamtx` 使用 host 网络，端口直接绑定在 WSL 网卡上，不需要 Compose `ports` 映射；Windows FFmpeg 通过 `localhost:1935` 推流。生产环境若改用 bridge，再按上表映射，并同时映射 8189 的 UDP 与 TCP。
>
> host 网络下无法用 `ports` 把监听限制到 `127.0.0.1`：MediaMTX 会监听 WSL 的全部网卡。WSL2 NAT 默认不对局域网暴露这些端口，但需要严格隔离时应改用 bridge，并把端口绑定写成 `127.0.0.1:<port>:<port>`。

### 9.2 流地址

| 流 | RTMP（推） | RTSP（拉） | WebRTC 页面 | WHEP | HLS |
| --- | --- | --- | --- | --- | --- |
| 原画 | `rtmp://localhost:1935/drone1` | `rtsp://localhost:8554/drone1` | `http://localhost:8889/drone1` | `http://localhost:8889/drone1/whep` | `http://localhost:8888/drone1/index.m3u8` |
| 检测画 | —（YOLO 直接推 RTSP） | `rtsp://localhost:8554/drone1_yolo` | `http://localhost:8889/drone1_yolo` | `http://localhost:8889/drone1_yolo/whep` | `http://localhost:8888/drone1_yolo/index.m3u8` |

本期 host 网络下，容器内访问 MediaMTX 也用 `127.0.0.1`；若改为 bridge，才用服务名（如 `mediamtx:8554`）。Windows 浏览器访问时使用 `localhost` 或 WSL IP。

> 若沿用 SRS/ZLMediaKit 的 `app/stream` 习惯，可把路径改为 `live/drone1`；本期为降低歧义统一使用单段路径 `drone1`。

### 9.3 WebRTC/WHEP 约定

- WHEP 请求：`POST http://<host>:8889/<path>/whep`，`Content-Type: application/sdp`，Body 为 Offer SDP。
- 响应：`201 Created`，`Location` 头返回会话地址，Body 为 Answer SDP；后续 `PATCH`/`DELETE` 按 WHEP 规范。
- ICE：服务端提供 TCP 候选（`webrtcLocalTCPAddress: :8189`）作为 WSL2 环境的兜底；UDP 候选可用时浏览器通常优先 UDP，失败后回落 TCP。
- CORS：允许控制台来源；本地演示可 `*`，生产必须收紧。
- 编码：H.264 Constrained Baseline/Main，无 B 帧；浏览器不支持 H.265，源为 HEVC 时必须转码。

### 9.4 MediaMTX 配置基线（示意）

```yaml
logLevel: info

rtspAddress: :8554
rtmpAddress: :1935
hlsAddress: :8888
webrtcAddress: :8889
apiAddress: :9997
metricsAddress: :9998

hlsVariant: lowLatency
hlsSegmentDuration: 1s
hlsPartDuration: 200ms

webrtcLocalUDPAddress: :8189      # 有 UDP 条件时使用
webrtcLocalTCPAddress: :8189      # WSL2 localhost 场景的关键
webrtcAdditionalHosts: [127.0.0.1] # 直连 WSL IP 时追加该 IP
webrtcAllowOrigins: ['*']

paths:
  all_others:
```

> 示意配置，实施时以所用 MediaMTX 镜像版本的默认配置为底稿，只覆盖必要项；不要整份复制导致版本字段不兼容。

### 9.5 YOLO 服务接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/healthz` | 进程存活 |
| `GET` | `/readyz` | 模型已加载且已输出首帧 |
| `GET` | `/metrics` | Prometheus 指标 |
| `GET` | `/api/v1/config` | 当前生效配置（脱敏，P1） |

### 9.6 控制 API

见 7.11。补充约定：

- 所有请求与响应使用 `application/json`，UTF-8；
- 错误响应统一为 `{"code": "...", "message": "...", "detail": {...}}`；
- 启动接口返回 202 表示已受理，状态通过 `GET /streams/{id}` 轮询；
- 停止接口必须幂等；
- 控制服务不得阻塞在 FFmpeg 进程生命周期上，需异步编排。

### 9.7 配置项

**Windows 推流脚本 `scripts/push-windows.ps1`**

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `-Video` | `assets\drone.mp4` | 源视频路径 |
| `-RtmpUrl` | `rtmp://localhost:1935/drone1` | 推流地址 |
| `-Width` / `-Height` | `1920` / `1080` | 输出分辨率 |
| `-Fps` | `25` | 输出帧率 |
| `-Bitrate` / `-BufSize` | `4M` / `8M` | H.264 码率与缓冲区 |
| `-Preset` | `veryfast` | libx264 preset |
| `-FfmpegPath` | `ffmpeg` | FFmpeg 可执行文件 |
| `-Once` | 关闭 | 只推一遍，不循环 |

**YOLO 服务（M3 预留）**

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `YOLO_STREAM_KEY` | `drone1_yolo` | 检测画流路径 |
| `RTSP_TRANSPORT` | `tcp` | YOLO 拉流传输方式 |
| `MODEL` | `best.pt` | 权重（`models/best.pt`） |
| `IMGSZ` | `640` | 推理尺寸 |
| `CONF` | `0.25` | 置信度阈值 |
| `IOU` | `0.45` | NMS IoU |
| `CLASSES` | `""` | 类别过滤，逗号分隔 |
| `DEVICE` | `0` | `0` 或 `cpu` |
| `HALF` | `true` | FP16 |
| `WEB_PORT` | `8080` | 控制台端口 |
| `API_PORT` | `8000` | 控制 API 端口 |
| `TZ` | `Asia/Shanghai` | 日志时区 |

## 10. 模拟方案

### 10.1 视频源模拟

用 **Windows FFmpeg** 替代“机场推流”：

```text
实际：机场相机 → RTMP/RTSP/GB28181 → 流媒体服务器
模拟：本地视频文件 → Windows FFmpeg 循环转码 → RTMP → 流媒体服务器
```

关键点：

- `-re` 保证按实时速率读取，否则文件会瞬间推完；
- `-stream_loop -1` 循环；
- 若源为 HEVC/4K，必须转码为 H.264 1080p25，否则浏览器 WebRTC 无法解码或延迟过高；
- 默认去掉音频，避免 AAC/Opus 兼容问题；
- 推流中断由 `scripts/push-windows.ps1` 循环重启；容器回退方案用 `restart: unless-stopped` 兜底。

### 10.2 推流命令（参考）

推荐直接运行脚本：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\push-windows.ps1
```

等价的单条 FFmpeg 命令（Windows PowerShell）：

```powershell
ffmpeg -hide_banner -loglevel warning `
  -re -stream_loop -1 -i "assets\drone.mp4" `
  -vf "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,format=yuv420p" `
  -r 25 -c:v libx264 -preset veryfast -tune zerolatency `
  -profile:v baseline -bf 0 -g 25 -b:v 4M -maxrate 4M -bufsize 8M -an `
  -f flv rtmp://localhost:1935/drone1
```

> 若使用 WSL 内 FFmpeg，路径改成 `/home/lizao/docker-demo2/assets/drone.mp4`，地址改成 `rtmp://127.0.0.1:1935/drone1`。Windows 侧如需降低 CPU，可把 `libx264` 换成 `h264_nvenc`。

### 10.3 测试图案（无视频时）

```bash
ffmpeg -hide_banner -loglevel warning -re \
  -f lavfi -i "testsrc2=size=1920x1080:rate=25" \
  -c:v libx264 -preset ultrafast -tune zerolatency -bf 0 -g 25 -b:v 4M -an \
  -f flv rtmp://127.0.0.1:1935/drone1
```

延迟测量需要画面中带时钟：由 `scripts/gen-test-video.sh` 生成一段带 `HH:MM:SS.mmm` 烧录时钟的测试视频（内部用 `drawtext` 的 `pts` 或 `frame_num` 表达式实现，避免手写多层转义），再用 `scripts/push-windows.ps1 -Video <测试视频>` 循环播放。脚本必须同时提供不带时钟的纯色块/移动目标版本，便于观察检测框跟随效果。

### 10.4 控制指令模拟

| 步骤 | 真实链路 | 模拟链路 |
| --- | --- | --- |
| 1 | 云端调用 `live_start`，指定 RTMP 地址 | `POST /api/v1/streams/drone1/start` |
| 2 | 机场向该地址推流 | Windows 侧启动 `scripts/push-windows.ps1`，FFmpeg 推流 |
| 3 | 云端返回播放地址 | 控制 API 返回 WHEP/HLS 地址 |
| 4 | 用户浏览器播放 | 控制台播放 |
| 5 | 云端调用 `live_stop` | `POST /api/v1/streams/drone1/stop` |

### 10.5 切换到真实机场的改造点

| 改造项 | 需要做什么 | 不需要改什么 |
| --- | --- | --- |
| 推流端 | 用真实机场按 `live_start` 推 `rtmp://<server>:1935/drone1`；本地验证用 `scripts/push-windows.ps1` | MediaMTX 路径、YOLO、播放页 |
| 控制端 | 用 DJI Cloud API 适配器替换 REST mock，映射 `video_id` ↔ 流 key | 状态机与 URL 生成逻辑 |
| 网络 | 公网 IP/域名、TLS、端口放行、TURN（如需） | 本地播放逻辑 |
| 鉴权 | MediaMTX 发布/播放鉴权、设备证书、Token | YOLO 拉流地址（内部网络） |
| 协议 | 若机场只支持 GB28181，则用 ZLMediaKit/SRS 替换 MediaMTX 的接入层 | YOLO 仍从 RTSP 拉流 |
| 规模 | 多路时按 GPU 能力分片，YOLO 进程池/批处理 | 单路逻辑 |

## 11. 技术选型

### 11.1 流媒体服务器对比

| 维度 | MediaMTX | SRS | ZLMediaKit |
| --- | --- | --- | --- |
| WebRTC/WHEP | 内置，配置简单，HTTP 即可 | 内置，通常需 HTTPS/额外端口 | 内置 |
| RTSP/RTMP/HLS | 全部内置 | 全部内置 | 全部内置 |
| GB28181 | 不支持 | 需确认版本能力 | 支持较完整 |
| 部署体积 | 单二进制/小镜像 | 较大 | 较大 |
| 配置复杂度 | 低 | 中 | 中 |
| 适合场景 | 本模拟、快速验证 | 生产直播 | 国标/安防接入 |

**结论**：本期选 MediaMTX。若后续明确要求 GB28181，再评估 ZLMediaKit 替换接入层；YOLO 与播放端不受影响。

### 11.2 推理与编解码

| 项 | 选择 | 理由 |
| --- | --- | --- |
| 推理框架 | Ultralytics YOLO11n（GPU） | 开箱即用、生态成熟、n/s 规模适配 6 GB 显存 |
| 推理精度 | FP16，`imgsz=640` | 在 4050 上延迟低，精度满足演示 |
| 解码 | PyAV/OpenCV（FFmpeg 后端） | 支持 RTSP/TCP 与低延迟参数 |
| 编码 | `h264_nvenc` 优先，`libx264 ultrafast` 兜底 | 降低 CPU 占用，保证 1080p25 实时 |
| 画框 | OpenCV | 简单、可控、无额外依赖 |
| 播放 | WHEP + 原生 JS，`hls.js` 兜底 | 浏览器原生 WebRTC，低延迟 |
| Web | Nginx 静态页 | 轻量，无构建链 |

### 11.3 决策记录（ADR）

| 编号 | 决策 | 理由 | 影响 |
| --- | --- | --- | --- |
| ADR-01 | 用本地视频 + FFmpeg 模拟机场 | 无无人机，快速验证协议链路 | 不验证真实编码参数与网络条件 |
| ADR-02 | MediaMTX 作为流媒体服务器 | 单容器覆盖 RTMP/RTSP/HLS/WebRTC，WHEP 简单 | 不支持 GB28181 |
| ADR-03 | WebRTC 为主、LL-HLS 兜底 | 浏览器低延迟且免插件；WSL2 UDP 不稳定 | 需处理 ICE/TCP 与 CORS |
| ADR-04 | YOLO 独立容器，GPU 直通 | 职责分离，便于替换模型/扩容 | 需安装 nvidia-container-toolkit |
| ADR-05 | 单路、单机、无鉴权 | 本期为可行性验证 | 生产需补鉴权、TLS、并发 |
| ADR-06 | REST 模拟 live_start/stop | 保留 DJI 接入接缝 | 真实协议需另写适配器 |

## 12. 部署与运行

### 12.1 前置条件

1. Windows 11 + WSL2（Ubuntu 26.04），已安装 Docker 29.x 与 Compose v2+（实测 v5.5.0）。
2. Windows 侧安装 NVIDIA 驱动（实测 566.26），WSL 内 `nvidia-smi` 可用。
3. 安装 `nvidia-container-toolkit`（当前缺失）：

```bash
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
  | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg

curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
  | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
  | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list

sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker

# 验证
docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi
```

4. 视频素材放到 `assets/drone.mp4`。
5. 首次运行需联网拉取 MediaMTX 镜像与 YOLO 权重；之后可离线。

### 12.2 目录结构（建议）

```text
docker-demo2/
├── docker-compose.yml
├── .gitattributes
├── .gitignore
├── README.md
├── docs/
│   ├── requirements.md
│   ├── architecture.md
│   └── runbook.md
├── assets/
│   └── drone.mp4               # 用户提供，git 忽略
├── deploy/
│   └── mediamtx/mediamtx.yml
├── worker/                     # 当前实现：numpy mock YOLO，uv 管理
│   ├── pyproject.toml
│   ├── uv.lock
│   ├── requirements.txt        # 由 uv.lock 导出，供镜像使用
│   ├── Dockerfile
│   └── src/drone_worker/
│       ├── mock.py             # 假检测器（随机框/置信度）
│       ├── render.py           # 画框与标签
│       ├── pipeline.py         # 离线标注
│       ├── relay.py            # 在线拉流/推流
│       └── cli.py
├── backend/                    # 控制 API（FastAPI + Docker SDK）
│   ├── app/main.py
│   ├── app/controllers.py
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/                   # Vue 3 + Vite 控制台
│   ├── src/App.vue
│   ├── src/whep.js
│   ├── nginx.conf
│   └── Dockerfile
├── models/                     # 权重缓存，git 忽略
├── scripts/
│   ├── push-windows.ps1        # 可选：Windows 手动推流
│   ├── push-windows.cmd
│   ├── doctor.sh
│   ├── gen-test-video.sh
│   ├── healthcheck.sh
│   └── soak.sh
└── tests/
    └── smoke.sh
```

### 12.3 启动

```bash
# WSL：启动平台
cd /home/lizao/docker-demo2
docker compose up -d --build
docker compose ps
docker logs -f drone-backend
```

Windows PowerShell：启动模拟推流（不属于平台，模拟真实设备）

```powershell
cd E:\Pycharm\docker-demo2
powershell -ExecutionPolicy Bypass -File scripts\push-windows.ps1
```

浏览器打开：

- 控制台：`http://localhost:8080`
- 原画：`http://localhost:8889/drone1`（MediaMTX 自带播放页）
- 检测画：`http://localhost:8889/drone1_yolo`

平台只控制算法，不控制推流：

```bash
curl -s -X POST http://127.0.0.1:8000/api/algorithm/start
curl -s -X POST http://127.0.0.1:8000/api/algorithm/stop
```

> 当前 M3 先用 numpy mock 检测器打通链路，不依赖 GPU / `best.pt`；
> 接入真实 YOLO11n 时替换 `worker/src/drone_worker/mock.py` 即可。

### 12.4 验证

```powershell
# Windows：控制 API 状态
curl.exe -s http://127.0.0.1:8000/api/status

# 原画流参数（Windows ffprobe）
ffprobe -v error -rtsp_transport tcp -show_streams rtsp://localhost:8554/drone1

# 检测流参数
ffprobe -v error -rtsp_transport tcp -show_streams rtsp://localhost:8554/drone1_yolo
```

```bash
# WSL：前端反代、MediaMTX、容器日志
curl -s http://localhost:8080/api/status
curl -s http://localhost:9997/v3/paths/list
docker logs --tail 20 drone-backend
docker logs --tail 20 drone-worker
```

> worker 暂未提供 HTTP 健康检查；以后接入真实 YOLO 服务时再补 `/healthz`、`/readyz`。

### 12.5 排障

| 现象 | 可能原因 | 处理 |
| --- | --- | --- |
| 页面能打开但黑屏 | WebRTC 媒体未连通（UDP 被 WSL 阻断） | 确认 `webrtcLocalTCPAddress: :8189` 且映射 TCP 8189；浏览器控制台看 ICE 状态 |
| WHEP 返回 CORS 错误 | `webrtcAllowOrigins` 未允许控制台来源 | 配置允许 `http://localhost:8080` |
| 有原画无检测画 | worker 未启动/容器不存在 | 看 `docker logs drone-worker`，`docker compose ps` |
| 检测画延迟越来越大 | 推理慢且未丢帧，缓冲累积 | 确认队列 ≤1、丢帧策略、关闭无关缓冲 |
| 画面花屏/绿屏 | 源为 HEVC 或编码参数不兼容 | 转码 H.264、无 B 帧、`yuv420p` |
| 容器启动即退出 | 脚本 CRLF、路径不存在、权限 | `dos2unix`、检查挂载路径、看日志 |
| 显存不足 | 6 GB 被桌面/其他进程占用 | 关闭其他 GPU 程序，改用 `yolo11n`，限制 `batch=1` |
| `docker compose up` 报 GPU 错误 | 未安装 `nvidia-container-toolkit` | 按 12.1 安装并重启 Docker |

## 13. 验收标准

### 13.1 验收项

| 编号 | 验收项 | 通过条件 |
| --- | --- | --- |
| AC-01 | 环境自检 | `./scripts/doctor.sh` 全部通过，GPU 容器可运行 `nvidia-smi` |
| AC-02 | 链路 A 原画 | 浏览器 3 s 内出画；`ffprobe` 为 H.264 1920×1080 25 fps；连续播放 10 min 无中断 |
| AC-03 | 链路 B 检测画 | `drone1_yolo` 有视频；框、类别、置信度正确；目标移动时框跟随 |
| AC-04 | 双流对比 | 两个独立页面分别播放（或 P1 控制台并排）；同一时刻检测画的目标框与目标位置一致 |
| AC-05 | 延迟 | 原画 P95 ≤ 1 s；检测画 P95 ≤ 1.5 s；相对附加 ≤ 500 ms（测量方法见 13.2） |
| AC-06 | 断流自愈 | 停止 Windows FFmpeg 10 s 后重新运行脚本，两条链路 ≤10 s 自动恢复，无需重启容器 |
| AC-07 | 一键启动 | 清空容器后 `docker compose up -d` + Windows 推流到可播放 ≤ 60 s（镜像已就绪）；冷启动 ≤ 10 min |
| AC-08 | 配置生效 | 修改 `MODEL`/`CONF`/`CLASSES` 后重启 yolo，效果变化且无需重建镜像 |
| AC-09 | 资源 | 10 min 稳态：显存 ≤ 4 GB、CPU ≤ 6 核、内存 ≤ 6 GB |
| AC-10 | 稳定性 | 2 h 连续运行无崩溃；延迟漂移 ≤ 1 s；内存增长 ≤ 10% |
| AC-11 | 浏览器兼容 | Chrome 与 Edge 均可播放；无插件；1024×768 以上窗口布局可用 |
| AC-12 | 可替换性 | 停掉 Windows FFmpeg，从另一终端用 FFmpeg 推 RTMP 到 `drone1`，MediaMTX/YOLO/播放页不改即可工作 |

> 当前 worker 为 numpy mock：AC-03 的“框/类别/置信度正确”、AC-08 的参数生效、
> AC-09 的显存指标需等真实 YOLO11n 接入后复测；链路连通、画框渲染与断流自愈
> 已可用 mock 验证。

### 13.2 延迟测量方法

1. 使用带烧录时钟的测试源（`gen-test-video.sh` 生成的视频，通过 `push-windows.ps1 -Video` 传入），画面中显示 `HH:MM:SS.mmm`。
2. 手机/相机同时拍下浏览器画面与一块显示当前时间的屏幕（或手机秒表）。
3. 取 ≥5 个采样点，计算“源时钟 − 参考时钟”的差值，记录中位数与 P95。
4. 检测画附加延迟：暂停/截图同一时刻的双播放器画面，比较两路烧录时钟的差值。
5. 辅助指标：浏览器 `getStats()` 读取 `framesPerSecond`、`currentRoundTripTime`、`jitterBufferDelay`；控制台展示，但不作为唯一验收依据。

> 说明：烧录时钟方法能覆盖“解码 + 渲染 + 显示”全链路；浏览器 stats 只覆盖网络与抖动缓冲，两者结合判断。

### 13.3 验收环境

- Windows 11 build 26200，Chrome/Edge 最新稳定版，FFmpeg 9.0.2；
- WSL2 Ubuntu 26.04，Docker 29.7.2 / Compose v5.5.0；
- RTX 4050 Laptop 6 GB，驱动 566.26；
- 显示器 1920×1080；
- 单路 1080p25 源。

## 14. 里程碑与交付物

| 阶段 | 内容 | 产出 | 预估 |
| --- | --- | --- | --- |
| M0 | 需求评审 | 本文档定稿 | 0.5 d |
| M1 | 环境与骨架 | 安装 toolkit、Compose 骨架、MediaMTX、测试图案 | 0.5 d |
| M2 | 链路 A | Windows FFmpeg 推流 + 原画播放 + 重试 | 0.5 d |
| M3 | 链路 B | worker 拉流/画框/推流 + 自愈（当前为 numpy mock，真实 YOLO 后续替换） | 1 d |
| M4 | 控制台与控制 API | 双播放器、状态、start/stop | 1 d |
| M5 | 验收与文档 | 验收记录、README、runbook、演示 | 0.5 d |

**交付物**：代码仓库、`docker-compose.yml`、MediaMTX 配置、Windows 推流脚本、YOLO 服务、控制台、控制 API、脚本、文档、验收记录。

## 15. 风险与对策

| 编号 | 风险 | 影响 | 概率 | 对策 |
| --- | --- | --- | --- | --- |
| R1 | WSL2 不转发 UDP，WebRTC 黑屏 | 高 | 中 | 启用 ICE/TCP（`webrtcLocalTCPAddress`）+ localhost 转发；必要时 mirrored 网络或 HLS 兜底 |
| R2 | WSL IP 每次启动变化 | 中 | 高 | 默认不依赖 WSL IP；脚本动态注入；优先 localhost |
| R3 | 未装 `nvidia-container-toolkit` | GPU 不可用，YOLO 降级 | 已确认 | M1 首项任务安装并验证 |
| R4 | 6 GB 显存被桌面/浏览器占用 | OOM、推理失败 | 中 | `yolo11n` + FP16 + `batch=1`；关闭其他 GPU 程序；CPU 降级 |
| R5 | 源视频为 HEVC/4K | 浏览器无法解码、延迟高 | 高 | 统一转 H.264 1080p25、无 B 帧 |
| R6 | `/mnt/e` 文件系统慢 | 推流卡顿、启动慢 | 高 | 视频/模型放 WSL 原生路径或 volume |
| R7 | CRLF 导致脚本失败 | 容器起不来 | 中 | `.gitattributes` + `dos2unix` + CI 检查 |
| R8 | 浏览器自动播放限制 | 无画面 | 中 | `muted + autoplay + playsinline`，提供手动按钮 |
| R9 | 推理慢导致延迟累积 | 越看越滞后 | 中 | 队列 ≤1、丢帧策略、低延迟编码参数 |
| R10 | 编码 CPU 占用高 | 掉帧 | 中 | NVENC 优先，libx264 ultrafast 兜底 |
| R11 | Ultralytics AGPL-3.0 许可 | 商用合规风险 | 中 | 提前确认许可，必要时购买商业授权或换模型 |
| R12 | 视频隐私/版权 | 合规风险 | 低 | 仅本地使用，不入库、不外发 |
| R13 | 端口冲突 | 启动失败 | 低 | 修改 MediaMTX 配置或 compose 端口；doctor 脚本预检 |
| R14 | 时间戳/抖动缓冲导致测量偏差 | 验收争议 | 中 | 统一测量方法，保留原始记录 |

## 16. 待确认事项

| 编号 | 问题 | 默认假设 | 需要确认 |
| --- | --- | --- | --- |
| Q1 | 视频素材路径、格式、分辨率、帧率、时长？ | `assets/drone.mp4`，640×368@24，H.264，85 s | 已提供 |
| Q2 | 检测目标类别？ | COCO 全类，可过滤 | 是否只保留 person/vehicle |
| Q3 | 是否需要自定义模型？ | 否，预训练 YOLO11n | 若有领域目标需重新评估 |
| Q4 | 是否需要多路并发？ | 单路 | 未来路数与 GPU 预算 |
| Q5 | 是否必须支持 GB28181？ | 否 | 决定 MediaMTX 是否够用 |
| Q6 | 是否需要音频？ | 否，默认静音 | 需要则转 Opus |
| Q7 | 是否需要中文标签/中文界面？ | 界面中文、标签英文 | 中文标签需字体与编码处理 |
| Q8 | 最终生产部署环境？ | 公司公网服务器 + 域名 | 影响 TLS/TURN/带宽设计 |
| Q9 | 是否要录像/截图/告警？ | 本期不做 | 后续范围 |

## 17. 参考

- MediaMTX 文档：<https://mediamtx.org/docs/>
- MediaMTX WebRTC 特性（ICE/TCP、`webrtcAdditionalHosts`、H.264 无 B 帧）：<https://mediamtx.org/docs/features/webrtc-specific-features>
- MediaMTX 仓库：<https://github.com/bluenviron/mediamtx>
- Ultralytics YOLO 文档：<https://docs.ultralytics.com/>
- 大疆上云 API 文档：<https://developer.dji.com/doc/cloud-api-tutorial/cn/>
- WSL2 网络与 localhost 转发：<https://learn.microsoft.com/windows/wsl/networking>
- NVIDIA Container Toolkit 安装：<https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html>
- SRS：<https://ossrs.io/>
- ZLMediaKit：<https://github.com/ZLMediaKit/ZLMediaKit>
