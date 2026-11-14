FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:0.11.15 /uv /bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY app ./app
COPY data_derived ./data_derived
# 원본 폴더 이름은 macOS에서 NFD로 저장되어 있어 ASCII 접두어로 찾고, 대상은 loader.py와 같은 NFC 이름으로 둔다
COPY ["01_*/04_*/", "./01_참가자_배포용/04_원본데이터/"]
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
EXPOSE 8000
# 상태는 DATABASE_URL이 가리키는 DB에 둔다(AXHub는 axhub.yaml의 database 선언으로 Postgres 주소를 주입).
# 비어 있으면 컨테이너 안 SQLite(시연용, 재시작 시 사라짐)
# 포트는 axhub.yaml runtime.port(8000)와 같다. 플랫폼이 PORT를 주입하는지는 미확인이라 주입되면 그 값을 따른다
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
