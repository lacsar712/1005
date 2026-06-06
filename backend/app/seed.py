from .app import create_app
from .db import db, Album, Photo, Tag
import datetime

def seed():
    app = create_app()
    with app.app_context():
        # 清理旧数据 (保持幂等)
        if Album.query.count() == 0:
            print("🌱 正在进行初始数据填充...")
            # 创建默认相册
            default_album = Album(
                title="我的精选相册", 
                description="这是系统自动生成的初始相册，用于展示功能。"
            )
            db.session.add(default_album)
            db.session.commit()
            print("✅ 数据填充完成。")
        else:
            print("✨ 数据库已存在数据，跳过填充。")

if __name__ == '__main__':
    seed()
