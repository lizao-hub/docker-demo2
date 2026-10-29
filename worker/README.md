# worker — 模拟 YOLO 推理端

用 numpy 随机生成检测框（带随机游走，模拟目标移动），再用 OpenCV 画到画面上。
不依赖 torch / CUDA / `best.pt`，目的是先把「拉流 → 推理 → 画框 → 推流」整条链路跑通。

真正的 YOLO 版本后续替换 `src/drone_worker/mock.py` 里的 `MockDetector` 即可，其余代码不用动。

## 本地环境（uv）

```powershell
cd E:\Pycharm\docker-demo2\worker
uv sync
```

`uv sync` 会按 `pyproject.toml` + `uv.lock` 创建 `.venv` 并装好依赖。

## 命令

### relay：实时拉流、画框、推流

```powershell
cd E:\Pycharm\docker-demo2
uv run --project worker drone-worker relay
```

默认：

```text
RTSP  rtsp://127.0.0.1:8554/drone1
RTMP  rtmp://127.0.0.1:1935/drone1_yolo
```

`drone1` 不在线时会每 2 秒重试；`Ctrl+C` 退出。

### annotate：离线给视频画框

```powershell
uv run --project worker drone-worker annotate --limit 120 --frames-dir worker/out/frames
```

默认读 `assets/drone.mp4`，输出 `worker/out/annotated.mp4`。

### info：查看视频信息

```powershell
uv run --project worker drone-worker info
```

## 参数

### relay

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `--source` | `rtsp://127.0.0.1:8554/drone1` | 输入流，环境变量 `DRONE_SOURCE` |
| `--dest` | `rtmp://127.0.0.1:1935/drone1_yolo` | 输出流，环境变量 `DRONE_DEST` |
| `--ffmpeg` | `ffmpeg` | ffmpeg 路径，环境变量 `FFMPEG_BIN` |
| `--bitrate` | `4M` | H.264 码率 |
| `--preset` | `veryfast` | x264 preset |
| `--retry-delay` | `2.0` | 重连间隔（秒） |
| `--duration` | `0` | 运行时长，0 表示一直跑 |
| `--seed` | `7` | 随机种子 |
| `--max-objects` | `4` | 同时存在的框数量上限 |

### annotate

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `--input` | `assets/drone.mp4` | 源视频 |
| `--output` | `worker/out/annotated.mp4` | 输出视频 |
| `--limit` | 不限 | 只处理前 N 帧 |
| `--seed` | `7` | 随机种子 |
| `--max-objects` | `4` | 同时存在的框数量上限 |
| `--frames-dir` | 无 | 额外导出 jpg 的目录 |
| `--frame-every` | `30` | jpg 导出间隔 |

## 实现要点

- OpenCV 只负责解码、画框；编码和推流交给 ffmpeg 子进程，原始 BGR 帧走 `stdin`。
  `cv2.VideoWriter` 写 RTMP 不可靠，所以不用它。
- RTSP 强制走 TCP（`OPENCV_FFMPEG_CAPTURE_OPTIONS=rtsp_transport;tcp`），
  因为 WSL2 不转发 Windows 到 WSL 的 UDP。
- 打开/读取都设置了 5 秒超时，断流后自动重连。
- 分辨率或帧率变化时会重启 ffmpeg。
- 音频直接丢弃。

## 容器

```bash
docker build -t drone-worker:dev /mnt/e/Pycharm/docker-demo2/worker
```

或由 compose 构建（见仓库根目录 `docker-compose.yml` 的 `worker` 服务）。

镜像内的依赖安装方式：

- Python 依赖和静态 ffmpeg 都来自 `requirements.txt`；
- ffmpeg 用 `imageio-ffmpeg` 包自带的 Linux 静态二进制（含 libx264），所以镜像里不需要 apt，体积更小、构建更快；
- pip 走阿里云 PyPI 镜像（Dockerfile 内配置）。

改动依赖后重新导出：

```powershell
cd E:\Pycharm\docker-demo2\worker
uv export --frozen --no-hashes --no-dev --no-emit-project --extra container -o requirements.txt
```

镜像不复制本地 `.venv`，也不需要 uv。

## 目录

```text
worker/
├── pyproject.toml
├── uv.lock
├── requirements.txt    # 从 uv.lock 导出，供镜像使用
├── .python-version
├── Dockerfile
└── src/drone_worker/
    ├── mock.py           # numpy 假检测器
    ├── render.py         # 画框 / 标签 / HUD
    ├── pipeline.py       # 离线：读视频 → 检测 → 写视频
    ├── relay.py          # 在线：RTSP → 检测 → ffmpeg → RTMP
    └── cli.py            # relay / annotate / info
```
