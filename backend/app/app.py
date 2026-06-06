import os
import uuid
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, abort, send_from_directory, jsonify
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.utils import secure_filename
from .db import db, Album, Photo, Tag, Comment, SiteConfig

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
                flash('登录成功', 'success')
                return redirect(url_for('index'))
            else:
                flash('用户名或密码错误', 'error')
        return render_template('login.html')

    @app.route('/admin/logout')
    @login_required
    def logout():
        """管理员登出"""
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
                db.session.commit()
                flash('相册创建成功', 'success')
                return redirect(url_for('index'))
        return render_template('create_album.html')

    @app.route('/album/delete/<int:album_id>')
    @login_required
    def delete_album(album_id):
        """删除相册及关联图片"""
        album = Album.query.get_or_404(album_id)
        # 删除物理文件
        for photo in album.photos:
            try:
                os.remove(os.path.join(app.config['UPLOAD_FOLDER'], photo.filename))
            except OSError:
                pass # 文件可能不存在
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
                    uploaded_count += 1
            
            if uploaded_count > 0:
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
            tag.name = new_name
            db.session.commit()
            flash(f'标签已从「{old_name}」重命名为「{new_name}」', 'success')
        return redirect(url_for('manage_tags'))

    @app.route('/admin/tag/delete/<int:tag_id>')
    @login_required
    def delete_tag(tag_id):
        """删除标签（仅解除关联，不删除照片）"""
        tag = Tag.query.get_or_404(tag_id)
        tag_name = tag.name
        db.session.delete(tag)
        db.session.commit()
        flash(f'标签「{tag_name}」已删除（关联照片未受影响）', 'success')
        return redirect(url_for('manage_tags'))

    @app.route('/photo/<int:photo_id>/tags', methods=['POST'])
    @login_required
    def set_photo_tags(photo_id):
        """为照片设置标签"""
        photo = Photo.query.get_or_404(photo_id)
        tag_ids = request.form.getlist('tag_ids')
        tag_ids = [int(tid) for tid in tag_ids if tid.isdigit()]
        selected_tags = Tag.query.filter(Tag.id.in_(tag_ids)).all() if tag_ids else []
        photo.tags = selected_tags
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

        set_config_value('site_name', site_name)
        set_config_value('welcome_message', welcome_message)
        set_config_value('copyright_text', copyright_text)
        set_config_value('contact_email', contact_email)
        set_config_value('max_upload_size_mb', str(size_mb))
        set_config_value('album_sort_by', album_sort_by)
        set_config_value('show_site_stats', show_site_stats)

        app.config['MAX_CONTENT_LENGTH'] = size_mb * 1024 * 1024

        flash('站点设置已保存', 'success')
        return redirect(url_for('site_settings'))

    return app

if __name__ == '__main__':
    app = create_app()
    app.run(host='0.0.0.0', port=8000)
