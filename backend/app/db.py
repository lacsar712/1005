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
    location_country = db.Column(db.String(100)) # 逆地理编码：国家
    location_province = db.Column(db.String(100)) # 逆地理编码：省/直辖市
    location_city = db.Column(db.String(100)) # 逆地理编码：城市
    location_district = db.Column(db.String(100)) # 逆地理编码：区/县
    location_address = db.Column(db.String(255)) # 逆地理编码：完整地址
    location_manual = db.Column(db.Boolean, default=False) # 是否为人工手动设置
    trip_id = db.Column(db.Integer, db.ForeignKey('trip.id', ondelete='SET NULL'), nullable=True)
    tags = db.relationship('Tag', secondary=photo_tags, backref=db.backref('photos', lazy='dynamic'), lazy='dynamic')
    comments = db.relationship('Comment', backref='photo', lazy=True, cascade="all, delete-orphan")

    @property
    def has_gps(self):
        return self.gps_latitude is not None and self.gps_longitude is not None

    @property
    def has_location(self):
        return (self.location_city is not None and self.location_city.strip()) or \
               (self.location_address is not None and self.location_address.strip())

    @property
    def location_short(self):
        parts = [p for p in [self.location_province, self.location_city, self.location_district] if p]
        return ' '.join(parts) if parts else None

    @property
    def location_display(self):
        if self.location_address:
            return self.location_address
        return self.location_short

class Trip(db.Model):
    """行程模型 - 将时空邻近的照片自动聚合为行程"""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200)) # 行程名称
    description = db.Column(db.Text) # 行程描述
    start_time = db.Column(db.DateTime) # 起始时间
    end_time = db.Column(db.DateTime) # 结束时间
    start_latitude = db.Column(db.Float) # 起始点纬度
    start_longitude = db.Column(db.Float) # 起始点经度
    end_latitude = db.Column(db.Float) # 结束点纬度
    end_longitude = db.Column(db.Float) # 结束点经度
    location_summary = db.Column(db.String(255)) # 行程地点摘要
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    photos = db.relationship('Photo', backref='trip', lazy='dynamic',
                             foreign_keys='Photo.trip_id')

    @property
    def photo_count(self):
        return self.photos.count()

    @property
    def route_points(self):
        """返回有序的坐标点列表用于绘制 polyline"""
        result = []
        for p in self.photos.order_by(db.func.coalesce(Photo.taken_at, Photo.uploaded_at).asc()).all():
            if p.gps_latitude is not None and p.gps_longitude is not None:
                result.append([p.gps_latitude, p.gps_longitude])
        return result

    @property
    def time_span_str(self):
        if not self.start_time or not self.end_time:
            return ''
        if self.start_time.date() == self.end_time.date():
            return f"{self.start_time.strftime('%Y-%m-%d %H:%M')} ~ {self.end_time.strftime('%H:%M')}"
        return f"{self.start_time.strftime('%Y-%m-%d %H:%M')} ~ {self.end_time.strftime('%Y-%m-%d %H:%M')}"

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name or ('行程 ' + str(self.id)),
            'description': self.description,
            'start_time': self.start_time.strftime('%Y-%m-%d %H:%M:%S') if self.start_time else None,
            'end_time': self.end_time.strftime('%Y-%m-%d %H:%M:%S') if self.end_time else None,
            'time_span': self.time_span_str,
            'photo_count': self.photo_count,
            'location_summary': self.location_summary,
            'route_points': self.route_points,
        }


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
        'photo_tag_update': '更新照片标签',
        'photo_location_update': '更新照片地点',
        'tag_create': '创建标签',
        'tag_rename': '重命名标签',
        'tag_delete': '删除标签',
        'comment_delete': '删除评论',
        'settings_update': '更新站点设置',
        'export_zip': 'ZIP导出',
        'recycle_bin_clear': '清空回收站',
        'recycle_bin_restore': '从回收站恢复',
        'webhook_create': '创建Webhook',
        'webhook_update': '更新Webhook',
        'webhook_delete': '删除Webhook',
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


class ExportJob(db.Model):
    """导出任务模型"""

    STATUS_PENDING = 'pending'
    STATUS_PROCESSING = 'processing'
    STATUS_COMPLETED = 'completed'
    STATUS_FAILED = 'failed'

    id = db.Column(db.Integer, primary_key=True)
    album_id = db.Column(db.Integer, db.ForeignKey('album.id'), nullable=False, index=True)
    status = db.Column(db.String(20), nullable=False, default=STATUS_PENDING, index=True)
    progress = db.Column(db.Integer, nullable=False, default=0)
    total_photos = db.Column(db.Integer, nullable=False, default=0)
    processed_photos = db.Column(db.Integer, nullable=False, default=0)
    options = db.Column(JSONType)
    zip_filename = db.Column(db.String(200))
    file_size = db.Column(db.Integer, default=0)
    error_message = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    completed_at = db.Column(db.DateTime)
    expires_at = db.Column(db.DateTime)

    album = db.relationship('Album', backref=db.backref('export_jobs', lazy='dynamic'))

    @property
    def is_ready(self):
        return self.status == self.STATUS_COMPLETED and self.zip_filename is not None

    def to_dict(self):
        return {
            'id': self.id,
            'album_id': self.album_id,
            'status': self.status,
            'progress': self.progress,
            'total_photos': self.total_photos,
            'processed_photos': self.processed_photos,
            'options': self.options or {},
            'zip_filename': self.zip_filename,
            'file_size': self.file_size,
            'error_message': self.error_message,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None,
            'completed_at': self.completed_at.strftime('%Y-%m-%d %H:%M:%S') if self.completed_at else None,
            'is_ready': self.is_ready,
        }


