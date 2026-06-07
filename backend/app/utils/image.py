import os
import time
import threading
from datetime import datetime
from sqlalchemy import func
from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS
import requests

from .constants import ALLOWED_EXTENSIONS, UPLOAD_FOLDER
from ..db import db, Photo, Trip


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def _dms_to_degrees(dms, ref):
    try:
        degrees = float(dms[0])
        minutes = float(dms[1])
        seconds = float(dms[2])
        result = degrees + (minutes / 60.0) + (seconds / 3600.0)
        if ref in ('S', 'W'):
            result = -result
        return result
    except Exception:
        return None


def extract_exif(file_path):
    result = {
        'camera_model': None,
        'taken_at': None,
        'gps_latitude': None,
        'gps_longitude': None,
    }
    try:
        with Image.open(file_path) as img:
            exif_data = img._getexif()
            if not exif_data:
                return result
            exif = {}
            for tag_id, value in exif_data.items():
                tag = TAGS.get(tag_id, tag_id)
                exif[tag] = value
            make = exif.get('Make', '')
            model = exif.get('Model', '')
            camera = ' '.join([str(make).strip(), str(model).strip()]).strip()
            if camera:
                result['camera_model'] = camera[:100]
            dt_original = exif.get('DateTimeOriginal') or exif.get('DateTime')
            if dt_original:
                try:
                    result['taken_at'] = datetime.strptime(str(dt_original), '%Y:%m:%d %H:%M:%S')
                except (ValueError, TypeError):
                    pass
            gps_info_tag = None
            for tag_id, value in exif_data.items():
                if TAGS.get(tag_id) == 'GPSInfo':
                    gps_info_tag = value
                    break
            if gps_info_tag:
                gps = {}
                for k, v in gps_info_tag.items():
                    gps[GPSTAGS.get(k, k)] = v
                lat = gps.get('GPSLatitude')
                lat_ref = gps.get('GPSLatitudeRef')
                lon = gps.get('GPSLongitude')
                lon_ref = gps.get('GPSLongitudeRef')
                if lat and lat_ref:
                    result['gps_latitude'] = _dms_to_degrees(lat, lat_ref)
                if lon and lon_ref:
                    result['gps_longitude'] = _dms_to_degrees(lon, lon_ref)
    except Exception:
        pass
    return result


def get_image_format(filename):
    if '.' in filename:
        ext = filename.rsplit('.', 1)[1].lower()
        if ext == 'jpeg':
            ext = 'jpg'
        return ext
    return None


def reverse_geocode(latitude, longitude):
    if latitude is None or longitude is None:
        return None
    try:
        url = "https://nominatim.openstreetmap.org/reverse"
        params = {
            'lat': str(latitude),
            'lon': str(longitude),
            'format': 'json',
            'zoom': 14,
            'addressdetails': 1,
            'accept-language': 'zh-CN'
        }
        headers = {
            'User-Agent': 'PhotoAlbumApp/1.0 (local)'
        }
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        if resp.status_code != 200:
            return None
        data = resp.json()
        if not data or 'address' not in data:
            return None
        addr = data['address']
        result = {
            'country': addr.get('country'),
            'province': addr.get('state') or addr.get('province'),
            'city': addr.get('city') or addr.get('town') or addr.get('county'),
            'district': addr.get('suburb') or addr.get('district') or addr.get('township'),
            'address': data.get('display_name')
        }
        for k, v in list(result.items()):
            if isinstance(v, str):
                result[k] = v.strip() or None
        if not any(result.values()):
            return None
        return result
    except Exception:
        return None


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
        dist = haversine_distance(
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


def process_photo_location(photo):
    if photo.location_manual:
        return
    if photo.gps_latitude is None or photo.gps_longitude is None:
        return
    if photo.location_city or photo.location_address:
        return
    result = reverse_geocode(photo.gps_latitude, photo.gps_longitude)
    if result:
        photo.location_country = result.get('country')
        photo.location_province = result.get('province')
        photo.location_city = result.get('city')
        photo.location_district = result.get('district')
        photo.location_address = result.get('address')


def process_uploaded_locations_async(app_instance, photo_ids):
    with app_instance.app_context():
        try:
            for pid in photo_ids:
                photo = Photo.query.get(pid)
                if not photo:
                    continue
                process_photo_location(photo)
                time.sleep(1.0)
            db.session.commit()
            infer_trips(photo_ids=photo_ids)
        except Exception:
            pass
