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
*本项目严格遵循 Prompt2Repo 核心开发规范与 AI 项目自控协议。*
