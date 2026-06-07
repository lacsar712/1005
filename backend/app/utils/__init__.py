from .constants import (
    UPLOAD_FOLDER,
    EXPORT_FOLDER,
    ALLOWED_EXTENSIONS,
    EXPORT_EXPIRE_DAYS,
    ADMIN_USERNAME,
    ADMIN_PASSWORD,
)
from .auth import User
from .logging import (
    get_client_ip,
    detect_anomaly,
    log_operation,
    model_snapshot,
    diff_snapshots,
)
from .config import (
    DEFAULT_SITE_CONFIG,
    get_site_config,
    get_config_value,
    set_config_value,
    init_default_config,
)
from .search import (
    levenshtein_distance,
    fuzzy_match,
    highlight_keywords,
)
from ..services.exif_service import ExifService
from ..services.photo_service import PhotoService


def allowed_file(filename):
    return PhotoService.allowed_file(filename)


def extract_exif(file_path):
    return ExifService.extract_exif(file_path)


def get_image_format(filename):
    return PhotoService.get_image_format(filename)


def reverse_geocode(latitude, longitude):
    return ExifService.reverse_geocode(latitude, longitude)


def haversine_distance(lat1, lon1, lat2, lon2):
    return PhotoService.haversine_distance(lat1, lon1, lat2, lon2)


def infer_trips(photo_ids=None, min_photos=2, time_gap_hours=6, distance_gap_meters=5000):
    return PhotoService.infer_trips(
        photo_ids=photo_ids,
        min_photos=min_photos,
        time_gap_hours=time_gap_hours,
        distance_gap_meters=distance_gap_meters,
    )


def process_photo_location(photo):
    return PhotoService.process_photo_location(photo)


def process_uploaded_locations_async(app_instance, photo_ids):
    return PhotoService.process_uploaded_locations_async(app_instance, photo_ids)


from .notifications import dispatch_notification
from .dashboard import (
    estimate_disk_usage_bytes,
    format_bytes,
    collect_dashboard_stats,
)
from .export import process_export_job

__all__ = [
    'UPLOAD_FOLDER',
    'EXPORT_FOLDER',
    'ALLOWED_EXTENSIONS',
    'EXPORT_EXPIRE_DAYS',
    'ADMIN_USERNAME',
    'ADMIN_PASSWORD',
    'User',
    'get_client_ip',
    'detect_anomaly',
    'log_operation',
    'model_snapshot',
    'diff_snapshots',
    'DEFAULT_SITE_CONFIG',
    'get_site_config',
    'get_config_value',
    'set_config_value',
    'init_default_config',
    'levenshtein_distance',
    'fuzzy_match',
    'highlight_keywords',
    'allowed_file',
    'extract_exif',
    'get_image_format',
    'reverse_geocode',
    'haversine_distance',
    'infer_trips',
    'process_photo_location',
    'process_uploaded_locations_async',
    'dispatch_notification',
    'estimate_disk_usage_bytes',
    'format_bytes',
    'collect_dashboard_stats',
    'process_export_job',
]
