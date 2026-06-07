# 在线相册系统 (项目 ID: 1005)

我尊敬的主上【**尼古拉斯·东北老王**】，这是为您精心打磨的 100% 汉化全栈相册项目。

## 🛠️ 技术栈
- **后端**: Flask 3.0 + SQLAlchemy (SQLite)
- **前端**: Tailwind CSS + Viewer.js (灯箱预览)
- **部署**: Docker Compose (345 端口算法)

## 🚀 一键启动
请确保环境已安装 Docker，然后在根目录执行：
```bash
docker compose up --build -d
```

## 🔗 访问信息
- **首页**: [http://localhost:31005](http://localhost:31005)
- **后端管理**: [http://localhost:41005](http://localhost:41005) (API 暴露)
- **管理员账号**: `admin` / `123456` (支持一键填充)

## ✨ 核心特性
1. **多图拖拽上传**: 极致高效的图片上传体验。
2. **专业灯箱**: 完美的图片预览与操作交互。
3. **资源优化**: 严格限制 `1.5GB` 内存占用，适配 16GB Mac。
4. **数据安全**: 数据库与图片存储均通过 Docker Volume 持久化。

---

## 🏥 健康检查探针

系统内置两个 Kubernetes 风格的健康检查端点：

| 端点 | 检查项 | 用途 |
|------|--------|------|
| `GET /healthz` | SQLite 数据库连通性 | Liveness 探针（进程存活） |
| `GET /readyz` | SQLite + uploads 可写 + Schema 版本 | Readiness 探针（服务就绪） |

响应示例：
```json
{
  "status": "ok",
  "checks": {
    "sqlite": { "status": "ok", "details": "" },
    "uploads_writable": { "status": "ok", "details": "" },
    "schema_version": { "status": "ok", "details": "version=1, expected>=1" }
  }
}
```

---

## 🌱 数据填充 (seed.py)

启动时自动执行数据填充，行为可通过环境变量控制：

| 环境变量 | 说明 |
|----------|------|
| `SKIP_SEED=1` | 完全跳过数据填充 |
| `FORCE_SEED=1` | 即使数据库非空也强制执行填充 |

默认行为：仅在**空数据库**（无相册、照片、标签、评论）时执行填充。

在 Docker Compose 中使用：
```yaml
environment:
  - SKIP_SEED=1
```

---

## 📂 备份与恢复

### 备份数据
```bash
bash scripts/backup.sh
```
备份包含 `data/`（SQLite 数据库）和 `uploads/`（上传图片），归档保存至 `backups/album_backup_YYYYMMDD_HHMMSS.tar.gz`。

可通过环境变量自定义备份目录：
```bash
BACKUP_DIR=/path/to/backups bash scripts/backup.sh
```

### 恢复数据
```bash
bash scripts/restore.sh backups/album_backup_20260101_120000.tar.gz
```
恢复时会自动将现有目录重命名为 `.bak.<timestamp>` 作为备份。

强制覆盖（无交互式确认）：
```bash
RESTORE_OVERWRITE=1 bash scripts/restore.sh backups/album_backup_20260101_120000.tar.gz
```

---

## 🐳 Docker Compose Profiles

### 默认模式（向后兼容）
```bash
docker compose up -d
```
启动 `web` 服务，包含开发模式（热重载、调试、双端口）。

### 开发模式 (dev profile)
```bash
docker compose --profile dev up web-dev -d
```
启动 `web-dev` 服务（显式指定服务名避免与默认 `web` 同时启动），配置如下：
- 源码热重载（volume 挂载 `./backend/app`）
- FLASK_DEBUG=1
- 双端口映射：31005 / 41005
- 健康检查使用 `/healthz`

### 生产模式 (prod profile)
```bash
docker compose --profile prod up web-prod -d
```
启动 `web-prod` 服务（显式指定服务名避免与默认 `web` 同时启动），生产环境优化：
- 无源码挂载，使用镜像内代码
- FLASK_DEBUG=0
- 仅单端口映射：31005
- 健康检查使用 `/readyz`（更严格）
- 更长的启动等待时间

---

## 📊 健康状态监控

查看容器健康状态：
```bash
docker compose ps
```

手动测试健康端点：
```bash
curl http://localhost:31005/healthz
curl http://localhost:31005/readyz
```

---

*本项目严格遵循 Prompt2Repo 核心开发规范与 AI 项目自控协议。*
