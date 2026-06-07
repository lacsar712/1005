import os
from sqlalchemy import inspect, text
from flask import jsonify, current_app
from .db import db
from .utils.constants import UPLOAD_FOLDER
from .utils.config import get_config_value, set_config_value

SCHEMA_VERSION_KEY = 'schema_version'
CURRENT_SCHEMA_VERSION = 1


def get_schema_version():
    try:
        version = get_config_value(SCHEMA_VERSION_KEY)
        if version:
            return int(version)
    except Exception:
        pass
    inspector = inspect(db.engine)
    tables = inspector.get_table_names()
    if 'site_config' in tables:
        return CURRENT_SCHEMA_VERSION
    return 0


def ensure_schema_version_recorded():
    try:
        existing = get_config_value(SCHEMA_VERSION_KEY)
        if not existing:
            set_config_value(SCHEMA_VERSION_KEY, str(CURRENT_SCHEMA_VERSION))
    except Exception:
        pass


def check_sqlite():
    try:
        db.session.execute(text('SELECT 1'))
        db.session.commit()
        inspector = inspect(db.engine)
        inspector.get_table_names()
        return True, None
    except Exception as e:
        return False, str(e)


def check_uploads_writable():
    try:
        test_file = os.path.join(UPLOAD_FOLDER, '.health_write_test')
        with open(test_file, 'w') as f:
            f.write('ok')
        os.remove(test_file)
        return True, None
    except Exception as e:
        return False, str(e)


def check_schema_version():
    try:
        version = get_schema_version()
        ok = version >= CURRENT_SCHEMA_VERSION
        return ok, f"version={version}, expected>={CURRENT_SCHEMA_VERSION}"
    except Exception as e:
        return False, str(e)


def run_health_checks(include_ready=False):
    checks = {}
    overall_ok = True

    sqlite_ok, sqlite_msg = check_sqlite()
    checks['sqlite'] = {'status': 'ok' if sqlite_ok else 'fail', 'details': sqlite_msg or ''}
    if not sqlite_ok:
        overall_ok = False

    if include_ready:
        uploads_ok, uploads_msg = check_uploads_writable()
        checks['uploads_writable'] = {'status': 'ok' if uploads_ok else 'fail', 'details': uploads_msg or ''}
        if not uploads_ok:
            overall_ok = False

        schema_ok, schema_msg = check_schema_version()
        checks['schema_version'] = {'status': 'ok' if schema_ok else 'fail', 'details': schema_msg or ''}
        if not schema_ok:
            overall_ok = False

    return overall_ok, checks
