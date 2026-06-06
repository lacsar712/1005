from datetime import datetime
from ..db import db, Notification


class NotificationService:
    """通知创建与查询服务"""

    @staticmethod
    def create(
        type,
        title,
        content=None,
        status=Notification.STATUS_SUCCESS,
        task_id=None,
        parent_id=None,
        data=None,
        commit=True,
    ):
        notification = Notification(
            type=type,
            title=title[:200],
            content=content,
            status=status,
            is_read=False,
            task_id=task_id,
            parent_id=parent_id,
            data=data,
        )
        db.session.add(notification)
        if commit:
            db.session.commit()
        return notification

    @staticmethod
    def get_unread_count():
        return Notification.query.filter_by(is_read=False, parent_id=None).count()

    @staticmethod
    def get_list(
        page=1,
        per_page=20,
        type_filter=None,
        status_filter=None,
        unread_only=False,
    ):
        query = Notification.query.filter(Notification.parent_id.is_(None))

        if type_filter:
            query = query.filter(Notification.type == type_filter)

        if status_filter:
            query = query.filter(Notification.status == status_filter)

        if unread_only:
            query = query.filter(Notification.is_read == False)

        query = query.order_by(Notification.created_at.desc())
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)
        return pagination

    @staticmethod
    def get_detail(notification_id):
        return Notification.query.get(notification_id)

    @staticmethod
    def mark_as_read(notification_id):
        notification = Notification.query.get(notification_id)
        if notification and not notification.is_read:
            notification.is_read = True
            notification.read_at = datetime.utcnow()
            db.session.commit()
        return notification

    @staticmethod
    def mark_all_as_read():
        count = Notification.query.filter_by(is_read=False).update(
            {Notification.is_read: True, Notification.read_at: datetime.utcnow()}
        )
        db.session.commit()
        return count

    @staticmethod
    def delete(notification_id):
        notification = Notification.query.get(notification_id)
        if notification:
            db.session.delete(notification)
            db.session.commit()
            return True
        return False

    @staticmethod
    def find_parent_by_task_id(task_id):
        if not task_id:
            return None
        return Notification.query.filter_by(task_id=task_id, parent_id=None).first()
