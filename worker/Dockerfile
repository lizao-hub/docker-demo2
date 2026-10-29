FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Python 依赖 + 静态 ffmpeg（imageio-ffmpeg，含 libx264），不需要 apt。
# requirements.txt 由 uv.lock 导出，保证和本地环境版本一致：
#   uv export --frozen --no-hashes --no-dev --no-emit-project --extra container -o requirements.txt
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src

ENTRYPOINT ["python", "-m", "drone_worker"]
CMD ["relay"]
