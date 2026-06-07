from ..db import Notification
from ..services import NotificationService, WebhookService, CleanupService


def dispatch_notification(
    type,
    title,
    content=None,
    status=Notification.STATUS_SUCCESS,
    task_id=None,
    parent_id=None,
    data=None,
):
    notif = NotificationService.create(
        type=type, title=title, content=content, status=status,
        task_id=task_id, parent_id=parent_id, data=data,
    )
    WebhookService.dispatch(notif)
    CleanupService.cleanup_if_needed()
    return notif
