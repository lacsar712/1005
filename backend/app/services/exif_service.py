from datetime import datetime
from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS
import requests


class ExifService:
    """EXIF 数据解析与逆地理编码服务"""

    @staticmethod
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

    @staticmethod
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
                        result['gps_latitude'] = ExifService._dms_to_degrees(lat, lat_ref)
                    if lon and lon_ref:
                        result['gps_longitude'] = ExifService._dms_to_degrees(lon, lon_ref)
        except Exception:
            pass
        return result

    @staticmethod
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
