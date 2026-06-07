import io
import csv
import os
import re
import uuid
import json
import zipfile
import threading
import time
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash, abort, send_from_directory, jsonify, make_response, send_file
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.utils import secure_filename
from sqlalchemy import or_, and_, func
from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS
import requests
from .db import db, Album, Photo, Tag, Comment, SiteConfig, OperationLog, ExportJob, DownloadHistory, Trip, format_bytes_human, Notification, WebhookConfig, migrate_schema
from .services import NotificationService, AggregationService, WebhookService, CleanupService


def dispatch_notification(
    type,
    title,
    content=None,
    status=Notification.STATUS_SUCCESS,
    task_id=None,
    parent_id=None,
    data=None,
):
    notif = NotificationService.create(
        type=type, title=title, content=content, status=status,
        task_id=task_id, parent_id=parent_id, data=data,
    )
    WebhookService.dispatch(notif)
    CleanupService.cleanup_if_needed()
    return notif

# 常量设置
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static/uploads')
EXPORT_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static/exports')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
EXPORT_EXPIRE_DAYS = 7

# 管理员配置
ADMIN_USERNAME = 'admin'
ADMIN_PASSWORD = '123456'  # 演示用简单密码

class User(UserMixin):
    def __init__(self, id):
        self.id = id

