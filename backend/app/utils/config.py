from ..db import db, SiteConfig


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
    configs = SiteConfig.query.all()
    result = dict(DEFAULT_SITE_CONFIG)
    for cfg in configs:
        result[cfg.config_key] = cfg.config_value
    return result


def get_config_value(key):
    cfg = SiteConfig.query.filter_by(config_key=key).first()
    if cfg:
        return cfg.config_value
    return DEFAULT_SITE_CONFIG.get(key, '')


def set_config_value(key, value):
    cfg = SiteConfig.query.filter_by(config_key=key).first()
    if cfg:
        cfg.config_value = str(value)
    else:
        cfg = SiteConfig(config_key=key, config_value=str(value))
        db.session.add(cfg)
    db.session.commit()


def init_default_config():
    for key, value in DEFAULT_SITE_CONFIG.items():
        if not SiteConfig.query.filter_by(config_key=key).first():
            cfg = SiteConfig(config_key=key, config_value=value)
            db.session.add(cfg)
    db.session.commit()