class DownloadHistory(db.Model):
    """下载历史记录模型"""

    id = db.Column(db.Integer, primary_key=True)
    album_id = db.Column(db.Integer, db.ForeignKey('album.id'), nullable=False, index=True)
    export_job_id = db.Column(db.Integer, db.ForeignKey('export_job.id'), nullable=True)
    album_title = db.Column(db.String(100), nullable=False)
    zip_filename = db.Column(db.String(200), nullable=False)
    file_size = db.Column(db.Integer, default=0)
    photo_count = db.Column(db.Integer, default=0)
    options = db.Column(JSONType)
    ip_address = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    album = db.relationship('Album', backref=db.backref('download_histories', lazy='dynamic'))
    export_job = db.relationship('ExportJob', backref=db.backref('download_histories', lazy='dynamic'))

    @property
    def file_exists(self):
        from .app import EXPORT_FOLDER
        if not self.zip_filename:
            return False
        import os
        return os.path.isfile(os.path.join(EXPORT_FOLDER, self.zip_filename))

    def to_dict(self):
        return {
            'id': self.id,
            'album_id': self.album_id,
            'export_job_id': self.export_job_id,
            'album_title': self.album_title,
            'zip_filename': self.zip_filename,
            'file_size': self.file_size,
            'file_size_human': format_bytes_human(self.file_size or 0),
            'photo_count': self.photo_count,
            'options': self.options or {},
            'ip_address': self.ip_address,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None,
            'file_exists': self.file_exists,
        }


class Notification(db.Model):
    """通知模型"""

    TYPE_UPLOAD = 'upload'
    TYPE_UPLOAD_BATCH = 'upload_batch'
    TYPE_DELETE = 'delete'
    TYPE_DELETE_BATCH = 'delete_batch'
    TYPE_EXPORT_ZIP = 'export_zip'
    TYPE_RECYCLE_CLEAR = 'recycle_clear'
    TYPE_SYSTEM = 'system'

    TYPE_LABELS = {
        TYPE_UPLOAD: '上传成功',
        TYPE_UPLOAD_BATCH: '批量上传',
        TYPE_DELETE: '删除成功',
        TYPE_DELETE_BATCH: '批量删除',
        TYPE_EXPORT_ZIP: 'ZIP 导出',
        TYPE_RECYCLE_CLEAR: '回收站清理',
        TYPE_SYSTEM: '系统通知',
    }

    STATUS_PENDING = 'pending'
    STATUS_SUCCESS = 'success'
    STATUS_FAILED = 'failed'
    STATUS_PARTIAL = 'partial'

    MAX_RETENTION = 100

    id = db.Column(db.Integer, primary_key=True)
    type = db.Column(db.String(50), nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text)
    status = db.Column(db.String(20), nullable=False, default=STATUS_SUCCESS, index=True)
    is_read = db.Column(db.Boolean, default=False, index=True)
    task_id = db.Column(db.String(100), index=True)
    parent_id = db.Column(db.Integer, db.ForeignKey('notification.id', ondelete='CASCADE'))
    data = db.Column(JSONType)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    read_at = db.Column(db.DateTime)

    parent = db.relationship('Notification', remote_side=[id], backref=db.backref('children', lazy='dynamic', cascade='all, delete-orphan'))

    @property
    def type_label(self):
        return self.TYPE_LABELS.get(self.type, self.type)

    @property
    def is_aggregated(self):
        return self.children.count() > 0

    @property
    def children_count(self):
        return self.children.count()

    @property
    def unread_children_count(self):
        return self.children.filter_by(is_read=False).count()

    def to_dict(self, include_children=False):
        data = {
            'id': self.id,
            'type': self.type,
            'type_label': self.type_label,
            'title': self.title,
            'content': self.content,
            'status': self.status,
            'is_read': self.is_read,
            'task_id': self.task_id,
            'parent_id': self.parent_id,
            'data': self.data or {},
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None,
            'read_at': self.read_at.strftime('%Y-%m-%d %H:%M:%S') if self.read_at else None,
            'is_aggregated': self.is_aggregated,
            'children_count': self.children_count,
            'unread_children_count': self.unread_children_count,
        }
        if include_children:
            data['children'] = [c.to_dict(include_children=False) for c in self.children.order_by(Notification.created_at.desc()).all()]
        return data


class WebhookConfig(db.Model):
    """Webhook 配置模型"""

    EVENT_TYPES = {
        'upload': '上传事件',
        'delete': '删除事件',
        'export_zip': 'ZIP 导出事件',
        'recycle_clear': '回收站清理事件',
        'system': '系统事件',
        'all': '所有事件',
    }

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    url = db.Column(db.String(500), nullable=False)
    secret = db.Column(db.String(100))
    event_types = db.Column(JSONType)
    is_active = db.Column(db.Boolean, default=True)
    last_triggered_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @property
    def event_types_display(self):
        types = self.event_types or []
        labels = [self.EVENT_TYPES.get(t, t) for t in types]
        return '、'.join(labels) or '无'

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'url': self.url,
            'secret': self.secret,
            'event_types': self.event_types or [],
            'is_active': self.is_active,
            'last_triggered_at': self.last_triggered_at.strftime('%Y-%m-%d %H:%M:%S') if self.last_triggered_at else None,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None,
            'updated_at': self.updated_at.strftime('%Y-%m-%d %H:%M:%S') if self.updated_at else None,
        }


def format_bytes_human(num_bytes):
    if num_bytes < 1024:
        return f"{num_bytes} B"
    elif num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f} KB"
    elif num_bytes < 1024 * 1024 * 1024:
        return f"{num_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{num_bytes / (1024 * 1024 * 1024):.2f} GB"
