import uuid
from datetime import datetime
from ..db import db, Notification


class AggregationService:
    """通知聚合服务 - 管理批量任务的父子通知关系"""

    @staticmethod
    def create_batch_parent(
        type,
        title,
        content=None,
        task_id=None,
        data=None,
    ):
        if not task_id:
            task_id = uuid.uuid4().hex

        parent = Notification(
            type=type,
            title=title[:200],
            content=content,
            status=Notification.STATUS_PENDING,
            is_read=False,
            task_id=task_id,
            parent_id=None,
            data=data,
        )
        db.session.add(parent)
        db.session.flush()
        return parent, task_id

    @staticmethod
    def add_child(
        parent_id,
        type,
        title,
        content=None,
        status=Notification.STATUS_SUCCESS,
        data=None,
        commit=False,
    ):
        child = Notification(
            type=type,
            title=title[:200],
            content=content,
            status=status,
            is_read=False,
            parent_id=parent_id,
            data=data,
        )
        db.session.add(child)
        if commit:
            db.session.commit()
        return child

    @staticmethod
    def finalize_batch(parent_id, status=None, data=None):
        parent = Notification.query.get(parent_id)
        if not parent:
            return None

        children = parent.children.all()
        success_count = sum(1 for c in children if c.status == Notification.STATUS_SUCCESS)
        failed_count = sum(1 for c in children if c.status == Notification.STATUS_FAILED)
        total_count = len(children)

        if status is None:
            if total_count == 0:
                status = Notification.STATUS_SUCCESS
            elif failed_count == 0:
                status = Notification.STATUS_SUCCESS
            elif success_count == 0:
                status = Notification.STATUS_FAILED
            else:
                status = Notification.STATUS_PARTIAL

        parent.status = status
        if data:
            existing = parent.data or {}
            existing.update(data)
            parent.data = existing
        else:
            parent.data = {
                'total': total_count,
                'success': success_count,
                'failed': failed_count,
            }

        db.session.commit()
        return parent

    @staticmethod
    def get_children(parent_id):
        parent = Notification.query.get(parent_id)
        if not parent:
            return []
        return parent.children.order_by(Notification.created_at.desc()).all()

    @staticmethod
    def mark_parent_and_children_read(parent_id):
        parent = Notification.query.get(parent_id)
        if not parent:
            return 0

        count = 0
        now = datetime.utcnow()
        if not parent.is_read:
            parent.is_read = True
            parent.read_at = now
            count += 1

        for child in parent.children.filter_by(is_read=False).all():
            child.is_read = True
            child.read_at = now
            count += 1

        db.session.commit()
        return count
