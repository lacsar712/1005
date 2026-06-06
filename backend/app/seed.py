from .app import create_app
from .db import db, Album, Photo, Tag, Comment, SiteConfig
import datetime

def seed():
    app = create_app()
    with app.app_context():
        if Album.query.count() == 0:
            print("🌱 正在进行初始数据填充...")
            default_album = Album(
                title="我的精选相册", 
                description="这是系统自动生成的初始相册，用于展示功能。"
            )
            db.session.add(default_album)
            db.session.commit()

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
        else:
            print("✨ 数据库已存在数据，跳过填充。")

if __name__ == '__main__':
    seed()
