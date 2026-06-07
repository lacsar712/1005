import os

UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'static', 'uploads')
EXPORT_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'static', 'exports')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
EXPORT_EXPIRE_DAYS = 7

ADMIN_USERNAME = 'admin'
ADMIN_PASSWORD = '123456'
