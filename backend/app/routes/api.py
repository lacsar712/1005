from flask import Blueprint, jsonify, request
from flask_login import login_required

from ..db import db, Comment, OperationLog, Notification, WebhookConfig
from ..services import NotificationService, AggregationService, WebhookService
from ..utils import (
    log_operation,
    model_snapshot,
    diff_snapshots,
    collect_dashboard_stats,
    infer_trips,
)

api_bp = Blueprint('api', __name__)


@api_bp.route('/api/comment/<int:comment_id>', methods=['DELETE'], endpoint='delete_comment')
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


@api_bp.route('/api/admin/logs/<int:log_id>', endpoint='api_log_detail')
@login_required
def api_log_detail(log_id):
    log = OperationLog.query.get_or_404(log_id)
    data = log.to_dict(include_children=True)
    data['before_data'] = log.before_data
    data['after_data'] = log.after_data
    data['diffs'] = diff_snapshots(log.before_data or {}, log.after_data or {})
    return jsonify({'success': True, 'log': data})


@api_bp.route('/api/admin/dashboard', endpoint='api_admin_dashboard')
@login_required
def api_admin_dashboard():
    days = request.args.get('days', 7, type=int)
    if days not in (7, 30):
        days = 7
    stats = collect_dashboard_stats(days=days)
    return jsonify({'success': True, 'stats': stats})


@api_bp.route('/api/admin/infer-trips', methods=['POST'], endpoint='api_infer_trips')
@login_required
def api_infer_trips():
    try:
        infer_trips()
        return jsonify({'success': True, 'message': '行程推断完成'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@api_bp.route('/api/notifications/unread-count', endpoint='api_notification_unread_count')
@login_required
def api_notification_unread_count():
    return jsonify({
        'success': True,
        'count': NotificationService.get_unread_count(),
    })


@api_bp.route('/api/notifications/<int:notification_id>', endpoint='api_notification_detail')
@login_required
def api_notification_detail(notification_id):
    notif = NotificationService.get_detail(notification_id)
    if not notif:
        return jsonify({'success': False, 'message': '通知不存在'}), 404
    return jsonify({
        'success': True,
        'notification': notif.to_dict(include_children=True),
    })


@api_bp.route('/api/notifications/<int:notification_id>/read', methods=['POST'], endpoint='api_notification_mark_read')
@login_required
def api_notification_mark_read(notification_id):
    notif = NotificationService.mark_as_read(notification_id)
    if notif and notif.is_aggregated:
        AggregationService.mark_parent_and_children_read(notification_id)
    return jsonify({
        'success': True,
        'unread_count': NotificationService.get_unread_count(),
    })


@api_bp.route('/api/notifications/read-all', methods=['POST'], endpoint='api_notification_mark_all_read')
@login_required
def api_notification_mark_all_read():
    count = NotificationService.mark_all_as_read()
    return jsonify({
        'success': True,
        'marked_count': count,
    })


@api_bp.route('/api/notifications/<int:notification_id>', methods=['DELETE'], endpoint='api_notification_delete')
@login_required
def api_notification_delete(notification_id):
    ok = NotificationService.delete(notification_id)
    return jsonify({
        'success': ok,
        'unread_count': NotificationService.get_unread_count(),
    })


@api_bp.route('/api/admin/webhooks', methods=['POST'], endpoint='api_webhook_create')
@login_required
def api_webhook_create():
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


@api_bp.route('/api/admin/webhooks/<int:config_id>', methods=['POST'], endpoint='api_webhook_update')
@login_required
def api_webhook_update(config_id):
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


@api_bp.route('/api/admin/webhooks/<int:config_id>', methods=['DELETE'], endpoint='api_webhook_delete')
@login_required
def api_webhook_delete(config_id):
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


@api_bp.route('/api/admin/webhooks/<int:config_id>/test', methods=['POST'], endpoint='api_webhook_test')
@login_required
def api_webhook_test(config_id):
    success, message = WebhookService.test_config(config_id)
    return jsonify({'success': success, 'message': message})
