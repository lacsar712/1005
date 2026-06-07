FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
RUN pip install --no-cache-dir -r requirements.txt

# Create necessary directories
RUN mkdir -p /app/data /app/app/static/uploads /app/app/static/exports

# Copy application code
COPY . .

# Expose port (Internal)
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/healthz', timeout=5).status == 200 else 1)" || exit 1

# 启动命令：先执行数据库填充，再启动应用
CMD ["sh", "-c", "python -m app.seed && python -m app.app"]
