#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

usage() {
    echo "📦 在线相册系统恢复工具"
    echo "================================"
    echo ""
    echo "用法: $0 <备份文件路径>"
    echo ""
    echo "示例:"
    echo "  $0 backups/album_backup_20260101_120000.tar.gz"
    echo ""
    echo "环境变量:"
    echo "  RESTORE_OVERWRITE=1   强制覆盖现有数据（不交互式确认）"
    exit 1
}

if [ $# -lt 1 ]; then
    usage
fi

BACKUP_FILE="$1"

if [ ! -f "$BACKUP_FILE" ]; then
    echo "❌ 错误: 备份文件不存在: $BACKUP_FILE"
    exit 1
fi

if [[ ! "$BACKUP_FILE" == *.tar.gz ]]; then
    echo "❌ 错误: 备份文件格式不正确，应为 .tar.gz 文件"
    exit 1
fi

echo "📦 在线相册系统恢复工具"
echo "================================"
echo "项目根目录: $PROJECT_ROOT"
echo "备份文件:   $BACKUP_FILE"
echo ""

OVERWRITE="${RESTORE_OVERWRITE:-0}"

DATA_DIR="$PROJECT_ROOT/data"
UPLOADS_DIR="$PROJECT_ROOT/uploads"

HAS_EXISTING_DATA=0
if [ -d "$DATA_DIR" ] && [ "$(ls -A "$DATA_DIR" 2>/dev/null)" ]; then
    HAS_EXISTING_DATA=1
fi
if [ -d "$UPLOADS_DIR" ] && [ "$(ls -A "$UPLOADS_DIR" 2>/dev/null)" ]; then
    HAS_EXISTING_DATA=1
fi

if [ "$HAS_EXISTING_DATA" -eq 1 ] && [ "$OVERWRITE" != "1" ]; then
    echo "⚠️  检测到现有数据:"
    [ -d "$DATA_DIR" ] && [ "$(ls -A "$DATA_DIR" 2>/dev/null)" ] && echo "  data/      : 存在数据"
    [ -d "$UPLOADS_DIR" ] && [ "$(ls -A "$UPLOADS_DIR" 2>/dev/null)" ] && echo "  uploads/   : 存在数据"
    echo ""
    read -p "是否覆盖现有数据？此操作不可撤销！(yes/N): " confirm
    if [[ ! "$confirm" =~ ^[Yy][Ee][Ss]$ ]]; then
        echo "⏹️  已取消恢复操作。"
        exit 0
    fi
fi

echo "🔍 验证备份文件..."
if ! tar -tzf "$BACKUP_FILE" > /dev/null 2>&1; then
    echo "❌ 错误: 备份文件损坏或格式无效"
    exit 1
fi

BACKUP_CONTENTS=$(tar -tzf "$BACKUP_FILE" | head -20)
echo "📋 备份内容预览:"
echo "$BACKUP_CONTENTS" | sed 's/^/  /'
echo ""

echo "🚀 开始恢复数据..."

if [ "$OVERWRITE" = "1" ]; then
    echo "⚠️  RESTORE_OVERWRITE=1，将覆盖现有数据..."
fi

if [ -d "$DATA_DIR" ]; then
    if [ "$(ls -A "$DATA_DIR" 2>/dev/null)" ]; then
        DATA_BACKUP="$PROJECT_ROOT/data.bak.$(date +%Y%m%d_%H%M%S)"
        echo "💾 备份现有 data/ 目录至: $DATA_BACKUP"
        mv "$DATA_DIR" "$DATA_BACKUP"
    fi
fi

if [ -d "$UPLOADS_DIR" ]; then
    if [ "$(ls -A "$UPLOADS_DIR" 2>/dev/null)" ]; then
        UPLOADS_BACKUP="$PROJECT_ROOT/uploads.bak.$(date +%Y%m%d_%H%M%S)"
        echo "💾 备份现有 uploads/ 目录至: $UPLOADS_BACKUP"
        mv "$UPLOADS_DIR" "$UPLOADS_BACKUP"
    fi
fi

tar -xzf "$BACKUP_FILE" -C "$PROJECT_ROOT"

echo ""
echo "✅ 恢复完成！"
echo ""
echo "📁 已恢复内容:"
[ -d "$DATA_DIR" ] && echo "  data/      : $(find "$DATA_DIR" -type f | wc -l) 个文件"
[ -d "$UPLOADS_DIR" ] && echo "  uploads/   : $(find "$UPLOADS_DIR" -type f | wc -l) 个文件"
echo ""
echo "💡 提示: 请重启 Docker 容器以加载恢复的数据:"
echo "   docker compose restart"
