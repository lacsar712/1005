from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class Album(db.Model):
    """相册模型"""
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False) # 相册标题
    description = db.Column(db.Text) # 相册描述
    created_at = db.Column(db.DateTime, default=datetime.utcnow) # 创建时间 (UTC)
    photos = db.relationship('Photo', backref='album', lazy=True, cascade="all, delete-orphan")

class Photo(db.Model):
    """照片模型"""
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(100), nullable=False) # 存储的文件名 (UUID)
    original_filename = db.Column(db.String(100), nullable=False) # 原始文件名
    album_id = db.Column(db.Integer, db.ForeignKey('album.id'), nullable=False) # 所属相册 ID
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow) # 上传时间 (UTC)
