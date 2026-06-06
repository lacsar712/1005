import json
import hashlib
import hmac
import threading
from datetime import datetime
import requests
from ..db import db, WebhookConfig, Notification


class WebhookService:
    """Webhook 推送服务"""

    @staticmethod
    def list_configs():
        return WebhookConfig.query.order_by(WebhookConfig.created_at.desc()).all()

    @staticmethod
    def get_config(config_id):
        return WebhookConfig.query.get(config_id)

    @staticmethod
    def create_config(name, url, secret=None, event_types=None, is_active=True):
        config = WebhookConfig(
            name=name.strip()[:100],
            url=url.strip()[:500],
            secret=secret.strip()[:100] if secret else None,
            event_types=event_types or [],
            is_active=is_active,
        )
        db.session.add(config)
        db.session.commit()
        return config

    @staticmethod
    def update_config(config_id, **kwargs):
        config = WebhookConfig.query.get(config_id)
        if not config:
            return None

        if 'name' in kwargs and kwargs['name'] is not None:
            config.name = kwargs['name'].strip()[:100]
        if 'url' in kwargs and kwargs['url'] is not None:
            config.url = kwargs['url'].strip()[:500]
        if 'secret' in kwargs:
            config.secret = kwargs['secret'].strip()[:100] if kwargs['secret'] else None
        if 'event_types' in kwargs:
            config.event_types = kwargs['event_types'] or []
        if 'is_active' in kwargs:
            config.is_active = bool(kwargs['is_active'])

        db.session.commit()
        return config

    @staticmethod
    def delete_config(config_id):
        config = WebhookConfig.query.get(config_id)
        if config:
            db.session.delete(config)
            db.session.commit()
            return True
        return False

    @staticmethod
    def _should_trigger(config, notification_type):
        event_types = config.event_types or []
        if 'all' in event_types:
            return True
        type_to_event = {
            Notification.TYPE_UPLOAD: 'upload',
            Notification.TYPE_UPLOAD_BATCH: 'upload',
            Notification.TYPE_DELETE: 'delete',
            Notification.TYPE_DELETE_BATCH: 'delete',
            Notification.TYPE_EXPORT_ZIP: 'export_zip',
            Notification.TYPE_RECYCLE_CLEAR: 'recycle_clear',
            Notification.TYPE_SYSTEM: 'system',
        }
        event = type_to_event.get(notification_type)
        return event in event_types

    @staticmethod
    def _generate_signature(secret, payload):
        if not secret:
            return None
        mac = hmac.new(
            secret.encode('utf-8'),
            payload.encode('utf-8'),
            hashlib.sha256,
        )
        return f"sha256={mac.hexdigest()}"

    @staticmethod
    def _build_payload(notification):
        data = notification.to_dict(include_children=True)
        return {
            'event': notification.type,
            'timestamp': datetime.utcnow().isoformat(),
            'notification': data,
        }

    @staticmethod
    def _dispatch_single(config, notification):
        try:
            payload = WebhookService._build_payload(notification)
            payload_json = json.dumps(payload, ensure_ascii=False)
            headers = {
                'Content-Type': 'application/json',
                'X-Webhook-Event': notification.type,
            }
            signature = WebhookService._generate_signature(config.secret, payload_json)
            if signature:
                headers['X-Webhook-Signature'] = signature

            response = requests.post(
                config.url,
                data=payload_json.encode('utf-8'),
                headers=headers,
                timeout=10,
            )
            if 200 <= response.status_code < 300:
                config.last_triggered_at = datetime.utcnow()
                db.session.commit()
                return True
            return False
        except Exception:
            return False

    @staticmethod
    def dispatch(notification):
        """向所有订阅该事件类型的 Webhook 推送通知"""
        if notification.parent_id is not None:
            return

        configs = WebhookConfig.query.filter_by(is_active=True).all()
        targets = [c for c in configs if WebhookService._should_trigger(c, notification.type)]

        if not targets:
            return

        def worker():
            from flask import current_app
            with current_app.app_context():
                for c in targets:
                    WebhookService._dispatch_single(c, notification)

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()

    @staticmethod
    def test_config(config_id):
        """测试 Webhook 配置是否可用"""
        config = WebhookConfig.query.get(config_id)
        if not config:
            return False, "配置不存在"

        test_notification = Notification(
            id=0,
            type=Notification.TYPE_SYSTEM,
            title='Webhook 测试',
            content='这是一条来自系统的 Webhook 测试消息',
            status=Notification.STATUS_SUCCESS,
            created_at=datetime.utcnow(),
        )
        success = WebhookService._dispatch_single(config, test_notification)
        if success:
            return True, "测试成功"
        return False, "请求失败，请检查 URL 是否可达"
