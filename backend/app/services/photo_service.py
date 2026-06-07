import os
import time
import uuid
from datetime import datetime
from sqlalchemy import func
from werkzeug.utils import secure_filename

from .exif_service import ExifService
from ..utils.constants import ALLOWED_EXTENSIONS
from ..db import db, Photo, Trip


class PhotoService:
    """照片上传、地点处理与行程推断服务"""

    @staticmethod
    def allowed_file(filename):
        return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

    @staticmethod
    def get_image_format(filename):
        if '.' in filename:
            ext = filename.rsplit('.', 1)[1].lower()
            if ext == 'jpeg':
                ext = 'jpg'
            return ext
        return None

    @staticmethod
    def save_uploaded_photos(files, album_id, upload_folder, max_size_bytes):
        """处理上传文件列表，保存到磁盘并创建 Photo 记录（已加入 session 但未 commit）。
        返回 (uploaded_photos, uploaded_count)。
        """
        uploaded_photos = []
        uploaded_count = 0

        for file in files:
            if file.filename == '':
                continue

            if file and PhotoService.allowed_file(file.filename):
                file.seek(0, os.SEEK_END)
                file_size = file.tell()
                file.seek(0)
                if file_size > max_size_bytes:
                    continue

                original_filename = secure_filename(file.filename)
                if not original_filename:
                    original_filename = "未命名图片"

                try:
                    extension = file.filename.rsplit('.', 1)[1].lower()
                except IndexError:
                    continue

                unique_filename = f"{uuid.uuid4().hex}.{extension}"
                saved_path = os.path.join(upload_folder, unique_filename)
                file.save(saved_path)

                exif_info = ExifService.extract_exif(saved_path)
                img_format = PhotoService.get_image_format(original_filename)

                new_photo = Photo(
                    filename=unique_filename,
                    original_filename=original_filename,
                    album_id=album_id,
                    camera_model=exif_info['camera_model'],
                    taken_at=exif_info['taken_at'],
                    gps_latitude=exif_info['gps_latitude'],
                    gps_longitude=exif_info['gps_longitude'],
                    image_format=img_format
                )
                db.session.add(new_photo)
                db.session.flush()
                uploaded_photos.append(new_photo)
                uploaded_count += 1

        return uploaded_photos, uploaded_count

    @staticmethod
    def process_photo_location(photo):
        if photo.location_manual:
            return
        if photo.gps_latitude is None or photo.gps_longitude is None:
            return
        if photo.location_city or photo.location_address:
            return
        result = ExifService.reverse_geocode(photo.gps_latitude, photo.gps_longitude)
        if result:
            photo.location_country = result.get('country')
            photo.location_province = result.get('province')
            photo.location_city = result.get('city')
            photo.location_district = result.get('district')
            photo.location_address = result.get('address')

    @staticmethod
    def process_uploaded_locations_async(app_instance, photo_ids):
        with app_instance.app_context():
            try:
                for pid in photo_ids:
                    photo = Photo.query.get(pid)
                    if not photo:
                        continue
                    PhotoService.process_photo_location(photo)
                    time.sleep(1.0)
                db.session.commit()
                PhotoService.infer_trips(photo_ids=photo_ids)
            except Exception:
                pass

    @staticmethod
    def haversine_distance(lat1, lon1, lat2, lon2):
        if None in (lat1, lon1, lat2, lon2):
            return float('inf')
        import math
        R = 6371000
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlmb = math.radians(lon2 - lon1)
        a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2) ** 2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return R * c

    @staticmethod
    def _haversine_distance(lat1, lon1, lat2, lon2):
        return PhotoService.haversine_distance(lat1, lon1, lat2, lon2)

    @staticmethod
    def infer_trips(photo_ids=None, min_photos=2, time_gap_hours=6, distance_gap_meters=5000):
        query = Photo.query.filter(
            Photo.gps_latitude.isnot(None),
            Photo.gps_longitude.isnot(None)
        )
        if photo_ids:
            query = query.filter(Photo.id.in_(photo_ids))
        all_photos = query.order_by(func.coalesce(Photo.taken_at, Photo.uploaded_at).asc()).all()
        if len(all_photos) < min_photos:
            return

        clusters = []
        current_cluster = []
        prev_photo = None

        for photo in all_photos:
            if prev_photo is None:
                current_cluster = [photo]
                prev_photo = photo
                continue
            prev_time = prev_photo.taken_at or prev_photo.uploaded_at
            curr_time = photo.taken_at or photo.uploaded_at
            time_diff = (curr_time - prev_time).total_seconds() / 3600.0 if prev_time and curr_time else float('inf')
            dist = PhotoService._haversine_distance(
                prev_photo.gps_latitude, prev_photo.gps_longitude,
                photo.gps_latitude, photo.gps_longitude
            )
            if time_diff > time_gap_hours or dist > distance_gap_meters:
                if len(current_cluster) >= min_photos:
                    clusters.append(current_cluster)
                current_cluster = [photo]
            else:
                current_cluster.append(photo)
            prev_photo = photo

        if len(current_cluster) >= min_photos:
            clusters.append(current_cluster)

        for cluster in clusters:
            sorted_photos = sorted(
                cluster,
                key=lambda p: (p.taken_at or p.uploaded_at or datetime.min)
            )
            first_p = sorted_photos[0]
            last_p = sorted_photos[-1]
            start_time = first_p.taken_at or first_p.uploaded_at
            end_time = last_p.taken_at or last_p.uploaded_at

            locations = set()
            for p in sorted_photos:
                loc = p.location_short
                if loc:
                    locations.add(loc)
            loc_summary = ' → '.join(list(locations)[:3]) if locations else None

            same_trip_ids = set()
            for p in sorted_photos:
                if p.trip_id:
                    same_trip_ids.add(p.trip_id)

            trip = None
            if len(same_trip_ids) == 1:
                trip = Trip.query.get(list(same_trip_ids)[0])

            if trip is None:
                trip = Trip()
                db.session.add(trip)
                db.session.flush()

            trip.start_time = start_time
            trip.end_time = end_time
            trip.start_latitude = first_p.gps_latitude
            trip.start_longitude = first_p.gps_longitude
            trip.end_latitude = last_p.gps_latitude
            trip.end_longitude = last_p.gps_longitude
            trip.location_summary = loc_summary

            date_str = start_time.strftime('%Y-%m-%d') if start_time else '未知日期'
            city_str = ''
            for p in sorted_photos:
                if p.location_city:
                    city_str = p.location_city
                    break
            if city_str:
                trip.name = f"{city_str}之旅 · {date_str}"
            else:
                trip.name = f"行程 · {date_str}"

            for p in sorted_photos:
                p.trip_id = trip.id

        db.session.commit()
