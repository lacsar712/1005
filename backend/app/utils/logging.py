from datetime import datetime, timedelta
from flask import request
from ..db import db, OperationLog


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