def allowed_file(filename):
    """验证文件后缀名"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_client_ip():
    if request.headers.getlist('X-Forwarded-For'):
        return request.headers.getlist('X-Forwarded-For')[0]
    if request.headers.get('X-Real-IP'):
        return request.headers.get('X-Real-IP')
    return request.remote_addr or 'unknown'


def detect_anomaly(operation_type, count=1):
    if operation_type in ('photo_delete', 'photo_batch_delete', 'album_delete', 'recycle_bin_clear'):
        if count >= 10:
            return True
        time_window = datetime.utcnow() - timedelta(minutes=5)
        recent_count = OperationLog.query.filter(
            OperationLog.operation_type.in_(['photo_delete', 'photo_batch_delete', 'album_delete']),
            OperationLog.created_at >= time_window
        ).count()
        if recent_count + count >= 20:
            return True
    if operation_type in ('export_zip',):
        if count >= 50:
            return True
    return False


def log_operation(operation_type, summary, resource_type=None, resource_id=None,
                  before_data=None, after_data=None, parent_id=None, is_anomaly=None, commit=True):
    if is_anomaly is None:
        is_anomaly = detect_anomaly(operation_type)
    log = OperationLog(
        operation_type=operation_type,
        summary=summary[:500],
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id is not None else None,
        ip_address=get_client_ip(),
        user_agent=request.user_agent.string[:500] if request and request.user_agent else None,
        before_data=before_data,
        after_data=after_data,
        parent_id=parent_id,
        is_anomaly=is_anomaly,
    )
    db.session.add(log)
    if commit:
        db.session.commit()
    return log


def model_snapshot(model, exclude_fields=None):
    if not model:
        return None
    exclude = exclude_fields or []
    data = {}
    for col in model.__table__.columns:
        if col.name in exclude:
            continue
        val = getattr(model, col.name)
        if isinstance(val, datetime):
            val = val.strftime('%Y-%m-%d %H:%M:%S')
        data[col.name] = val
    return data


def diff_snapshots(before, after):
    if not before or not after:
        return []
    diffs = []
    all_keys = set(before.keys()) | set(after.keys())
    for key in sorted(all_keys):
        b = before.get(key)
        a = after.get(key)
        if b != a:
            diffs.append({'field': key, 'before': b, 'after': a})
    return diffs


def levenshtein_distance(s1, s2):
    """计算两个字符串之间的编辑距离"""
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)
    s1 = s1.lower()
    s2 = s2.lower()
    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    return previous_row[-1]


def fuzzy_match(query, text, max_distance=2):
    """判断文本是否匹配查询：支持子串包含 + 基于编辑距离的模糊容错"""
    if not query or not text:
        return False
    q = query.lower().strip()
    t = text.lower()
    if not q:
        return False
    if q in t:
        return True
    words = t.split()
    for word in words:
        word_clean = word.strip(' ,.;:!?()[]{}"\'')
        if not word_clean:
            continue
        if q in word_clean:
            return True
        word_len = len(word_clean)
        query_len = len(q)
        if word_len < 3 or query_len < 3:
            continue
        allowed = max_distance if max(word_len, query_len) >= 5 else 1
        if levenshtein_distance(q, word_clean) <= allowed:
            return True
    return False


def highlight_keywords(text, query):
    """在文本中高亮匹配的关键词，返回带 <mark> 的 HTML"""
    if not text or not query:
        return text or ''
    q = query.strip()
    if not q:
        return text
    q_lower = q.lower()
    text_lower = text.lower()
    result = []
    i = 0
    used = set()
    while i < len(text):
        matched = False
        for length in range(min(len(q) + 3, len(text) - i), max(1, len(q) - 3), -1):
            if length <= 0:
                continue
            segment = text_lower[i:i + length]
            if q_lower in segment:
                idx = segment.find(q_lower)
                result.append(text[i:i + idx])
                result.append(f'<mark class="bg-yellow-200 text-yellow-900 px-0.5 rounded">{text[i + idx:i + idx + len(q)]}</mark>')
                i += idx + len(q)
                matched = True
                break
            if levenshtein_distance(q_lower, segment) <= 2 and length >= 3:
                result.append(f'<mark class="bg-yellow-100 text-yellow-800 px-0.5 rounded border border-yellow-300">{text[i:i + length]}</mark>')
                i += length
                matched = True
                break
        if not matched:
            result.append(text[i])
            i += 1
    return ''.join(result)


def _dms_to_degrees(dms, ref):
    """将 EXIF GPS 的度分秒转换为十进制度数"""
    try:
        degrees = float(dms[0])
        minutes = float(dms[1])
        seconds = float(dms[2])
        result = degrees + (minutes / 60.0) + (seconds / 3600.0)
        if ref in ('S', 'W'):
            result = -result
        return result
    except Exception:
        return None


def extract_exif(file_path):
    """从图片文件提取 EXIF 信息，返回字典"""
    result = {
        'camera_model': None,
        'taken_at': None,
        'gps_latitude': None,
        'gps_longitude': None,
    }
    try:
        with Image.open(file_path) as img:
            exif_data = img._getexif()
            if not exif_data:
                return result
            exif = {}
            for tag_id, value in exif_data.items():
                tag = TAGS.get(tag_id, tag_id)
                exif[tag] = value
            make = exif.get('Make', '')
            model = exif.get('Model', '')
            camera = ' '.join([str(make).strip(), str(model).strip()]).strip()
            if camera:
                result['camera_model'] = camera[:100]
            dt_original = exif.get('DateTimeOriginal') or exif.get('DateTime')
            if dt_original:
                try:
                    result['taken_at'] = datetime.strptime(str(dt_original), '%Y:%m:%d %H:%M:%S')
                except (ValueError, TypeError):
                    pass
            gps_info_tag = None
            for tag_id, value in exif_data.items():
                if TAGS.get(tag_id) == 'GPSInfo':
                    gps_info_tag = value
                    break
            if gps_info_tag:
                gps = {}
                for k, v in gps_info_tag.items():
                    gps[GPSTAGS.get(k, k)] = v
                lat = gps.get('GPSLatitude')
                lat_ref = gps.get('GPSLatitudeRef')
                lon = gps.get('GPSLongitude')
                lon_ref = gps.get('GPSLongitudeRef')
                if lat and lat_ref:
                    result['gps_latitude'] = _dms_to_degrees(lat, lat_ref)
                if lon and lon_ref:
                    result['gps_longitude'] = _dms_to_degrees(lon, lon_ref)
    except Exception:
        pass
    return result


def get_image_format(filename):
    """从文件名获取图片格式"""
    if '.' in filename:
        ext = filename.rsplit('.', 1)[1].lower()
        if ext == 'jpeg':
            ext = 'jpg'
        return ext
    return None


def reverse_geocode(latitude, longitude):
    """
    使用 Nominatim (OpenStreetMap) 进行逆地理编码
    返回 {country, province, city, district, address}
    失败或无结果返回 None
    """
    if latitude is None or longitude is None:
        return None
    try:
        url = "https://nominatim.openstreetmap.org/reverse"
        params = {
            'lat': str(latitude),
            'lon': str(longitude),
            'format': 'json',
            'zoom': 14,
            'addressdetails': 1,
            'accept-language': 'zh-CN'
        }
        headers = {
            'User-Agent': 'PhotoAlbumApp/1.0 (local)'
        }
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        if resp.status_code != 200:
            return None
        data = resp.json()
        if not data or 'address' not in data:
            return None
        addr = data['address']
        result = {
            'country': addr.get('country'),
            'province': addr.get('state') or addr.get('province'),
            'city': addr.get('city') or addr.get('town') or addr.get('county'),
            'district': addr.get('suburb') or addr.get('district') or addr.get('township'),
            'address': data.get('display_name')
        }
        for k, v in list(result.items()):
            if isinstance(v, str):
                result[k] = v.strip() or None
        if not any(result.values()):
            return None
        return result
    except Exception:
        return None


def haversine_distance(lat1, lon1, lat2, lon2):
    """
    计算两点间的 Haversine 距离（米）
    """
    if None in (lat1, lon1, lat2, lon2):
        return float('inf')
    import math
    R = 6371000
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def infer_trips(photo_ids=None, min_photos=2, time_gap_hours=6, distance_gap_meters=5000):
    """
    基于时空邻近性推断行程
    :param photo_ids: 限定只处理这些照片ID（None表示全部有GPS的照片）
    :param min_photos: 形成行程最少照片数
    :param time_gap_hours: 两张照片超过此时间差则断开
    :param distance_gap_meters: 两张照片超过此距离则断开
    """
    query = Photo.query.filter(
        Photo.gps_latitude.isnot(None),
        Photo.gps_longitude.isnot(None)
    )
    if photo_ids:
        query = query.filter(Photo.id.in_(photo_ids))
    all_photos = query.order_by(func.coalesce(Photo.taken_at, Photo.uploaded_at).asc()).all()
    if len(all_photos) < min_photos:
        return

    clusters = []
    current_cluster = []
    prev_photo = None

    for photo in all_photos:
        if prev_photo is None:
            current_cluster = [photo]
            prev_photo = photo
            continue
        prev_time = prev_photo.taken_at or prev_photo.uploaded_at
        curr_time = photo.taken_at or photo.uploaded_at
        time_diff = (curr_time - prev_time).total_seconds() / 3600.0 if prev_time and curr_time else float('inf')
        dist = haversine_distance(
            prev_photo.gps_latitude, prev_photo.gps_longitude,
            photo.gps_latitude, photo.gps_longitude
        )
        if time_diff > time_gap_hours or dist > distance_gap_meters:
            if len(current_cluster) >= min_photos:
                clusters.append(current_cluster)
            current_cluster = [photo]
        else:
            current_cluster.append(photo)
        prev_photo = photo

    if len(current_cluster) >= min_photos:
        clusters.append(current_cluster)

    for cluster in clusters:
        sorted_photos = sorted(
            cluster,
            key=lambda p: (p.taken_at or p.uploaded_at or datetime.min)
        )
        first_p = sorted_photos[0]
        last_p = sorted_photos[-1]
        start_time = first_p.taken_at or first_p.uploaded_at
        end_time = last_p.taken_at or last_p.uploaded_at

        locations = set()
        for p in sorted_photos:
            loc = p.location_short
            if loc:
                locations.add(loc)
        loc_summary = ' → '.join(list(locations)[:3]) if locations else None

        same_trip_ids = set()
        for p in sorted_photos:
            if p.trip_id:
                same_trip_ids.add(p.trip_id)

        trip = None
        if len(same_trip_ids) == 1:
            trip = Trip.query.get(list(same_trip_ids)[0])

        if trip is None:
            trip = Trip()
            db.session.add(trip)
            db.session.flush()

        trip.start_time = start_time
        trip.end_time = end_time
        trip.start_latitude = first_p.gps_latitude
        trip.start_longitude = first_p.gps_longitude
        trip.end_latitude = last_p.gps_latitude
        trip.end_longitude = last_p.gps_longitude
        trip.location_summary = loc_summary

        date_str = start_time.strftime('%Y-%m-%d') if start_time else '未知日期'
        city_str = ''
        for p in sorted_photos:
            if p.location_city:
                city_str = p.location_city
                break
        if city_str:
            trip.name = f"{city_str}之旅 · {date_str}"
        else:
            trip.name = f"行程 · {date_str}"

        for p in sorted_photos:
            p.trip_id = trip.id

    db.session.commit()


def process_photo_location(photo):
    """
    为照片处理逆地理编码（已有GPS且未手动设置地点时）
    """
    if photo.location_manual:
        return
    if photo.gps_latitude is None or photo.gps_longitude is None:
        return
    if photo.location_city or photo.location_address:
        return
    result = reverse_geocode(photo.gps_latitude, photo.gps_longitude)
    if result:
        photo.location_country = result.get('country')
        photo.location_province = result.get('province')
        photo.location_city = result.get('city')
        photo.location_district = result.get('district')
        photo.location_address = result.get('address')


def process_uploaded_locations_async(app_instance, photo_ids):
    """
    后台线程：为刚上传的照片批量处理逆地理编码 + 行程推断
    """
    with app_instance.app_context():
        try:
            for pid in photo_ids:
                photo = Photo.query.get(pid)
                if not photo:
                    continue
                process_photo_location(photo)
                time.sleep(1.0)
            db.session.commit()
            infer_trips(photo_ids=photo_ids)
        except Exception:
            pass


DEFAULT_SITE_CONFIG = {
    'site_name': '在线相册',
    'welcome_message': '欢迎来到在线相册系统',
    'copyright_text': '© 2026 在线相册系统. 保留所有权利。',
    'contact_email': 'admin@example.com',
    'max_upload_size_mb': '5',
    'album_sort_by': 'created_at',
    'show_site_stats': 'true'
}

def get_site_config():
    """获取所有站点配置，返回字典"""
    configs = SiteConfig.query.all()
    result = dict(DEFAULT_SITE_CONFIG)
    for cfg in configs:
        result[cfg.config_key] = cfg.config_value
    return result

def get_config_value(key):
    """获取单个配置值"""
    cfg = SiteConfig.query.filter_by(config_key=key).first()
    if cfg:
        return cfg.config_value
    return DEFAULT_SITE_CONFIG.get(key, '')

def set_config_value(key, value):
    """设置单个配置值"""
    cfg = SiteConfig.query.filter_by(config_key=key).first()
    if cfg:
        cfg.config_value = str(value)
    else:
        cfg = SiteConfig(config_key=key, config_value=str(value))
        db.session.add(cfg)
    db.session.commit()

def init_default_config():
    """初始化默认站点配置"""
    for key, value in DEFAULT_SITE_CONFIG.items():
        if not SiteConfig.query.filter_by(config_key=key).first():
            cfg = SiteConfig(config_key=key, config_value=value)
            db.session.add(cfg)
    db.session.commit()

def create_app(config_overrides=None):
    app = Flask(__name__)
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev')
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:////app/data/photos.db')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
    app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024  # 5MB 限制
    if config_overrides:
        app.config.update(config_overrides)

    db.init_app(app)

    from sqlalchemy import event
    from sqlalchemy.engine import Engine

    @event.listens_for(Engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        try:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON;")
            cursor.close()
        except Exception:
            pass
    
    login_manager = LoginManager()
    login_manager.login_view = 'login'
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        if user_id == '1':
            return User(id='1')
        return None

    # 确保上传目录和导出目录存在
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    os.makedirs(EXPORT_FOLDER, exist_ok=True)

    with app.app_context():
        db.create_all()
        migrate_schema()
        # 初始化默认站点配置
        init_default_config()
        # 动态设置上传大小限制
        max_size_mb = int(get_config_value('max_upload_size_mb'))
        app.config['MAX_CONTENT_LENGTH'] = max_size_mb * 1024 * 1024
        # 如果没有任何相册，创建一个默认相册
        if Album.query.count() == 0:
            default_album = Album(title="我的首个相册", description="欢迎使用在线相册系统")
            db.session.add(default_album)
            db.session.commit()

    # 上下文处理器：注入站点配置到所有模板
    @app.context_processor
    def inject_site_config():
        config = get_site_config()
        config['max_upload_size_mb_int'] = int(config.get('max_upload_size_mb', 5))
        config['show_site_stats_bool'] = config.get('show_site_stats', 'true') == 'true'
        unread_notification_count = 0
        if current_user.is_authenticated:
            unread_notification_count = NotificationService.get_unread_count()
        return {
            'site_config': config,
            'unread_notification_count': unread_notification_count,
        }

    # 413 请求过大错误处理
    @app.errorhandler(413)
    def request_entity_too_large(error):
        max_size = get_config_value('max_upload_size_mb')
        flash(f'上传文件过大，单文件最大允许 {max_size} MB', 'error')
        return redirect(request.referrer or url_for('index'))

    # --- 路由 ---

    @app.route('/')
    def index():
        """相册列表页"""
        sort_by = get_config_value('album_sort_by')
        query = Album.query
        if sort_by == 'photo_count':
            from sqlalchemy import func
            albums = query.outerjoin(Photo).group_by(Album.id).order_by(func.count(Photo.id).desc()).all()
        elif sort_by == 'name':
            albums = query.order_by(Album.title.asc()).all()
        else:
            albums = query.order_by(Album.created_at.desc()).all()
        tags = Tag.query.order_by(Tag.name).all()

        total_albums = Album.query.count()
        total_photos = Photo.query.count()
        total_tags = Tag.query.count()
        total_comments = Comment.query.count()
        site_stats = {
            'total_albums': total_albums,
            'total_photos': total_photos,
            'total_tags': total_tags,
            'total_comments': total_comments
        }

        return render_template('index.html', albums=albums, tags=tags, site_stats=site_stats)

    @app.route('/album/<int:album_id>')
    def album_detail(album_id):
        """相册详情页"""
        album = Album.query.get_or_404(album_id)
        all_tags = Tag.query.order_by(Tag.name).all()
        return render_template('album.html', album=album, all_tags=all_tags)

    @app.route('/admin/login', methods=['GET', 'POST'])
    def login():
        """管理员登录"""
        if request.method == 'POST':
            username = request.form.get('username')
            password = request.form.get('password')
            if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
                user = User(id='1')
                login_user(user)
                log_operation('auth_login', '管理员登录成功')
                flash('登录成功', 'success')
                return redirect(url_for('index'))
            else:
                flash('用户名或密码错误', 'error')
        return render_template('login.html')

    @app.route('/admin/logout')
    @login_required
    def logout():
        """管理员登出"""
        log_operation('auth_logout', '管理员登出')
        logout_user()
        flash('已退出登录', 'info')
        return redirect(url_for('index'))

    @app.route('/album/create', methods=['GET', 'POST'])
    @login_required
    def create_album():
        """创建相册"""
        if request.method == 'POST':
            title = request.form.get('title')
            description = request.form.get('description')
            if not title:
                flash('相册名称不能为空', 'error')
            else:
                new_album = Album(title=title, description=description)
                db.session.add(new_album)
                db.session.flush()
                after_snap = model_snapshot(new_album)
                log_operation('album_create', f'创建相册「{title}」',
                              resource_type='album', resource_id=new_album.id,
                              after_data=after_snap)
                db.session.commit()
                flash('相册创建成功', 'success')
                return redirect(url_for('index'))
        return render_template('create_album.html')

    @app.route('/album/delete/<int:album_id>')
    @login_required
    def delete_album(album_id):
        """删除相册及关联图片"""
        album = Album.query.get_or_404(album_id)
        before_snap = model_snapshot(album)
        photo_count = len(album.photos)
        album_title = album.title
        parent_log = log_operation('album_delete',
                                   f'删除相册「{album.title}」（含 {photo_count} 张照片）',
                                   resource_type='album', resource_id=album.id,
                                   before_data=before_snap, commit=False)
        if photo_count > 1:
            batch_parent, _ = AggregationService.create_batch_parent(
                type=Notification.TYPE_DELETE_BATCH,
                title=f'批量删除 {photo_count} 张照片',
                content=f'随相册「{album_title}」一起删除',
                data={'album_id': album.id, 'album_title': album_title, 'total': photo_count},
            )
        for idx, photo in enumerate(album.photos):
            photo_before = model_snapshot(photo)
            log_operation('photo_delete',
                          f'删除照片「{photo.original_filename}」（随相册删除）',
                          resource_type='photo', resource_id=photo.id,
                          before_data=photo_before, parent_id=parent_log.id, commit=False)
            if photo_count > 1:
                AggregationService.add_child(
                    parent_id=batch_parent.id,
                    type=Notification.TYPE_DELETE,
                    title=f'照片已删除',
                    content=f'「{photo.original_filename}」已被删除',
                    status=Notification.STATUS_SUCCESS,
                    data={'photo_id': photo.id, 'original_filename': photo.original_filename},
                    commit=False,
                )
            try:
                os.remove(os.path.join(app.config['UPLOAD_FOLDER'], photo.filename))
            except OSError:
                pass
        db.session.delete(album)
        db.session.commit()
        if photo_count > 1:
            AggregationService.finalize_batch(
                batch_parent.id,
                status=Notification.STATUS_SUCCESS,
                data={'total': photo_count, 'success': photo_count, 'failed': 0,
                      'album_id': album.id, 'album_title': album_title},
            )
            WebhookService.dispatch(batch_parent)
            CleanupService.cleanup_if_needed()
        elif photo_count == 1:
            dispatch_notification(
                type=Notification.TYPE_DELETE,
                title=f'相册已删除',
                content=f'相册「{album_title}」（含 1 张照片）已删除',
                data={'album_id': album.id, 'album_title': album_title, 'photo_count': photo_count},
            )
        else:
            dispatch_notification(
                type=Notification.TYPE_DELETE,
                title=f'相册已删除',
                content=f'空相册「{album_title}」已删除',
                data={'album_id': album.id, 'album_title': album_title},
            )
        flash('相册已删除', 'success')
        return redirect(url_for('index'))

    @app.route('/upload/<int:album_id>', methods=['GET', 'POST'])
    @login_required
    def upload_photo(album_id):
        """上传照片至指定相册"""
        album = Album.query.get_or_404(album_id)
        if request.method == 'POST':
            if 'photo' not in request.files:
                flash('没有文件被上传', 'error')
                return redirect(request.url)
            
            files = request.files.getlist('photo')
            uploaded_count = 0

            max_size_bytes = int(get_config_value('max_upload_size_mb')) * 1024 * 1024

            uploaded_photos = []

            for file in files:
                if file.filename == '':
                    continue

                if file and allowed_file(file.filename):
                    file.seek(0, os.SEEK_END)
                    file_size = file.tell()
                    file.seek(0)
                    if file_size > max_size_bytes:
                        continue

                    original_filename = secure_filename(file.filename)
                    if not original_filename:
                        original_filename = "未命名图片"
                    
                    try:
                        extension = file.filename.rsplit('.', 1)[1].lower()
                    except IndexError:
                        continue

                    unique_filename = f"{uuid.uuid4().hex}.{extension}"
                    
                    saved_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
                    file.save(saved_path)

                    exif_info = extract_exif(saved_path)
                    img_format = get_image_format(original_filename)

                    new_photo = Photo(
                        filename=unique_filename,
                        original_filename=original_filename,
                        album_id=album.id,
                        camera_model=exif_info['camera_model'],
                        taken_at=exif_info['taken_at'],
                        gps_latitude=exif_info['gps_latitude'],
                        gps_longitude=exif_info['gps_longitude'],
                        image_format=img_format
                    )
                    db.session.add(new_photo)
                    db.session.flush()
                    uploaded_photos.append(new_photo)
                    uploaded_count += 1
            
            if uploaded_count > 0:
                db.session.flush()
                if uploaded_count == 1:
                    p = uploaded_photos[0]
                    log_operation('photo_upload',
                                  f'上传照片「{p.original_filename}」至相册「{album.title}」',
                                  resource_type='photo', resource_id=p.id,
                                  after_data=model_snapshot(p))
                    dispatch_notification(
                        type=Notification.TYPE_UPLOAD,
                        title=f'照片上传成功',
                        content=f'「{p.original_filename}」已上传至相册「{album.title}」',
                        data={'photo_id': p.id, 'album_id': album.id, 'album_title': album.title},
                    )
                else:
                    is_anomaly = detect_anomaly('photo_upload', count=uploaded_count)
                    parent_log = log_operation('photo_upload',
                                               f'批量上传 {uploaded_count} 张照片至相册「{album.title}」',
                                               resource_type='album', resource_id=album.id,
                                               is_anomaly=is_anomaly, commit=False)
                    batch_parent, task_id = AggregationService.create_batch_parent(
                        type=Notification.TYPE_UPLOAD_BATCH,
                        title=f'批量上传 {uploaded_count} 张照片',
                        content=f'上传至相册「{album.title}」',
                        data={'album_id': album.id, 'album_title': album.title, 'total': uploaded_count},
                    )
                    for idx, p in enumerate(uploaded_photos):
                        log_operation('photo_upload',
                                      f'上传照片「{p.original_filename}」',
                                      resource_type='photo', resource_id=p.id,
                                      after_data=model_snapshot(p),
                                      parent_id=parent_log.id, commit=False)
                        AggregationService.add_child(
                            parent_id=batch_parent.id,
                            type=Notification.TYPE_UPLOAD,
                            title=f'照片上传成功',
                            content=f'「{p.original_filename}」上传完成',
                            status=Notification.STATUS_SUCCESS,
                            data={'photo_id': p.id, 'original_filename': p.original_filename},
                            commit=False,
                        )
                    AggregationService.finalize_batch(
                        batch_parent.id,
                        status=Notification.STATUS_SUCCESS,
                        data={'total': uploaded_count, 'success': uploaded_count, 'failed': 0,
                              'album_id': album.id, 'album_title': album.title},
                    )
                    WebhookService.dispatch(batch_parent)
                    CleanupService.cleanup_if_needed()
                db.session.commit()

                uploaded_ids = [p.id for p in uploaded_photos]
                loc_thread = threading.Thread(
                    target=process_uploaded_locations_async,
                    args=(app, uploaded_ids),
                    daemon=True
                )
                loc_thread.start()

                flash(f'成功上传 {uploaded_count} 张图片', 'success')
                return redirect(url_for('album_detail', album_id=album.id))
            else:
                flash('未选择有效文件或格式不支持', 'error')

        max_size_mb = int(get_config_value('max_upload_size_mb'))
        return render_template('upload.html', album=album, max_upload_size_mb=max_size_mb)

    @app.route('/photo/delete/<int:photo_id>')
    @login_required
    def delete_photo(photo_id):
        """删除单张照片"""
        photo = Photo.query.get_or_404(photo_id)
        album_id = photo.album_id
        before_snap = model_snapshot(photo)
        original_filename = photo.original_filename
        log_operation('photo_delete',
                      f'删除照片「{photo.original_filename}」',
                      resource_type='photo', resource_id=photo.id,
                      before_data=before_snap)
        try:
            os.remove(os.path.join(app.config['UPLOAD_FOLDER'], photo.filename))
        except OSError:
            pass
        db.session.delete(photo)
        db.session.commit()
        dispatch_notification(
            type=Notification.TYPE_DELETE,
            title=f'照片已删除',
            content=f'「{original_filename}」已被删除',
            data={'photo_id': photo_id, 'original_filename': original_filename},
        )
        flash('图片已删除', 'success')
        return redirect(url_for('album_detail', album_id=album_id))

    # --- 标签管理路由 ---

    @app.route('/tags')
    def browse_tags():
        """浏览所有标签（首页入口）"""
        tags = Tag.query.order_by(Tag.name).all()
        tag_photo_counts = {}
        for tag in tags:
            tag_photo_counts[tag.id] = tag.photos.count()
        return render_template('tag_browse.html', tags=tags, tag_photo_counts=tag_photo_counts)

    @app.route('/tag/<int:tag_id>')
    def view_tag(tag_id):
        """查看指定标签下的所有照片"""
        tag = Tag.query.get_or_404(tag_id)
        photos = tag.photos.all()
        photo_data = []
        for photo in photos:
            photo_data.append({
                'photo': photo,
                'album': Album.query.get(photo.album_id)
            })
        all_tags = Tag.query.order_by(Tag.name).all()
        return render_template('tag_browse.html', tags=all_tags, current_tag=tag, photo_data=photo_data, tag_photo_counts={t.id: t.photos.count() for t in all_tags})

    @app.route('/admin/tags', methods=['GET', 'POST'])
    @login_required
    def manage_tags():
        """标签管理页面 - 创建、查看标签"""
        if request.method == 'POST':
            name = request.form.get('name', '').strip()
            if not name:
                flash('标签名称不能为空', 'error')
            elif Tag.query.filter_by(name=name).first():
                flash('标签名称已存在，请使用其他名称', 'error')
            else:
                new_tag = Tag(name=name)
                db.session.add(new_tag)
                db.session.flush()
                log_operation('tag_create', f'创建标签「{name}」',
                              resource_type='tag', resource_id=new_tag.id,
                              after_data=model_snapshot(new_tag))
                db.session.commit()
                flash(f'标签「{name}」创建成功', 'success')
            return redirect(url_for('manage_tags'))
        tags = Tag.query.order_by(Tag.created_at.desc()).all()
        tag_photo_counts = {}
        for tag in tags:
            tag_photo_counts[tag.id] = tag.photos.count()
        return render_template('tags.html', tags=tags, tag_photo_counts=tag_photo_counts)

    @app.route('/admin/tag/rename/<int:tag_id>', methods=['POST'])
    @login_required
    def rename_tag(tag_id):
        """重命名标签"""
        tag = Tag.query.get_or_404(tag_id)
        new_name = request.form.get('name', '').strip()
        if not new_name:
            flash('标签名称不能为空', 'error')
        elif Tag.query.filter(Tag.name == new_name, Tag.id != tag_id).first():
            flash('标签名称已存在，请使用其他名称', 'error')
        else:
            old_name = tag.name
            before_snap = model_snapshot(tag)
            tag.name = new_name
            after_snap = model_snapshot(tag)
            log_operation('tag_rename',
                          f'标签从「{old_name}」重命名为「{new_name}」',
                          resource_type='tag', resource_id=tag.id,
                          before_data=before_snap, after_data=after_snap)
            db.session.commit()
            flash(f'标签已从「{old_name}」重命名为「{new_name}」', 'success')
        return redirect(url_for('manage_tags'))

    @app.route('/admin/tag/delete/<int:tag_id>')
    @login_required
    def delete_tag(tag_id):
        """删除标签（仅解除关联，不删除照片）"""
        tag = Tag.query.get_or_404(tag_id)
        tag_name = tag.name
        before_snap = model_snapshot(tag)
        log_operation('tag_delete',
                      f'删除标签「{tag_name}」',
                      resource_type='tag', resource_id=tag.id,
                      before_data=before_snap)
        db.session.delete(tag)
        db.session.commit()
        flash(f'标签「{tag_name}」已删除（关联照片未受影响）', 'success')
        return redirect(url_for('manage_tags'))

    @app.route('/photo/<int:photo_id>/tags', methods=['POST'])
    @login_required
    def set_photo_tags(photo_id):
        """为照片设置标签"""
        photo = Photo.query.get_or_404(photo_id)
        old_tag_ids = sorted([t.id for t in photo.tags.all()])
        old_tag_names = [t.name for t in photo.tags.all()]
        tag_ids = request.form.getlist('tag_ids')
        tag_ids = [int(tid) for tid in tag_ids if tid.isdigit()]
        selected_tags = Tag.query.filter(Tag.id.in_(tag_ids)).all() if tag_ids else []
        new_tag_names = [t.name for t in selected_tags]
        before_data = {'photo_id': photo.id, 'tag_ids': old_tag_ids, 'tag_names': old_tag_names}
        after_data = {'photo_id': photo.id, 'tag_ids': sorted(tag_ids), 'tag_names': new_tag_names}
        photo.tags = selected_tags
        log_operation('photo_tag_update',
                      f'更新照片「{photo.original_filename}」标签：{", ".join(old_tag_names) or "无"} → {", ".join(new_tag_names) or "无"}',
                      resource_type='photo', resource_id=photo.id,
                      before_data=before_data, after_data=after_data)
        db.session.commit()
        flash('标签已更新', 'success')
        return redirect(url_for('album_detail', album_id=photo.album_id))

    # --- 评论 API 路由 ---

    def comment_to_dict(comment):
        return {
            'id': comment.id,
            'photo_id': comment.photo_id,
            'nickname': comment.nickname,
            'content': comment.content,
            'created_at': comment.created_at.strftime('%Y-%m-%d %H:%M:%S')
        }

    @app.route('/api/photo/<int:photo_id>/comments', methods=['GET'])
    def get_photo_comments(photo_id):
        photo = Photo.query.get_or_404(photo_id)
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 5, type=int)
        offset = (page - 1) * per_page

        query = Comment.query.filter_by(photo_id=photo_id).order_by(Comment.created_at.desc())
        total = query.count()
        comments = query.offset(offset).limit(per_page).all()

        return jsonify({
            'success': True,
            'comments': [comment_to_dict(c) for c in comments],
            'total': total,
            'page': page,
            'per_page': per_page,
            'has_more': (offset + len(comments)) < total
        })

    @app.route('/api/photo/<int:photo_id>/comments', methods=['POST'])
    def add_photo_comment(photo_id):
        photo = Photo.query.get_or_404(photo_id)
        data = request.get_json() if request.is_json else request.form

        nickname = (data.get('nickname') or '').strip() or '匿名访客'
        content = (data.get('content') or '').strip()

        if not content:
            return jsonify({'success': False, 'message': '评论内容不能为空'}), 400

        if len(content) > 500:
            return jsonify({'success': False, 'message': '评论内容不能超过500字'}), 400

        if len(nickname) > 50:
            return jsonify({'success': False, 'message': '昵称不能超过50字'}), 400

        new_comment = Comment(
            photo_id=photo_id,
            nickname=nickname,
            content=content
        )
        db.session.add(new_comment)
        db.session.commit()

        return jsonify({
            'success': True,
            'comment': comment_to_dict(new_comment)
        })

    @app.route('/api/comment/<int:comment_id>', methods=['DELETE'])
    @login_required
    def delete_comment(comment_id):
        comment = Comment.query.get_or_404(comment_id)
        before_snap = model_snapshot(comment)
        log_operation('comment_delete',
                      f'删除评论（{comment.nickname}）：{comment.content[:50]}',
                      resource_type='comment', resource_id=comment.id,
                      before_data=before_snap)
        db.session.delete(comment)
        db.session.commit()
        return jsonify({'success': True, 'message': '评论已删除'})

    # --- 站点设置路由 ---

    @app.route('/admin/settings', methods=['GET'])
    @login_required
    def site_settings():
        """站点设置页面"""
        config = get_site_config()
        return render_template('settings.html', config=config)

    @app.route('/admin/settings', methods=['POST'])
    @login_required
    def save_site_settings():
        """保存站点设置"""
        site_name = request.form.get('site_name', '').strip()
        welcome_message = request.form.get('welcome_message', '').strip()
        copyright_text = request.form.get('copyright_text', '').strip()
        contact_email = request.form.get('contact_email', '').strip()
        max_upload_size_mb = request.form.get('max_upload_size_mb', '5')
        album_sort_by = request.form.get('album_sort_by', 'created_at')
        show_site_stats = request.form.get('show_site_stats', 'false')

        if not site_name:
            flash('站点名称不能为空', 'error')
            return redirect(url_for('site_settings'))

        try:
            size_mb = int(max_upload_size_mb)
            if size_mb < 1 or size_mb > 10:
                flash('上传大小限制必须在 1-10 MB 之间', 'error')
                return redirect(url_for('site_settings'))
        except (ValueError, TypeError):
            flash('上传大小限制格式无效', 'error')
            return redirect(url_for('site_settings'))

        before_config = get_site_config()
        set_config_value('site_name', site_name)
        set_config_value('welcome_message', welcome_message)
        set_config_value('copyright_text', copyright_text)
        set_config_value('contact_email', contact_email)
        set_config_value('max_upload_size_mb', str(size_mb))
        set_config_value('album_sort_by', album_sort_by)
        set_config_value('show_site_stats', show_site_stats)
        after_config = get_site_config()

        changed_fields = []
        for k in before_config:
            if str(before_config.get(k)) != str(after_config.get(k)):
                changed_fields.append(k)

        if changed_fields:
            log_operation('settings_update',
                          f'更新站点设置：{", ".join(changed_fields)}',
                          before_data={k: before_config.get(k) for k in changed_fields},
                          after_data={k: after_config.get(k) for k in changed_fields})

        app.config['MAX_CONTENT_LENGTH'] = size_mb * 1024 * 1024

        flash('站点设置已保存', 'success')
        return redirect(url_for('site_settings'))

    # --- 操作日志路由 ---

    def build_log_query():
        operation_types = request.args.getlist('operation_type')
        keyword = request.args.get('keyword', '').strip()
        date_from = request.args.get('date_from', '').strip()
        date_to = request.args.get('date_to', '').strip()

        query = OperationLog.query.filter(OperationLog.parent_id.is_(None))

        if operation_types:
            query = query.filter(OperationLog.operation_type.in_(operation_types))

        if keyword:
            like = f'%{keyword}%'
            query = query.filter(or_(
                OperationLog.summary.like(like),
                OperationLog.resource_type.like(like),
                OperationLog.resource_id.like(like),
            ))

        if date_from:
            try:
                dt_from = datetime.strptime(date_from, '%Y-%m-%d')
                query = query.filter(OperationLog.created_at >= dt_from)
            except ValueError:
                pass

        if date_to:
            try:
                dt_to = datetime.strptime(date_to, '%Y-%m-%d') + timedelta(days=1)
                query = query.filter(OperationLog.created_at < dt_to)
            except ValueError:
                pass

        return query

    @app.route('/admin/logs')
    @login_required
    def operation_logs():
        """操作日志页面"""
        page = request.args.get('page', 1, type=int)
        per_page = 20
        query = build_log_query().order_by(OperationLog.created_at.desc())
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)
        total = pagination.total
        logs = pagination.items

        operation_types_list = sorted(OperationLog.OPERATION_TYPES.items(), key=lambda x: x[1])
        selected_types = request.args.getlist('operation_type')

        return render_template('operation_logs.html',
                               logs=logs,
                               pagination=pagination,
                               total=total,
                               operation_types=operation_types_list,
                               selected_types=selected_types,
                               keyword=request.args.get('keyword', ''),
                               date_from=request.args.get('date_from', ''),
                               date_to=request.args.get('date_to', ''))

    @app.route('/admin/logs/export')
    @login_required
    def export_logs_csv():
        """导出操作日志为 CSV"""
        query = build_log_query().order_by(OperationLog.created_at.desc())
        logs = query.all()

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['操作时间', '操作类型', '摘要', '资源类型', '资源ID', 'IP地址', '是否异常', '变更快照'])

        def flatten_log(log, depth=0):
            rows = []
            prefix = '  ' * depth
            rows.append([
                log.created_at.strftime('%Y-%m-%d %H:%M:%S') if log.created_at else '',
                log.operation_type_label,
                prefix + log.summary,
                log.resource_type or '',
                log.resource_id or '',
                log.ip_address or '',
                '是' if log.is_anomaly else '否',
                '',
            ])
            if log.before_data or log.after_data:
                diffs = diff_snapshots(log.before_data or {}, log.after_data or {})
                for d in diffs:
                    rows.append(['', '', '', '', '', '', '',
                                 f"{d['field']}: {d['before']} → {d['after']}"])
            for child in log.children.all():
                rows.extend(flatten_log(child, depth + 1))
            return rows

        for log in logs:
            for row in flatten_log(log):
                writer.writerow(row)

        output.seek(0)
        response = make_response(output.getvalue())
        response.headers['Content-Type'] = 'text/csv; charset=utf-8-sig'
        filename = f"operation_logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        response.headers['Content-Disposition'] = f'attachment; filename={filename}'
        return response

    @app.route('/api/admin/logs/<int:log_id>')
    @login_required
    def api_log_detail(log_id):
        """获取单条日志详情（含快照 diff 与子日志）"""
        log = OperationLog.query.get_or_404(log_id)
        data = log.to_dict(include_children=True)
        data['before_data'] = log.before_data
        data['after_data'] = log.after_data
        data['diffs'] = diff_snapshots(log.before_data or {}, log.after_data or {})
        return jsonify({'success': True, 'log': data})

    # --- 全站搜索路由 ---

    @app.route('/api/search/autocomplete')
    def api_search_autocomplete():
        """相册标题前缀自动补全 API"""
        query = request.args.get('q', '').strip()
        if not query:
            return jsonify({'success': True, 'suggestions': []})
        q_lower = query.lower()
        albums = Album.query.all()
        suggestions = []
        for album in albums:
            title = album.title or ''
            if title.lower().startswith(q_lower) or q_lower in title.lower():
                suggestions.append({
                    'id': album.id,
                    'title': title,
                    'url': url_for('album_detail', album_id=album.id)
                })
            if len(suggestions) >= 8:
                break
        return jsonify({'success': True, 'suggestions': suggestions})

    @app.route('/search')
    def search():
        """全站搜索结果页"""
        query = request.args.get('q', '').strip()
        filter_album_id = request.args.get('album_id', type=int)
        date_from = request.args.get('date_from', '').strip()
        date_to = request.args.get('date_to', '').strip()
        filter_format = request.args.get('format', '').strip()
        filter_gps = request.args.get('has_gps', '').strip()

        matched_albums = []
        matched_photos = []

        all_albums = Album.query.order_by(Album.title.asc()).all()
        all_formats = sorted(set(
            f for f in db.session.query(Photo.image_format).distinct().all()
            if f and f[0]
        ), key=lambda x: x[0].lower())
        all_formats = [f[0] for f in all_formats]

        if query:
            albums_raw = Album.query.all()
            for album in albums_raw:
                text_parts = [album.title or '', album.description or '']
                if any(fuzzy_match(query, t) for t in text_parts):
                    matched_albums.append(album)

            photos_raw = Photo.query.all()
            for photo in photos_raw:
                tag_names = ' '.join([t.name for t in photo.tags.all()])
                taken_at_str = photo.taken_at.strftime('%Y-%m-%d %H:%M:%S') if photo.taken_at else ''
                text_parts = [
                    photo.original_filename or '',
                    photo.description or '',
                    photo.camera_model or '',
                    taken_at_str,
                    tag_names,
                ]
                if any(fuzzy_match(query, t) for t in text_parts):
                    matched_photos.append(photo)

            if filter_album_id:
                matched_photos = [p for p in matched_photos if p.album_id == filter_album_id]

            if date_from:
                try:
                    dt_from = datetime.strptime(date_from, '%Y-%m-%d')
                    matched_photos = [
                        p for p in matched_photos
                        if (p.taken_at or p.uploaded_at) >= dt_from
                    ]
                except ValueError:
                    pass

            if date_to:
                try:
                    dt_to = datetime.strptime(date_to, '%Y-%m-%d') + timedelta(days=1)
                    matched_photos = [
                        p for p in matched_photos
                        if (p.taken_at or p.uploaded_at) < dt_to
                    ]
                except ValueError:
                    pass

            if filter_format:
                matched_photos = [p for p in matched_photos if p.image_format == filter_format]

            if filter_gps == 'yes':
                matched_photos = [p for p in matched_photos if p.gps_latitude is not None and p.gps_longitude is not None]
            elif filter_gps == 'no':
                matched_photos = [p for p in matched_photos if p.gps_latitude is None or p.gps_longitude is None]

        matched_albums_data = []
        for album in matched_albums:
            matched_albums_data.append({
                'id': album.id,
                'title': highlight_keywords(album.title or '', query),
                'title_raw': album.title or '',
                'description': highlight_keywords(album.description or '', query),
                'description_raw': album.description or '',
                'photo_count': len(album.photos),
                'cover_photo': album.photos[-1] if album.photos else None,
                'url': url_for('album_detail', album_id=album.id),
                'created_at': album.created_at,
            })

        matched_photos_data = []
        for photo in matched_photos:
            tag_names_html = ', '.join([
                highlight_keywords(t.name, query) for t in photo.tags.all()
            ])
            taken_at = photo.taken_at or photo.uploaded_at
            taken_at_str = taken_at.strftime('%Y-%m-%d %H:%M:%S') if taken_at else ''
            matched_photos_data.append({
                'id': photo.id,
                'original_filename': highlight_keywords(photo.original_filename or '', query),
                'original_filename_raw': photo.original_filename or '',
                'description': highlight_keywords(photo.description or '', query),
                'description_raw': photo.description or '',
                'camera_model': highlight_keywords(photo.camera_model or '', query),
                'camera_model_raw': photo.camera_model or '',
                'taken_at': highlight_keywords(taken_at_str, query),
                'taken_at_raw': taken_at_str,
                'has_gps': photo.gps_latitude is not None and photo.gps_longitude is not None,
                'image_format': photo.image_format or '',
                'tag_names_html': tag_names_html,
                'album': Album.query.get(photo.album_id),
                'album_id': photo.album_id,
                'filename': photo.filename,
                'url': url_for('album_detail', album_id=photo.album_id),
            })

        active_filters = {}
        if filter_album_id:
            active_filters['album_id'] = filter_album_id
        if date_from:
            active_filters['date_from'] = date_from
        if date_to:
            active_filters['date_to'] = date_to
        if filter_format:
            active_filters['format'] = filter_format
        if filter_gps:
            active_filters['has_gps'] = filter_gps

        return render_template(
            'search.html',
            query=query,
            matched_albums=matched_albums_data,
            matched_photos=matched_photos_data,
            all_albums=all_albums,
            all_formats=all_formats,
            filter_album_id=filter_album_id,
            date_from=date_from,
            date_to=date_to,
            filter_format=filter_format,
            filter_gps=filter_gps,
            active_filters=active_filters,
            total_count=len(matched_albums_data) + len(matched_photos_data),
        )

    # --- 数据统计仪表盘 ---

    def estimate_disk_usage_bytes():
        """估算磁盘占用：基于上传目录实际文件大小"""
        total_bytes = 0
        try:
            for filename in os.listdir(UPLOAD_FOLDER):
                filepath = os.path.join(UPLOAD_FOLDER, filename)
                if os.path.isfile(filepath):
                    total_bytes += os.path.getsize(filepath)
        except OSError:
            pass
        return total_bytes

    def format_bytes(num_bytes):
        """将字节数格式化为易读字符串"""
        if num_bytes < 1024:
            return f"{num_bytes} B"
        elif num_bytes < 1024 * 1024:
            return f"{num_bytes / 1024:.1f} KB"
        elif num_bytes < 1024 * 1024 * 1024:
            return f"{num_bytes / (1024 * 1024):.1f} MB"
        else:
            return f"{num_bytes / (1024 * 1024 * 1024):.2f} GB"

    def get_daily_uploads(days=7, end_date=None):
        """获取指定天数范围内每天的上传数量"""
        if end_date is None:
            end_date = datetime.utcnow().date()
        start_date = end_date - timedelta(days=days - 1)
        start_dt = datetime.combine(start_date, datetime.min.time())

        results = db.session.query(
            func.date(Photo.uploaded_at),
            func.count(Photo.id)
        ).filter(
            Photo.uploaded_at >= start_dt
        ).group_by(
            func.date(Photo.uploaded_at)
        ).all()

        date_counts = {str(d): 0 for d in [start_date + timedelta(days=i) for i in range(days)]}
        for date_val, count in results:
            date_counts[str(date_val)] = count

        dates = sorted(date_counts.keys())
        return {
            'labels': dates,
            'counts': [date_counts[d] for d in dates]
        }

    def get_album_photo_counts(limit=15):
        """获取各相册照片数量（Top limit + 其他）"""
        results = db.session.query(
            Album.id,
            Album.title,
            func.count(Photo.id).label('photo_count')
        ).outerjoin(
            Photo, Photo.album_id == Album.id
        ).group_by(
            Album.id, Album.title
        ).order_by(
            func.count(Photo.id).desc()
        ).all()

        top_albums = []
        others_count = 0
        for idx, (album_id, title, count) in enumerate(results):
            if idx < limit:
                top_albums.append({
                    'id': album_id,
                    'title': title,
                    'count': count
                })
            else:
                others_count += count

        if others_count > 0 or len(results) > limit:
            top_albums.append({
                'id': None,
                'title': '其他',
                'count': others_count
            })

        return top_albums

    def get_format_distribution():
        """获取图片格式分布"""
        results = db.session.query(
            Photo.image_format,
            func.count(Photo.id)
        ).group_by(
            Photo.image_format
        ).all()

        format_data = []
        for fmt, count in results:
            format_data.append({
                'format': (fmt or 'unknown').upper(),
                'count': count
            })
        return sorted(format_data, key=lambda x: x['count'], reverse=True)

    def get_heatmap_data():
        """获取过去 52 周（约一年）的上传热力图数据"""
        end_date = datetime.utcnow().date()
        # 对齐到周日
        weekday = end_date.weekday()  # 周一=0, 周日=6
        days_to_sunday = (6 - weekday) % 7
        end_date = end_date + timedelta(days=days_to_sunday)

        start_date = end_date - timedelta(weeks=52) + timedelta(days=1)
        start_dt = datetime.combine(start_date, datetime.min.time())

        results = db.session.query(
            func.date(Photo.uploaded_at),
            func.count(Photo.id)
        ).filter(
            Photo.uploaded_at >= start_dt
        ).group_by(
            func.date(Photo.uploaded_at)
        ).all()

        date_counts = {}
        for date_val, count in results:
            date_counts[str(date_val)] = count

        weeks = []
        current_date = start_date
        while current_date <= end_date:
            week_days = []
            for i in range(7):
                d = current_date + timedelta(days=i)
                if d >= start_date and d <= end_date:
                    week_days.append({
                        'date': str(d),
                        'count': date_counts.get(str(d), 0)
                    })
                else:
                    week_days.append(None)
            weeks.append(week_days)
            current_date += timedelta(days=7)

        return weeks

    def get_most_active_albums(days=30, limit=5):
        """获取上传最活跃的相册（指定时间范围内）"""
        start_dt = datetime.utcnow() - timedelta(days=days)
        results = db.session.query(
            Album.id,
            Album.title,
            func.count(Photo.id).label('upload_count')
        ).join(
            Photo, Photo.album_id == Album.id
        ).filter(
            Photo.uploaded_at >= start_dt
        ).group_by(
            Album.id, Album.title
        ).order_by(
            func.count(Photo.id).desc()
        ).limit(limit).all()

        return [{
            'id': aid,
            'title': title,
            'count': cnt
        } for aid, title, cnt in results]

    def get_storage_growth_trend(days=30):
        """获取存储增长趋势（近30天，按日累计）和线性回归斜率"""
        end_date = datetime.utcnow().date()
        start_date = end_date - timedelta(days=days - 1)
        start_dt = datetime.combine(start_date, datetime.min.time())

        # 获取每天上传量
        daily_results = db.session.query(
            func.date(Photo.uploaded_at),
            func.count(Photo.id)
        ).filter(
            Photo.uploaded_at >= start_dt
        ).group_by(
            func.date(Photo.uploaded_at)
        ).all()

        date_counts = {}
        for date_val, count in daily_results:
            date_counts[str(date_val)] = count

        labels = []
        cumulative = []
        total = 0
        # 已有的历史上传量（早于 start_date 的）
        existing_count = Photo.query.filter(Photo.uploaded_at < start_dt).count()
        total = existing_count

        for i in range(days):
            d = start_date + timedelta(days=i)
            date_str = str(d)
            count = date_counts.get(date_str, 0)
            total += count
            labels.append(date_str)
            cumulative.append(total)

        # 线性回归计算斜率
        n = len(labels)
        if n > 1:
            x_mean = (n - 1) / 2
            y_mean = sum(cumulative) / n
            numerator = sum((i - x_mean) * (cumulative[i] - y_mean) for i in range(n))
            denominator = sum((i - x_mean) ** 2 for i in range(n))
            slope = numerator / denominator if denominator != 0 else 0
        else:
            slope = 0

        return {
            'labels': labels,
            'cumulative': cumulative,
            'slope': slope,
            'projected_30d': cumulative[-1] + slope * 30 if cumulative else 0
        }

    def collect_dashboard_stats(days=7):
        """收集仪表盘所有统计数据"""
        disk_bytes = estimate_disk_usage_bytes()
        today = datetime.utcnow().date()
        today_start = datetime.combine(today, datetime.min.time())
        today_uploads = Photo.query.filter(Photo.uploaded_at >= today_start).count()

        # 当前周期和上一周期（用于同比）
        current_data = get_daily_uploads(days=days)
        prev_end = today - timedelta(days=days)
        prev_data = get_daily_uploads(days=days, end_date=prev_end)

        return {
            'summary': {
                'total_albums': Album.query.count(),
                'total_photos': Photo.query.count(),
                'today_uploads': today_uploads,
                'disk_usage': format_bytes(disk_bytes),
                'disk_usage_bytes': disk_bytes
            },
            'daily_uploads': {
                'current': current_data,
                'previous': prev_data
            },
            'album_counts': get_album_photo_counts(15),
            'format_distribution': get_format_distribution(),
            'heatmap': get_heatmap_data(),
            'active_albums': get_most_active_albums(30, 5),
            'storage_trend': get_storage_growth_trend(30)
        }

    @app.route('/admin/dashboard')
    @login_required
    def admin_dashboard():
        """管理员数据统计仪表盘页面"""
        days = request.args.get('days', 7, type=int)
        if days not in (7, 30):
            days = 7
        stats = collect_dashboard_stats(days=days)
        return render_template('dashboard.html', stats=stats, initial_days=days)

    @app.route('/api/admin/dashboard')
    @login_required
    def api_admin_dashboard():
        """仪表盘数据 API（用于动态刷新）"""
        days = request.args.get('days', 7, type=int)
        if days not in (7, 30):
            days = 7
        stats = collect_dashboard_stats(days=days)
        return jsonify({'success': True, 'stats': stats})

    @app.route('/admin/dashboard/print')
    @login_required
    def admin_dashboard_print():
        """仪表盘打印/导出视图（供前端 PDF 导出使用）"""
        days = request.args.get('days', 7, type=int)
        if days not in (7, 30):
            days = 7
        stats = collect_dashboard_stats(days=days)
        config = get_site_config()
        return render_template('dashboard_print.html', stats=stats, days=days, site_config=config, now=datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'))

    # --- 相册 ZIP 导出相关 ---

    def _resize_for_web(img_path, max_long_side=1920):
        """将图片等比缩放到长边不超过 max_long_side，返回 BytesIO"""
        try:
            with Image.open(img_path) as img:
                width, height = img.size
                long_side = max(width, height)
                if long_side <= max_long_side:
                    with open(img_path, 'rb') as f:
                        return io.BytesIO(f.read())
                scale = max_long_side / long_side
                new_width = int(width * scale)
                new_height = int(height * scale)
                resized = img.resize((new_width, new_height), Image.LANCZOS)
                output = io.BytesIO()
                fmt = img.format or 'JPEG'
                if fmt.upper() == 'JPG':
                    fmt = 'JPEG'
                save_kwargs = {}
                if fmt.upper() == 'JPEG':
                    save_kwargs['quality'] = 85
                    save_kwargs['optimize'] = True
                resized.save(output, format=fmt, **save_kwargs)
                output.seek(0)
                return output
        except Exception:
            with open(img_path, 'rb') as f:
                return io.BytesIO(f.read())

    def _get_unique_name(used_names, original_name):
        """生成不重复的文件名，重名追加序号"""
        if original_name not in used_names:
            used_names.add(original_name)
            return original_name
        base, ext = os.path.splitext(original_name)
        counter = 1
        while True:
            candidate = f"{base}_{counter}{ext}"
            if candidate not in used_names:
                used_names.add(candidate)
                return candidate
            counter += 1

    def process_export_job(app_instance, job_id):
        """后台线程处理 ZIP 导出任务"""
        with app_instance.app_context():
            job = ExportJob.query.get(job_id)
            if not job:
                return
            try:
                job.status = ExportJob.STATUS_PROCESSING
                db.session.commit()

                album = Album.query.get(job.album_id)
                if not album:
                    raise Exception("相册不存在")

                photos = album.photos
                job.total_photos = len(photos)
                db.session.commit()

                options = job.options or {}
                compress_web = options.get('compress_web', False)
                include_manifest = options.get('include_manifest', False)
                group_by_date = options.get('group_by_date', False)

                used_names = set()
                manifest_entries = []

                today_str = datetime.now().strftime('%Y%m%d')
                safe_title = re.sub(r'[\\/:*?"<>|]', '_', album.title)
                zip_basename = f"{safe_title}_{today_str}.zip"
                zip_fullname = f"{uuid.uuid4().hex}_{zip_basename}"
                zip_path = os.path.join(EXPORT_FOLDER, zip_fullname)

                with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                    for idx, photo in enumerate(photos):
                        img_path = os.path.join(UPLOAD_FOLDER, photo.filename)
                        if not os.path.isfile(img_path):
                            job.processed_photos = idx + 1
                            job.progress = int((idx + 1) / max(1, job.total_photos) * 100)
                            db.session.commit()
                            continue

                        display_name = _get_unique_name(used_names, photo.original_filename or f"photo_{photo.id}")

                        if group_by_date:
                            date_obj = photo.uploaded_at or datetime.utcnow()
                            date_folder = date_obj.strftime('%Y-%m-%d')
                            arcname = f"{date_folder}/{display_name}"
                        else:
                            arcname = display_name

                        if compress_web:
                            img_data = _resize_for_web(img_path)
                            zf.writestr(arcname, img_data.getvalue())
                        else:
                            zf.write(img_path, arcname)

                        if include_manifest:
                            exif_summary = {}
                            if photo.camera_model:
                                exif_summary['camera_model'] = photo.camera_model
                            if photo.taken_at:
                                exif_summary['taken_at'] = photo.taken_at.strftime('%Y-%m-%d %H:%M:%S')
                            if photo.gps_latitude is not None and photo.gps_longitude is not None:
                                exif_summary['gps'] = {
                                    'latitude': photo.gps_latitude,
                                    'longitude': photo.gps_longitude
                                }
                            manifest_entries.append({
                                'filename': display_name,
                                'original_filename': photo.original_filename,
                                'uploaded_at': photo.uploaded_at.strftime('%Y-%m-%d %H:%M:%S') if photo.uploaded_at else None,
                                'exif': exif_summary if exif_summary else None
                            })

                        job.processed_photos = idx + 1
                        job.progress = int((idx + 1) / max(1, job.total_photos) * 100)
                        if idx % 5 == 0 or idx == job.total_photos - 1:
                            db.session.commit()

                    if include_manifest and manifest_entries:
                        manifest_data = {
                            'album_title': album.title,
                            'exported_at': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
                            'total_photos': len(manifest_entries),
                            'files': manifest_entries
                        }
                        zf.writestr('manifest.json', json.dumps(manifest_data, ensure_ascii=False, indent=2))

                file_size = os.path.getsize(zip_path)
                job.zip_filename = zip_fullname
                job.file_size = file_size
                job.status = ExportJob.STATUS_COMPLETED
                job.completed_at = datetime.utcnow()
                job.expires_at = datetime.utcnow() + timedelta(days=EXPORT_EXPIRE_DAYS)
                job.progress = 100
                db.session.commit()

                history = DownloadHistory(
                    album_id=album.id,
                    export_job_id=job.id,
                    album_title=album.title,
                    zip_filename=zip_fullname,
                    file_size=file_size,
                    photo_count=job.total_photos,
                    options=options,
                    ip_address=get_client_ip()
                )
                db.session.add(history)
                db.session.commit()

                log_operation('export_zip',
                              f'导出相册「{album.title}」ZIP（{job.total_photos} 张，{format_bytes_human(file_size)}）',
                              resource_type='album', resource_id=album.id,
                              after_data={'photo_count': job.total_photos, 'file_size': file_size, 'options': options})

                dispatch_notification(
                    type=Notification.TYPE_EXPORT_ZIP,
                    title=f'ZIP 导出完成',
                    content=f'相册「{album.title}」已成功导出，共 {job.total_photos} 张照片',
                    status=Notification.STATUS_SUCCESS,
                    task_id=f'export_{job.id}',
                    data={
                        'job_id': job.id,
                        'album_id': album.id,
                        'album_title': album.title,
                        'photo_count': job.total_photos,
                        'file_size': file_size,
                        'file_size_human': format_bytes_human(file_size),
                        'download_url': f'/export/{job.id}/download',
                    },
                )

            except Exception as e:
                import traceback
                job.status = ExportJob.STATUS_FAILED
                job.error_message = str(e) + "\n" + traceback.format_exc()[-500:]
                db.session.commit()

                album = Album.query.get(job.album_id) if job else None
                dispatch_notification(
                    type=Notification.TYPE_EXPORT_ZIP,
                    title=f'ZIP 导出失败',
                    content=f'相册「{album.title if album else "未知"}」导出失败：{str(e)}',
                    status=Notification.STATUS_FAILED,
                    task_id=f'export_{job.id}' if job else None,
                    data={
                        'job_id': job.id if job else None,
                        'album_id': album.id if album else None,
                        'album_title': album.title if album else None,
                        'error': str(e),
                    },
                )

    @app.route('/album/<int:album_id>/export', methods=['POST'])
    @login_required
    def create_export_job(album_id):
        """创建相册 ZIP 导出任务"""
        album = Album.query.get_or_404(album_id)
        if not album.photos:
            return jsonify({'success': False, 'message': '相册为空，无法导出'}), 400

        data = request.get_json() if request.is_json else request.form
        options = {
            'compress_web': bool(data.get('compress_web', False)),
            'include_manifest': bool(data.get('include_manifest', False)),
            'group_by_date': bool(data.get('group_by_date', False)),
        }

        job = ExportJob(
            album_id=album.id,
            status=ExportJob.STATUS_PENDING,
            progress=0,
            total_photos=len(album.photos),
            processed_photos=0,
            options=options,
        )
        db.session.add(job)
        db.session.commit()

        thread = threading.Thread(target=process_export_job, args=(app, job.id), daemon=True)
        thread.start()

        return jsonify({'success': True, 'job': job.to_dict()})

    @app.route('/export/<int:job_id>/status')
    @login_required
    def export_status(job_id):
        """查询导出任务状态"""
        job = ExportJob.query.get_or_404(job_id)
        return jsonify({'success': True, 'job': job.to_dict()})

    @app.route('/export/<int:job_id>/download')
    @login_required
    def download_export(job_id):
        """下载已完成的导出 ZIP"""
        job = ExportJob.query.get_or_404(job_id)
        if not job.is_ready:
            abort(404)

        zip_path = os.path.join(EXPORT_FOLDER, job.zip_filename)
        if not os.path.isfile(zip_path):
            abort(404)

        album = Album.query.get(job.album_id)
        safe_title = re.sub(r'[\\/:*?"<>|]', '_', album.title if album else 'album')
        today_str = datetime.now().strftime('%Y%m%d')
        download_name = f"{safe_title}_{today_str}.zip"

        return send_file(
            zip_path,
            as_attachment=True,
            download_name=download_name,
            mimetype='application/zip'
        )

    @app.route('/admin/downloads')
    @login_required
    def download_history():
        """下载历史记录页面"""
        page = request.args.get('page', 1, type=int)
        per_page = 20
        query = DownloadHistory.query.order_by(DownloadHistory.created_at.desc())
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)
        records = pagination.items

        record_dicts = []
        for r in records:
            d = r.to_dict()
            record_dicts.append(d)

        return render_template('download_history.html',
                               records=record_dicts,
                               pagination=pagination,
                               total=pagination.total)

    @app.route('/admin/downloads/<int:history_id>/download')
    @login_required
    def redownload_from_history(history_id):
        """从历史记录重新下载 ZIP"""
        record = DownloadHistory.query.get_or_404(history_id)
        if not record.file_exists:
            flash('ZIP 文件已过期或被删除', 'error')
            return redirect(url_for('download_history'))

        zip_path = os.path.join(EXPORT_FOLDER, record.zip_filename)
        safe_title = re.sub(r'[\\/:*?"<>|]', '_', record.album_title or 'album')
        today_str = (record.created_at or datetime.now()).strftime('%Y%m%d')
        download_name = f"{safe_title}_{today_str}.zip"

        return send_file(
            zip_path,
            as_attachment=True,
            download_name=download_name,
            mimetype='application/zip'
        )

    # --- 地理位置相关路由 ---

    @app.route('/map')
    def map_view():
        """地图浏览页面"""
        return render_template('map.html')

    @app.route('/api/map/photos')
    def api_map_photos():
        """获取所有有 GPS 的照片数据（地图渲染用）"""
        photos = Photo.query.filter(
            Photo.gps_latitude.isnot(None),
            Photo.gps_longitude.isnot(None)
        ).all()
        result = []
        for p in photos:
            album = Album.query.get(p.album_id)
            taken_at = p.taken_at or p.uploaded_at
            result.append({
                'id': p.id,
                'latitude': p.gps_latitude,
                'longitude': p.gps_longitude,
                'original_filename': p.original_filename,
                'thumbnail_url': url_for('static', filename='uploads/' + p.filename),
                'address': p.location_display,
                'city': p.location_city,
                'district': p.location_district,
                'album_id': p.album_id,
                'album_title': album.title if album else '',
                'album_url': url_for('album_detail', album_id=p.album_id),
                'taken_at': taken_at.strftime('%Y-%m-%d %H:%M:%S') if taken_at else None,
                'trip_id': p.trip_id,
            })
        return jsonify({'success': True, 'photos': result})

    @app.route('/api/map/trips')
    def api_map_trips():
        """获取所有行程数据（地图侧栏展示用）"""
        trips = Trip.query.order_by(Trip.start_time.desc().nullslast()).all()
        result = [t.to_dict() for t in trips]
        return jsonify({'success': True, 'trips': result})

    @app.route('/photo/<int:photo_id>/location', methods=['POST'])
    @login_required
    def update_photo_location(photo_id):
        """手动补充/修正照片地点"""
        photo = Photo.query.get_or_404(photo_id)
        data = request.get_json() if request.is_json else request.form

        before = {
            'location_country': photo.location_country,
            'location_province': photo.location_province,
            'location_city': photo.location_city,
            'location_district': photo.location_district,
            'location_address': photo.location_address,
            'gps_latitude': photo.gps_latitude,
            'gps_longitude': photo.gps_longitude,
        }

        country = (data.get('country') or '').strip() or None
        province = (data.get('province') or '').strip() or None
        city = (data.get('city') or '').strip()
        district = (data.get('district') or '').strip() or None
        address = (data.get('address') or '').strip() or None
        latitude = data.get('latitude')
        longitude = data.get('longitude')

        if not city and not address:
            return jsonify({'success': False, 'message': '至少需要填写城市或完整地址'}), 400

        photo.location_country = country
        photo.location_province = province
        photo.location_city = city or None
        photo.location_district = district
        photo.location_address = address
        photo.location_manual = True

        try:
            if latitude is not None and longitude is not None:
                photo.gps_latitude = float(latitude)
                photo.gps_longitude = float(longitude)
        except (ValueError, TypeError):
            pass

        after = {
            'location_country': photo.location_country,
            'location_province': photo.location_province,
            'location_city': photo.location_city,
            'location_district': photo.location_district,
            'location_address': photo.location_address,
            'gps_latitude': photo.gps_latitude,
            'gps_longitude': photo.gps_longitude,
        }

        log_operation('photo_location_update',
                      f'更新照片「{photo.original_filename}」地点信息',
                      resource_type='photo', resource_id=photo.id,
                      before_data=before, after_data=after)
        db.session.commit()

        t = threading.Thread(target=lambda: (
            None,
            None,
            infer_trips(photo_ids=[photo.id])
        ), daemon=True)
        t.start()

        return jsonify({
            'success': True,
            'location': {
                'country': photo.location_country,
                'province': photo.location_province,
                'city': photo.location_city,
                'district': photo.location_district,
                'address': photo.location_address,
                'latitude': photo.gps_latitude,
                'longitude': photo.gps_longitude,
                'display': photo.location_display,
            }
        })

    @app.route('/photo/<int:photo_id>/location', methods=['GET'])
    def get_photo_location(photo_id):
        """获取单张照片的地点信息"""
        photo = Photo.query.get_or_404(photo_id)
        return jsonify({
            'success': True,
            'location': {
                'country': photo.location_country,
                'province': photo.location_province,
                'city': photo.location_city,
                'district': photo.location_district,
                'address': photo.location_address,
                'latitude': photo.gps_latitude,
                'longitude': photo.gps_longitude,
                'display': photo.location_display,
                'manual': photo.location_manual,
                'has_gps': photo.has_gps,
            }
        })

    @app.route('/api/admin/infer-trips', methods=['POST'])
    @login_required
    def api_infer_trips():
        """手动触发全局行程推断"""
        try:
            infer_trips()
            return jsonify({'success': True, 'message': '行程推断完成'})
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)}), 500

    # --- 通知中心路由 ---

    @app.route('/notifications')
    @login_required
    def notifications_page():
        """通知列表页"""
        page = request.args.get('page', 1, type=int)
        per_page = 20
        type_filter = request.args.get('type', '').strip() or None
        status_filter = request.args.get('status', '').strip() or None
        unread_only = request.args.get('unread_only', '').strip() == '1'

        pagination = NotificationService.get_list(
            page=page, per_page=per_page,
            type_filter=type_filter, status_filter=status_filter,
            unread_only=unread_only,
        )

        type_options = sorted(Notification.TYPE_LABELS.items(), key=lambda x: x[1])
        status_options = [
            (Notification.STATUS_PENDING, '处理中'),
            (Notification.STATUS_SUCCESS, '成功'),
            (Notification.STATUS_FAILED, '失败'),
            (Notification.STATUS_PARTIAL, '部分成功'),
        ]

        return render_template(
            'notifications.html',
            notifications=pagination.items,
            pagination=pagination,
            total=pagination.total,
            unread_count=NotificationService.get_unread_count(),
            type_options=type_options,
            status_options=status_options,
            current_type=type_filter or '',
            current_status=status_filter or '',
            unread_only=unread_only,
        )

    @app.route('/api/notifications/unread-count')
    @login_required
    def api_notification_unread_count():
        """获取未读通知数量"""
        return jsonify({
            'success': True,
            'count': NotificationService.get_unread_count(),
        })

    @app.route('/api/notifications/<int:notification_id>')
    @login_required
    def api_notification_detail(notification_id):
        """获取单条通知详情（含子项）"""
        notif = NotificationService.get_detail(notification_id)
        if not notif:
            return jsonify({'success': False, 'message': '通知不存在'}), 404
        return jsonify({
            'success': True,
            'notification': notif.to_dict(include_children=True),
        })

    @app.route('/api/notifications/<int:notification_id>/read', methods=['POST'])
    @login_required
    def api_notification_mark_read(notification_id):
        """标记单条通知已读"""
        notif = NotificationService.mark_as_read(notification_id)
        if notif and notif.is_aggregated:
            AggregationService.mark_parent_and_children_read(notification_id)
        return jsonify({
            'success': True,
            'unread_count': NotificationService.get_unread_count(),
        })

    @app.route('/api/notifications/read-all', methods=['POST'])
    @login_required
    def api_notification_mark_all_read():
        """标记全部通知已读"""
        count = NotificationService.mark_all_as_read()
        return jsonify({
            'success': True,
            'marked_count': count,
        })

    @app.route('/api/notifications/<int:notification_id>', methods=['DELETE'])
    @login_required
    def api_notification_delete(notification_id):
        """删除单条通知"""
        ok = NotificationService.delete(notification_id)
        return jsonify({
            'success': ok,
            'unread_count': NotificationService.get_unread_count(),
        })

    # --- Webhook 配置管理 ---

    @app.route('/admin/webhooks')
    @login_required
    def webhooks_page():
        """Webhook 配置管理页"""
        configs = WebhookService.list_configs()
        event_type_options = sorted(WebhookConfig.EVENT_TYPES.items(), key=lambda x: x[1])
        return render_template(
            'webhooks.html',
            configs=configs,
            event_type_options=event_type_options,
        )

    @app.route('/api/admin/webhooks', methods=['POST'])
    @login_required
    def api_webhook_create():
        """创建 Webhook 配置"""
        data = request.get_json() if request.is_json else request.form
        name = (data.get('name') or '').strip()
        url = (data.get('url') or '').strip()
        secret = (data.get('secret') or '').strip() or None
        event_types = data.getlist('event_types') if hasattr(data, 'getlist') else (data.get('event_types') or [])
        is_active = str(data.get('is_active', '1')) in ('1', 'true', 'True', 'on')

        if not name:
            return jsonify({'success': False, 'message': '名称不能为空'}), 400
        if not url:
            return jsonify({'success': False, 'message': 'URL 不能为空'}), 400

        config = WebhookService.create_config(
            name=name, url=url, secret=secret,
            event_types=event_types, is_active=is_active,
        )
        log_operation('webhook_create', f'创建 Webhook 配置「{name}」',
                      resource_type='webhook', resource_id=config.id,
                      after_data=config.to_dict())
        return jsonify({'success': True, 'config': config.to_dict()})

    @app.route('/api/admin/webhooks/<int:config_id>', methods=['POST'])
    @login_required
    def api_webhook_update(config_id):
        """更新 Webhook 配置"""
        data = request.get_json() if request.is_json else request.form
        before = WebhookService.get_config(config_id)
        if not before:
            return jsonify({'success': False, 'message': '配置不存在'}), 404
        before_snap = before.to_dict()

        kwargs = {}
        if 'name' in data:
            kwargs['name'] = data.get('name')
        if 'url' in data:
            kwargs['url'] = data.get('url')
        if 'secret' in data:
            kwargs['secret'] = data.get('secret')
        if 'event_types' in data:
            kwargs['event_types'] = data.get('event_types') or []
        if 'is_active' in data:
            kwargs['is_active'] = str(data.get('is_active')) in ('1', 'true', 'True', 'on')

        config = WebhookService.update_config(config_id, **kwargs)
        if not config:
            return jsonify({'success': False, 'message': '配置不存在'}), 404

        after_snap = config.to_dict()
        log_operation('webhook_update', f'更新 Webhook 配置「{config.name}」',
                      resource_type='webhook', resource_id=config.id,
                      before_data=before_snap, after_data=after_snap)
        return jsonify({'success': True, 'config': config.to_dict()})

    @app.route('/api/admin/webhooks/<int:config_id>', methods=['DELETE'])
    @login_required
    def api_webhook_delete(config_id):
        """删除 Webhook 配置"""
        config = WebhookService.get_config(config_id)
        if not config:
            return jsonify({'success': False, 'message': '配置不存在'}), 404
        before_snap = config.to_dict()
        ok = WebhookService.delete_config(config_id)
        if ok:
            log_operation('webhook_delete', f'删除 Webhook 配置「{config.name}」',
                          resource_type='webhook', resource_id=config_id,
                          before_data=before_snap)
        return jsonify({'success': ok})

    @app.route('/api/admin/webhooks/<int:config_id>/test', methods=['POST'])
    @login_required
    def api_webhook_test(config_id):
        """测试 Webhook 配置"""
        success, message = WebhookService.test_config(config_id)
        return jsonify({'success': success, 'message': message})

    return app

if __name__ == '__main__':
    app = create_app()
    app.run(host='0.0.0.0', port=8000)
