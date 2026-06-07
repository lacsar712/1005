import os
from unittest.mock import patch

import pytest

from app.db import (
    db, Album, Photo, Tag, Comment, Notification, OperationLog, photo_tags,
)


class TestDeleteSinglePhoto:
    """删除单张照片的多模块联调测试"""

    def test_delete_photo_cascades_tags_comments_and_file(
        self, app, logged_in_client, photo_with_relations_ids
    ):
        ids = photo_with_relations_ids
        photo_id = ids['photo_id']
        album_id = ids['album_id']
        tag_id = ids['tag_id']
        comment_ids = ids['comment_ids']
        filename = ids['filename']
        physical_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)

        assert os.path.isfile(physical_path)

        with patch('app.app.WebhookService.dispatch'):
            resp = logged_in_client.get(
                f'/photo/delete/{photo_id}', follow_redirects=False
            )

        assert resp.status_code == 302
        assert f'/album/{album_id}' in resp.headers['Location']

        with app.app_context():
            assert Photo.query.get(photo_id) is None

            for cid in comment_ids:
                assert Comment.query.get(cid) is None

            tag_link = db.session.query(photo_tags).filter(
                photo_tags.c.photo_id == photo_id,
                photo_tags.c.tag_id == tag_id,
            ).first()
            assert tag_link is None
            assert Tag.query.get(tag_id) is not None

            assert not os.path.exists(physical_path)

    def test_delete_photo_writes_operation_log(
        self, app, logged_in_client, photo_with_relations_ids
    ):
        ids = photo_with_relations_ids
        photo_id = ids['photo_id']
        original_name = ids['original_filename']
        filename = ids['filename']

        with patch('app.app.WebhookService.dispatch'):
            logged_in_client.get(f'/photo/delete/{photo_id}')

        with app.app_context():
            log = OperationLog.query.filter_by(
                operation_type='photo_delete',
                resource_type='photo',
                resource_id=str(photo_id),
            ).first()
            assert log is not None
            assert original_name in log.summary
            assert log.before_data is not None
            assert log.before_data.get('filename') == filename

    def test_delete_photo_creates_notification_and_dispatches_webhook(
        self, app, logged_in_client, photo_with_relations_ids
    ):
        ids = photo_with_relations_ids
        photo_id = ids['photo_id']
        original_name = ids['original_filename']

        with patch('app.app.WebhookService.dispatch') as mock_dispatch:
            logged_in_client.get(f'/photo/delete/{photo_id}')

            mock_dispatch.assert_called_once()
            notif_arg = mock_dispatch.call_args[0][0]
            assert notif_arg.type == Notification.TYPE_DELETE
            assert original_name in notif_arg.content

        with app.app_context():
            notif = Notification.query.filter_by(
                type=Notification.TYPE_DELETE,
            ).order_by(Notification.id.desc()).first()
            assert notif is not None
            assert notif.data and notif.data.get('photo_id') == photo_id


class TestDeleteAlbum:
    """删除整本相册的多模块联调测试"""

    def test_delete_album_removes_all_photos_and_relations(
        self, app, logged_in_client, album_with_multiple_photos_ids
    ):
        data = album_with_multiple_photos_ids
        album_id = data['album_id']
        photo_ids = data['photo_ids']
        filenames = data['filenames']
        comment_ids = data['comment_ids']

        upload_dir = app.config['UPLOAD_FOLDER']
        for fn in filenames:
            assert os.path.isfile(os.path.join(upload_dir, fn))

        with patch('app.app.WebhookService.dispatch'):
            resp = logged_in_client.get(
                f'/album/delete/{album_id}', follow_redirects=False
            )

        assert resp.status_code == 302
        assert '/' in resp.headers['Location']

        with app.app_context():
            assert Album.query.get(album_id) is None

            for pid in photo_ids:
                assert Photo.query.get(pid) is None

            for cid in comment_ids:
                assert Comment.query.get(cid) is None

            link_count = db.session.query(photo_tags).filter(
                photo_tags.c.photo_id.in_(photo_ids)
            ).count()
            assert link_count == 0

            for fn in filenames:
                assert not os.path.exists(os.path.join(upload_dir, fn))

            tags_remaining = Tag.query.count()
            assert tags_remaining > 0

    def test_delete_album_writes_operation_log_with_summary(
        self, app, logged_in_client, album_with_multiple_photos_ids
    ):
        data = album_with_multiple_photos_ids
        album_id = data['album_id']
        album_title = data['album_title']
        photo_count = len(data['photo_ids'])

        with patch('app.app.WebhookService.dispatch'):
            logged_in_client.get(f'/album/delete/{album_id}')

        with app.app_context():
            album_log = OperationLog.query.filter_by(
                operation_type='album_delete',
                resource_type='album',
                resource_id=str(album_id),
            ).first()
            assert album_log is not None
            assert album_title in album_log.summary
            assert str(photo_count) in album_log.summary

            photo_logs = OperationLog.query.filter_by(
                operation_type='photo_delete',
                parent_id=album_log.id,
            ).all()
            assert len(photo_logs) == photo_count

    def test_delete_album_batch_notification_and_webhook_dispatch(
        self, app, logged_in_client, album_with_multiple_photos_ids
    ):
        data = album_with_multiple_photos_ids
        album_id = data['album_id']
        photo_count = len(data['photo_ids'])

        with patch('app.app.WebhookService.dispatch') as mock_dispatch:
            logged_in_client.get(f'/album/delete/{album_id}')

            mock_dispatch.assert_called_once()
            batch_notif = mock_dispatch.call_args[0][0]
            assert batch_notif.type == Notification.TYPE_DELETE_BATCH
            assert str(photo_count) in batch_notif.title

        with app.app_context():
            parent = Notification.query.filter_by(
                type=Notification.TYPE_DELETE_BATCH,
            ).order_by(Notification.id.desc()).first()
            assert parent is not None
            assert parent.children.count() == photo_count
            assert parent.status == Notification.STATUS_SUCCESS
            assert parent.data is not None
            assert parent.data.get('total') == photo_count
            assert parent.data.get('album_id') == album_id


class TestDeleteNonExistentIds:
    """对不存在的 ID 进行边界测试"""

    def test_delete_nonexistent_photo_returns_404(
        self, app, logged_in_client
    ):
        non_existent_id = 99999
        with patch('app.app.WebhookService.dispatch'):
            resp = logged_in_client.get(
                f'/photo/delete/{non_existent_id}'
            )
        assert resp.status_code == 404

    def test_delete_nonexistent_album_returns_404(
        self, app, logged_in_client
    ):
        non_existent_id = 99999
        with patch('app.app.WebhookService.dispatch'):
            resp = logged_in_client.get(
                f'/album/delete/{non_existent_id}'
            )
        assert resp.status_code == 404

    def test_delete_nonexistent_photo_no_side_effects(
        self, app, logged_in_client, sample_album_id
    ):
        before_notif_count = 0
        before_log_count = 0
        with app.app_context():
            before_notif_count = Notification.query.count()
            before_log_count = OperationLog.query.count()

        with patch('app.app.WebhookService.dispatch') as mock_dispatch:
            resp = logged_in_client.get('/photo/delete/123456')

        assert resp.status_code == 404
        with app.app_context():
            assert Notification.query.count() == before_notif_count
            assert OperationLog.query.count() == before_log_count
        mock_dispatch.assert_not_called()
