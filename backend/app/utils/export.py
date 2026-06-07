import io
import os
import re
import json
import uuid
import zipfile
import threading
import traceback
from datetime import datetime, timedelta
from PIL import Image

from .constants import EXPORT_FOLDER, UPLOAD_FOLDER, EXPORT_EXPIRE_DAYS
from .logging import log_operation, get_client_ip
from .notifications import dispatch_notification
from ..db import db, Album, Photo, ExportJob, DownloadHistory, Notification, format_bytes_human


def _resize_for_web(img_path, max_long_side=1920):
    try:
        with Image.open(img_path) as img:
            width, height = img.size
            long_side = max(width, height)
            if long_side <= max_long_side:
                with open(img_path, 'rb') as f:
                    return io.BytesIO(f.read())
            scale = max_long_side / long_side
            new_width = int(width * scale)
            new_height = int(height * scale)
            resized = img.resize((new_width, new_height), Image.LANCZOS)
            output = io.BytesIO()
            fmt = img.format or 'JPEG'
            if fmt.upper() == 'JPG':
                fmt = 'JPEG'
            save_kwargs = {}
            if fmt.upper() == 'JPEG':
                save_kwargs['quality'] = 85
                save_kwargs['optimize'] = True
            resized.save(output, format=fmt, **save_kwargs)
            output.seek(0)
            return output
    except Exception:
        with open(img_path, 'rb') as f:
            return io.BytesIO(f.read())


def _get_unique_name(used_names, original_name):
    if original_name not in used_names:
        used_names.add(original_name)
        return original_name
    base, ext = os.path.splitext(original_name)
    counter = 1
    while True:
        candidate = f"{base}_{counter}{ext}"
        if candidate not in used_names:
            used_names.add(candidate)
            return candidate
        counter += 1


def process_export_job(app_instance, job_id):
    with app_instance.app_context():
        job = ExportJob.query.get(job_id)
        if not job:
            return
        try:
            job.status = ExportJob.STATUS_PROCESSING
            db.session.commit()

            album = Album.query.get(job.album_id)
            if not album:
                raise Exception("相册不存在")

            photos = album.photos
            job.total_photos = len(photos)
            db.session.commit()

            options = job.options or {}
            compress_web = options.get('compress_web', False)
            include_manifest = options.get('include_manifest', False)
            group_by_date = options.get('group_by_date', False)

            used_names = set()
            manifest_entries = []

            today_str = datetime.now().strftime('%Y%m%d')
            safe_title = re.sub(r'[\\/:*?"<>|]', '_', album.title)
            zip_basename = f"{safe_title}_{today_str}.zip"
            zip_fullname = f"{uuid.uuid4().hex}_{zip_basename}"
            zip_path = os.path.join(EXPORT_FOLDER, zip_fullname)

            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                for idx, photo in enumerate(photos):
                    img_path = os.path.join(UPLOAD_FOLDER, photo.filename)
                    if not os.path.isfile(img_path):
                        job.processed_photos = idx + 1
                        job.progress = int((idx + 1) / max(1, job.total_photos) * 100)
                        db.session.commit()
                        continue

                    display_name = _get_unique_name(used_names, photo.original_filename or f"photo_{photo.id}")

                    if group_by_date:
                        date_obj = photo.uploaded_at or datetime.utcnow()
                        date_folder = date_obj.strftime('%Y-%m-%d')
                        arcname = f"{date_folder}/{display_name}"
                    else:
                        arcname = display_name

                    if compress_web:
                        img_data = _resize_for_web(img_path)
                        zf.writestr(arcname, img_data.getvalue())
                    else:
                        zf.write(img_path, arcname)

                    if include_manifest:
                        exif_summary = {}
                        if photo.camera_model:
                            exif_summary['camera_model'] = photo.camera_model
                        if photo.taken_at:
                            exif_summary['taken_at'] = photo.taken_at.strftime('%Y-%m-%d %H:%M:%S')
                        if photo.gps_latitude is not None and photo.gps_longitude is not None:
                            exif_summary['gps'] = {
                                'latitude': photo.gps_latitude,
                                'longitude': photo.gps_longitude
                            }
                        manifest_entries.append({
                            'filename': display_name,
                            'original_filename': photo.original_filename,
                            'uploaded_at': photo.uploaded_at.strftime('%Y-%m-%d %H:%M:%S') if photo.uploaded_at else None,
                            'exif': exif_summary if exif_summary else None
                        })

                    job.processed_photos = idx + 1
                    job.progress = int((idx + 1) / max(1, job.total_photos) * 100)
                    if idx % 5 == 0 or idx == job.total_photos - 1:
                        db.session.commit()

                if include_manifest and manifest_entries:
                    manifest_data = {
                        'album_title': album.title,
                        'exported_at': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
                        'total_photos': len(manifest_entries),
                        'files': manifest_entries
                    }
                    zf.writestr('manifest.json', json.dumps(manifest_data, ensure_ascii=False, indent=2))

            file_size = os.path.getsize(zip_path)
            job.zip_filename = zip_fullname
            job.file_size = file_size
            job.status = ExportJob.STATUS_COMPLETED
            job.completed_at = datetime.utcnow()
            job.expires_at = datetime.utcnow() + timedelta(days=EXPORT_EXPIRE_DAYS)
            job.progress = 100
            db.session.commit()

            history = DownloadHistory(
                album_id=album.id,
                export_job_id=job.id,
                album_title=album.title,
                zip_filename=zip_fullname,
                file_size=file_size,
                photo_count=job.total_photos,
                options=options,
                ip_address=get_client_ip()
            )
            db.session.add(history)
            db.session.commit()

            log_operation('export_zip',
                          f'导出相册「{album.title}」ZIP（{job.total_photos} 张，{format_bytes_human(file_size)}）',
                          resource_type='album', resource_id=album.id,
                          after_data={'photo_count': job.total_photos, 'file_size': file_size, 'options': options})

            dispatch_notification(
                type=Notification.TYPE_EXPORT_ZIP,
                title=f'ZIP 导出完成',
                content=f'相册「{album.title}」已成功导出，共 {job.total_photos} 张照片',
                status=Notification.STATUS_SUCCESS,
                task_id=f'export_{job.id}',
                data={
                    'job_id': job.id,
                    'album_id': album.id,
                    'album_title': album.title,
                    'photo_count': job.total_photos,
                    'file_size': file_size,
                    'file_size_human': format_bytes_human(file_size),
                    'download_url': f'/export/{job.id}/download',
                },
            )

        except Exception as e:
            job.status = ExportJob.STATUS_FAILED
            job.error_message = str(e) + "\n" + traceback.format_exc()[-500:]
            db.session.commit()

            album = Album.query.get(job.album_id) if job else None
            dispatch_notification(
                type=Notification.TYPE_EXPORT_ZIP,
                title=f'ZIP 导出失败',
                content=f'相册「{album.title if album else "未知"}」导出失败：{str(e)}',
                status=Notification.STATUS_FAILED,
                task_id=f'export_{job.id}' if job else None,
                data={
                    'job_id': job.id if job else None,
                    'album_id': album.id if album else None,
                    'album_title': album.title if album else None,
                    'error': str(e),
                },
            )
