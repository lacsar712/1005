import os
import tempfile
import shutil
import sys
from datetime import datetime

import pytest

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, _BACKEND_ROOT)
_LOCAL_DEPS = os.path.join(_BACKEND_ROOT, 'pydeps')
if os.path.isdir(_LOCAL_DEPS):
    sys.path.insert(0, _LOCAL_DEPS)

from app.db import db, Album, Photo, Tag, Comment, Notification, OperationLog


@pytest.fixture
def app():
    upload_dir = tempfile.mkdtemp(prefix='test_uploads_')
    app_config = {
        'TESTING': True,
        'SECRET_KEY': 'test-secret',
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'SQLALCHEMY_TRACK_MODIFICATIONS': False,
        'UPLOAD_FOLDER': upload_dir,
        'WTF_CSRF_ENABLED': False,
    }
    from app.app import create_app
    application = create_app(config_overrides=app_config)
    application._test_upload_dir = upload_dir

    with application.app_context():
        db.drop_all()
        db.create_all()
        yield application

    shutil.rmtree(upload_dir, ignore_errors=True)


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def logged_in_client(client):
    with client.session_transaction() as sess:
        sess['_user_id'] = '1'
    return client


@pytest.fixture
def db_session(app):
    with app.app_context():
        yield db.session


def _refresh(app, model_class, entity_id):
    with app.app_context():
        return db.session.get(model_class, entity_id)


@pytest.fixture
def sample_album_id(app):
    with app.app_context():
        album = Album(title='测试相册', description='用于删除测试的相册')
        db.session.add(album)
        db.session.commit()
        return album.id


@pytest.fixture
def sample_photo_id(app, sample_album_id):
    with app.app_context():
        photo = Photo(
            filename='test_photo.jpg',
            original_filename='测试照片.jpg',
            album_id=sample_album_id,
            description='测试用照片描述',
        )
        db.session.add(photo)
        db.session.commit()
        return photo.id


@pytest.fixture
def sample_tag_id(app):
    with app.app_context():
        tag = Tag(name='风景')
        db.session.add(tag)
        db.session.commit()
        return tag.id


@pytest.fixture
def photo_with_relations_ids(app, sample_album_id, sample_tag_id):
    with app.app_context():
        upload_dir = app.config['UPLOAD_FOLDER']
        physical_filename = 'rel_photo.jpg'
        physical_path = os.path.join(upload_dir, physical_filename)
        with open(physical_path, 'wb') as f:
            f.write(b'fake image content for test')

        photo = Photo(
            filename=physical_filename,
            original_filename='关联测试照片.jpg',
            album_id=sample_album_id,
        )
        db.session.add(photo)
        db.session.flush()

        tag = db.session.get(Tag, sample_tag_id)
        photo.tags.append(tag)

        comment = Comment(
            photo_id=photo.id,
            nickname='测试用户',
            content='这是一条测试评论',
        )
        db.session.add(comment)
        db.session.commit()
        return {
            'photo_id': photo.id,
            'album_id': sample_album_id,
            'tag_id': sample_tag_id,
            'comment_ids': [comment.id],
            'filename': physical_filename,
            'original_filename': photo.original_filename,
        }


@pytest.fixture
def album_with_multiple_photos_ids(app):
    with app.app_context():
        upload_dir = app.config['UPLOAD_FOLDER']
        album = Album(title='多图相册', description='含有多张照片的测试相册')
        db.session.add(album)
        db.session.flush()

        tag_a = Tag(name='城市')
        tag_b = Tag(name='自然')
        db.session.add_all([tag_a, tag_b])
        db.session.flush()

        photo_ids = []
        filenames = []
        comment_ids = []
        for i, (fname, orig) in enumerate([
            ('p1.jpg', '照片一.jpg'),
            ('p2.jpg', '照片二.jpg'),
            ('p3.jpg', '照片三.jpg'),
        ]):
            physical_path = os.path.join(upload_dir, fname)
            with open(physical_path, 'wb') as f:
                f.write(b'fake image bytes %d' % i)
            p = Photo(filename=fname, original_filename=orig, album_id=album.id)
            db.session.add(p)
            db.session.flush()
            if i % 2 == 0:
                p.tags.append(tag_a)
            else:
                p.tags.append(tag_b)
            c = Comment(photo_id=p.id, nickname='访客', content='评论 %d' % i)
            db.session.add(c)
            db.session.flush()
            photo_ids.append(p.id)
            filenames.append(fname)
            comment_ids.append(c.id)

        db.session.commit()
        return {
            'album_id': album.id,
            'album_title': album.title,
            'photo_ids': photo_ids,
            'filenames': filenames,
            'comment_ids': comment_ids,
            'tag_ids': [tag_a.id, tag_b.id],
        }
