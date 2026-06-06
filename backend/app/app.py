import io
import csv
import os
import uuid
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash, abort, send_from_directory, jsonify, make_response
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.utils import secure_filename
from sqlalchemy import or_, and_
from .db import db, Album, Photo, Tag, Comment, SiteConfig, OperationLog

# 常量设置
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static/uploads')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

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

def create_app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev')
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:////app/data/photos.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
    app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024  # 5MB 限制

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

    # 确保上传目录存在
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)

    with app.app_context():
        db.create_all()
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
        return {'site_config': config}

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
        parent_log = log_operation('album_delete',
                                   f'删除相册「{album.title}」（含 {photo_count} 张照片）',
                                   resource_type='album', resource_id=album.id,
                                   before_data=before_snap, commit=False)
        for photo in album.photos:
            photo_before = model_snapshot(photo)
            log_operation('photo_delete',
                          f'删除照片「{photo.original_filename}」（随相册删除）',
                          resource_type='photo', resource_id=photo.id,
                          before_data=photo_before, parent_id=parent_log.id, commit=False)
            try:
                os.remove(os.path.join(app.config['UPLOAD_FOLDER'], photo.filename))
            except OSError:
                pass
        db.session.delete(album)
        db.session.commit()
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
                    
                    file.save(os.path.join(app.config['UPLOAD_FOLDER'], unique_filename))
                    
                    new_photo = Photo(filename=unique_filename, original_filename=original_filename, album_id=album.id)
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
                else:
                    is_anomaly = detect_anomaly('photo_upload', count=uploaded_count)
                    parent_log = log_operation('photo_upload',
                                               f'批量上传 {uploaded_count} 张照片至相册「{album.title}」',
                                               resource_type='album', resource_id=album.id,
                                               is_anomaly=is_anomaly, commit=False)
                    for p in uploaded_photos:
                        log_operation('photo_upload',
                                      f'上传照片「{p.original_filename}」',
                                      resource_type='photo', resource_id=p.id,
                                      after_data=model_snapshot(p),
                                      parent_id=parent_log.id, commit=False)
                db.session.commit()
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

    return app

if __name__ == '__main__':
    app = create_app()
    app.run(host='0.0.0.0', port=8000)
