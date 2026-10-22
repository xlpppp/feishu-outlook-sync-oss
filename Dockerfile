# 默认走 DaoCloud 代理镜像，避免直连 Docker Hub（国内/受限网络常见超时）
# 若本机已有官方镜像，可构建时覆盖：
#   docker compose build --build-arg PYTHON_IMAGE=python:3.12-slim
ARG PYTHON_IMAGE=docker.m.daocloud.io/library/python:3.12-slim
FROM ${PYTHON_IMAGE}

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATABASE_URL=sqlite:////data/sync.db

# 构建期可选代理（不重启 dockerd 也能传给 apt/pip）
ARG HTTP_PROXY
ARG HTTPS_PROXY
ARG NO_PROXY=localhost,127.0.0.1
ENV HTTP_PROXY=${HTTP_PROXY} \
    HTTPS_PROXY=${HTTPS_PROXY} \
    http_proxy=${HTTP_PROXY} \
    https_proxy=${HTTPS_PROXY} \
    NO_PROXY=${NO_PROXY} \
    no_proxy=${NO_PROXY}

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY scripts ./scripts

RUN mkdir -p /data

# 运行期清掉构建代理，避免容器业务流量误走代理
ENV HTTP_PROXY= HTTPS_PROXY= http_proxy= https_proxy= NO_PROXY= no_proxy=

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
