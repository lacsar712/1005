FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
RUN pip install --no-cache-dir -r requirements.txt

# Create necessary directories
RUN mkdir -p /app/data /app/app/static/uploads

# Copy application code
COPY . .

# Expose port (Internal)
EXPOSE 8000

# 启动命令：先执行数据库填充，再启动应用
CMD ["sh", "-c", "python -m app.seed && python -m app.app"]
