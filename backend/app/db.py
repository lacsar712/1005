from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

photo_tags = db.Table('photo_tags',
    db.Column('photo_id', db.Integer, db.ForeignKey('photo.id', ondelete='CASCADE'), primary_key=True),
    db.Column('tag_id', db.Integer, db.ForeignKey('tag.id', ondelete='CASCADE'), primary_key=True)
)

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
    tags = db.relationship('Tag', secondary=photo_tags, backref=db.backref('photos', lazy='dynamic'), lazy='dynamic')
    comments = db.relationship('Comment', backref='photo', lazy=True, cascade="all, delete-orphan")

class Comment(db.Model):
    """照片评论模型"""
    id = db.Column(db.Integer, primary_key=True)
    photo_id = db.Column(db.Integer, db.ForeignKey('photo.id', ondelete='CASCADE'), nullable=False)
    nickname = db.Column(db.String(50), nullable=False, default='匿名访客')
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Tag(db.Model):
    """标签模型"""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False, unique=True) # 标签名称 (唯一)
    created_at = db.Column(db.DateTime, default=datetime.utcnow) # 创建时间 (UTC)
