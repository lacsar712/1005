import os
from flask import Flask, request, redirect, url_for, flash
from flask_login import LoginManager, current_user

from .db import db, Album, migrate_schema
from .services import (
    NotificationService,
    AggregationService,
    WebhookService,
    CleanupService,
)
from .utils import (
    UPLOAD_FOLDER,
    EXPORT_FOLDER,
    User,
    get_site_config,
    get_config_value,
    init_default_config,
)
from .routes import public_bp, admin_bp, api_bp


def create_app(config_overrides=None):
    app = Flask(__name__)
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev')
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:////app/data/photos.db')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
    app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024
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

    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    os.makedirs(EXPORT_FOLDER, exist_ok=True)

    with app.app_context():
        db.create_all()
        migrate_schema()
        init_default_config()
        max_size_mb = int(get_config_value('max_upload_size_mb'))
        app.config['MAX_CONTENT_LENGTH'] = max_size_mb * 1024 * 1024
        if Album.query.count() == 0:
            default_album = Album(title="我的首个相册", description="欢迎使用在线相册系统")
            db.session.add(default_album)
            db.session.commit()

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

    @app.errorhandler(413)
    def request_entity_too_large(error):
        max_size = get_config_value('max_upload_size_mb')
        flash(f'上传文件过大，单文件最大允许 {max_size} MB', 'error')
        return redirect(request.referrer or url_for('index'))

    app.register_blueprint(public_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(api_bp)

    _BP_PREFIXES = ('public.', 'admin.', 'api.')
    _alias_rules = []
    for rule in list(app.url_map.iter_rules()):
        if rule.endpoint.startswith(_BP_PREFIXES):
            short_endpoint = rule.endpoint.split('.', 1)[1]
            if short_endpoint not in app.view_functions:
                app.view_functions[short_endpoint] = app.view_functions[rule.endpoint]
            if short_endpoint not in app.url_map._rules_by_endpoint:
                from werkzeug.routing import Rule as _Rule
                new_rule = _Rule(
                    rule.rule,
                    defaults=rule.defaults,
                    subdomain=rule.subdomain,
                    methods=rule.methods,
                    build_only=rule.build_only,
                    endpoint=short_endpoint,
                    strict_slashes=rule.strict_slashes,
                    redirect_to=rule.redirect_to,
                    host=rule.host,
                )
                _alias_rules.append(new_rule)
    for _r in _alias_rules:
        app.url_map.add(_r)

    return app


if __name__ == '__main__':
    app = create_app()
    app.run(host='0.0.0.0', port=8000)
