#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKUP_DIR="${BACKUP_DIR:-$PROJECT_ROOT/backups}"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP_NAME="album_backup_${TIMESTAMP}.tar.gz"
BACKUP_PATH="$BACKUP_DIR/$BACKUP_NAME"

DATA_DIR="$PROJECT_ROOT/data"
UPLOADS_DIR="$PROJECT_ROOT/uploads"

echo "📦 在线相册系统备份工具"
echo "================================"
echo "项目根目录: $PROJECT_ROOT"
echo "备份目录:   $BACKUP_DIR"
echo "备份文件:   $BACKUP_PATH"
echo ""

mkdir -p "$BACKUP_DIR"

if [ ! -d "$DATA_DIR" ] && [ ! -d "$UPLOADS_DIR" ]; then
    echo "⚠️  未找到 data/ 或 uploads/ 目录，无需备份。"
    exit 0
fi

echo "🔍 检查待备份内容..."
CONTENTS=""
if [ -d "$DATA_DIR" ]; then
    DATA_SIZE=$(du -sh "$DATA_DIR" 2>/dev/null | awk '{print $1}')
    echo "  data/      : 存在 (约 $DATA_SIZE)"
    CONTENTS="$CONTENTS data"
fi
if [ -d "$UPLOADS_DIR" ]; then
    UPLOADS_SIZE=$(du -sh "$UPLOADS_DIR" 2>/dev/null | awk '{print $1}')
    echo "  uploads/   : 存在 (约 $UPLOADS_SIZE)"
    CONTENTS="$CONTENTS uploads"
fi

echo ""
echo "🚀 开始创建备份归档..."

cd "$PROJECT_ROOT"
tar -czf "$BACKUP_PATH" $CONTENTS

BACKUP_SIZE=$(du -sh "$BACKUP_PATH" | awk '{print $1}')
echo ""
echo "✅ 备份完成！"
echo "   文件: $BACKUP_PATH"
echo "   大小: $BACKUP_SIZE"
echo ""
echo "💡 恢复命令: bash scripts/restore.sh $BACKUP_PATH"
