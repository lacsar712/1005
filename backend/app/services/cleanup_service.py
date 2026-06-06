from ..db import db, Notification


class CleanupService:
    """通知清理服务 - 保留最近 N 条，超出自动清理"""

    @staticmethod
    def cleanup(max_count=Notification.MAX_RETENTION):
        total = Notification.query.count()
        if total <= max_count:
            return 0

        subquery = (
            Notification.query
            .order_by(Notification.created_at.desc())
            .limit(max_count)
            .with_entities(Notification.id)
            .subquery()
        )

        to_delete = (
            Notification.query
            .filter(~Notification.id.in_(subquery))
            .all()
        )

        deleted_count = len(to_delete)
        for n in to_delete:
            db.session.delete(n)
        db.session.commit()
        return deleted_count

    @staticmethod
    def cleanup_if_needed(max_count=Notification.MAX_RETENTION):
        total = Notification.query.count()
        if total > max_count + 10:
            return CleanupService.cleanup(max_count)
        return 0
