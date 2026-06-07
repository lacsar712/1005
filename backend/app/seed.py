import os
from .app import create_app
from .db import db, Album, Photo, Tag, Comment, SiteConfig
import datetime


def is_database_empty():
    try:
        if Album.query.count() > 0:
            return False
        if Photo.query.count() > 0:
            return False
        if Tag.query.count() > 0:
            return False
        if Comment.query.count() > 0:
            return False
        return True
    except Exception:
        return True


def seed():
    skip_seed = os.environ.get('SKIP_SEED', '').lower() in ('1', 'true', 'yes')
    force_seed = os.environ.get('FORCE_SEED', '').lower() in ('1', 'true', 'yes')

    if skip_seed:
        print("⏭️  SKIP_SEED 已设置，跳过数据填充。")
        return

    app = create_app()
    with app.app_context():
        db_empty = is_database_empty()

        if not db_empty and not force_seed:
            print("✨ 数据库已存在数据，跳过填充。（使用 FORCE_SEED=1 强制执行）")
            return

        if force_seed and not db_empty:
            print("⚠️  FORCE_SEED 已设置，将对非空数据库执行填充...")

        print("🌱 正在进行初始数据填充...")

        if Album.query.count() == 0:
            default_album = Album(
                title="我的精选相册",
                description="这是系统自动生成的初始相册，用于展示功能。"
            )
            db.session.add(default_album)
            db.session.commit()
        else:
            default_album = Album.query.first()

        sample_comments = [
            {'nickname': '小明', 'content': '这张照片拍得真好看！'},
            {'nickname': '匿名访客', 'content': '光影效果很棒，学习了。'},
            {'nickname': '旅行者', 'content': '构图很有意境，点赞！'},
            {'nickname': '摄影爱好者', 'content': '色彩处理得很好看，请问用了什么滤镜？'},
            {'nickname': '路人甲', 'content': '非常漂亮的作品！'},
            {'nickname': '小红', 'content': '太棒了，收藏了！'},
            {'nickname': '匿名访客', 'content': '期待更多作品~'}
        ]

        photos = Photo.query.filter_by(album_id=default_album.id).all()
        for idx, photo in enumerate(photos):
            existing_comments = Comment.query.filter_by(photo_id=photo.id).count()
            if existing_comments > 0 and not force_seed:
                continue
            for i, c in enumerate(sample_comments[:min(len(sample_comments), 3 + idx)]):
                comment = Comment(
                    photo_id=photo.id,
                    nickname=c['nickname'],
                    content=c['content'],
                    created_at=datetime.datetime.utcnow() - datetime.timedelta(hours=i)
                )
                db.session.add(comment)
        db.session.commit()

        print("✅ 数据填充完成。")


if __name__ == '__main__':
    seed()
