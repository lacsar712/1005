import json
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import TypeDecorator, Text

db = SQLAlchemy()


class JSONType(TypeDecorator):
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return json.dumps(value, ensure_ascii=False)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return value

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
    description = db.Column(db.Text) # 照片说明
    album_id = db.Column(db.Integer, db.ForeignKey('album.id'), nullable=False) # 所属相册 ID
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow) # 上传时间 (UTC)
    camera_model = db.Column(db.String(100)) # EXIF: 相机型号
    taken_at = db.Column(db.DateTime) # EXIF: 拍摄时间
    gps_latitude = db.Column(db.Float) # EXIF: GPS 纬度
    gps_longitude = db.Column(db.Float) # EXIF: GPS 经度
    image_format = db.Column(db.String(10)) # 图片格式 (jpg/png/gif/webp)
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

class SiteConfig(db.Model):
    """站点配置模型"""
    id = db.Column(db.Integer, primary_key=True)
    config_key = db.Column(db.String(100), nullable=False, unique=True)
    config_value = db.Column(db.Text, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class OperationLog(db.Model):
    """操作日志模型"""

    OPERATION_TYPES = {
        'auth_login': '登录',
        'auth_logout': '登出',
        'album_create': '创建相册',
        'album_edit': '编辑相册',
        'album_delete': '删除相册',
        'photo_upload': '上传照片',
        'photo_delete': '删除照片',
        'photo_move': '移动照片',
        'photo_batch_delete': '批量删除照片',
        'photo_batch_rename': '批量重命名照片',
        'photo_batch_move': '批量移动照片',
        'tag_create': '创建标签',
        'tag_rename': '重命名标签',
        'tag_delete': '删除标签',
        'photo_tag_update': '更新照片标签',
        'comment_delete': '删除评论',
        'settings_update': '更新站点设置',
        'export_zip': 'ZIP导出',
        'recycle_bin_clear': '清空回收站',
        'recycle_bin_restore': '从回收站恢复',
    }

    id = db.Column(db.Integer, primary_key=True)
    operation_type = db.Column(db.String(50), nullable=False, index=True)
    summary = db.Column(db.String(500), nullable=False)
    resource_type = db.Column(db.String(50))
    resource_id = db.Column(db.String(100))
    ip_address = db.Column(db.String(50))
    user_agent = db.Column(db.String(500))
    before_data = db.Column(JSONType)
    after_data = db.Column(JSONType)
    parent_id = db.Column(db.Integer, db.ForeignKey('operation_log.id', ondelete='CASCADE'))
    is_anomaly = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    parent = db.relationship('OperationLog', remote_side=[id], backref=db.backref('children', lazy='dynamic', cascade='all, delete-orphan'))

    @property
    def operation_type_label(self):
        return self.OPERATION_TYPES.get(self.operation_type, self.operation_type)

    def to_dict(self, include_children=False):
        data = {
            'id': self.id,
            'operation_type': self.operation_type,
            'operation_type_label': self.operation_type_label,
            'summary': self.summary,
            'resource_type': self.resource_type,
            'resource_id': self.resource_id,
            'ip_address': self.ip_address,
            'is_anomaly': self.is_anomaly,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None,
            'has_snapshot': self.before_data is not None or self.after_data is not None,
            'has_children': self.children.count() > 0 if include_children else False,
        }
        if include_children:
            data['children'] = [c.to_dict(include_children=False) for c in self.children.all()]
        return data
