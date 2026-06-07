import io
import csv
import os
import re
import threading
import uuid
from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, make_response, send_file, current_app, jsonify
from flask_login import login_required, login_user, logout_user, current_user
from werkzeug.utils import secure_filename
from sqlalchemy import or_

from ..db import db, Album, Photo, Tag, SiteConfig, OperationLog, ExportJob, DownloadHistory, Notification, WebhookConfig, format_bytes_human
from ..services import NotificationService, AggregationService, WebhookService, CleanupService
from ..utils import (
    ADMIN_USERNAME,
    ADMIN_PASSWORD,
    User,
    log_operation,
    model_snapshot,
    diff_snapshots,
    detect_anomaly,
    dispatch_notification,
    get_site_config,
    get_config_value,
    set_config_value,
    allowed_file,
    extract_exif,
    get_image_format,
    process_uploaded_locations_async,
    infer_trips,
    collect_dashboard_stats,
    process_export_job,
)

admin_bp = Blueprint('admin', __name__)


@admin_bp.route('/admin/login', methods=['GET', 'POST'], endpoint='login')
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            user = User(id='1')
            login_user(user)
            log_operation('auth_login', '管理员登录成功')
            flash('登录成功', 'success')
            return redirect(url_for('index'))
        else:
            flash('用户名或密码错误', 'error')
    return render_template('login.html')


@admin_bp.route('/admin/logout', endpoint='logout')
@login_required
def logout():
    log_operation('auth_logout', '管理员登出')
    logout_user()
    flash('已退出登录', 'info')
    return redirect(url_for('index'))


@admin_bp.route('/album/create', methods=['GET', 'POST'], endpoint='create_album')
@login_required
def create_album():
    if request.method == 'POST':
        title = request.form.get('title')
        description = request.form.get('description')
        if not title:
            flash('相册名称不能为空', 'error')
        else:
            new_album = Album(title=title, description=description)
            db.session.add(new_album)
            db.session.flush()
            after_snap = model_snapshot(new_album)
            log_operation('album_create', f'创建相册「{title}」',
                          resource_type='album', resource_id=new_album.id,
                          after_data=after_snap)
            db.session.commit()
            flash('相册创建成功', 'success')
            return redirect(url_for('index'))
    return render_template('create_album.html')


@admin_bp.route('/album/delete/<int:album_id>', endpoint='delete_album')
@login_required
def delete_album(album_id):
    album = Album.query.get_or_404(album_id)
    before_snap = model_snapshot(album)
    photo_count = len(album.photos)
    album_title = album.title
    parent_log = log_operation('album_delete',
                               f'删除相册「{album.title}」（含 {photo_count} 张照片）',
                               resource_type='album', resource_id=album.id,
                               before_data=before_snap, commit=False)
    if photo_count > 1:
        batch_parent, _ = AggregationService.create_batch_parent(
            type=Notification.TYPE_DELETE_BATCH,
            title=f'批量删除 {photo_count} 张照片',
            content=f'随相册「{album_title}」一起删除',
            data={'album_id': album.id, 'album_title': album_title, 'total': photo_count},
        )
    for idx, photo in enumerate(album.photos):
        photo_before = model_snapshot(photo)
        log_operation('photo_delete',
                      f'删除照片「{photo.original_filename}」（随相册删除）',
                      resource_type='photo', resource_id=photo.id,
                      before_data=photo_before, parent_id=parent_log.id, commit=False)
        if photo_count > 1:
            AggregationService.add_child(
                parent_id=batch_parent.id,
                type=Notification.TYPE_DELETE,
                title=f'照片已删除',
                content=f'「{photo.original_filename}」已被删除',
                status=Notification.STATUS_SUCCESS,
                data={'photo_id': photo.id, 'original_filename': photo.original_filename},
                commit=False,
            )
        try:
            os.remove(os.path.join(current_app.config['UPLOAD_FOLDER'], photo.filename))
        except OSError:
            pass
    db.session.delete(album)
    db.session.commit()
    if photo_count > 1:
        AggregationService.finalize_batch(
            batch_parent.id,
            status=Notification.STATUS_SUCCESS,
            data={'total': photo_count, 'success': photo_count, 'failed': 0,
                  'album_id': album.id, 'album_title': album_title},
        )
        WebhookService.dispatch(batch_parent)
        CleanupService.cleanup_if_needed()
    elif photo_count == 1:
        dispatch_notification(
            type=Notification.TYPE_DELETE,
            title=f'相册已删除',
            content=f'相册「{album_title}」（含 1 张照片）已删除',
            data={'album_id': album.id, 'album_title': album_title, 'photo_count': photo_count},
        )
    else:
        dispatch_notification(
            type=Notification.TYPE_DELETE,
            title=f'相册已删除',
            content=f'空相册「{album_title}」已删除',
            data={'album_id': album.id, 'album_title': album_title},
        )
    flash('相册已删除', 'success')
    return redirect(url_for('index'))


@admin_bp.route('/upload/<int:album_id>', methods=['GET', 'POST'], endpoint='upload_photo')
@login_required
def upload_photo(album_id):
    album = Album.query.get_or_404(album_id)
    if request.method == 'POST':
        if 'photo' not in request.files:
            flash('没有文件被上传', 'error')
            return redirect(request.url)

        files = request.files.getlist('photo')
        uploaded_count = 0

        max_size_bytes = int(get_config_value('max_upload_size_mb')) * 1024 * 1024

        uploaded_photos = []

        for file in files:
            if file.filename == '':
                continue

            if file and allowed_file(file.filename):
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

                saved_path = os.path.join(current_app.config['UPLOAD_FOLDER'], unique_filename)
                file.save(saved_path)

                exif_info = extract_exif(saved_path)
                img_format = get_image_format(original_filename)

                new_photo = Photo(
                    filename=unique_filename,
                    original_filename=original_filename,
                    album_id=album.id,
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

        if uploaded_count > 0:
            db.session.flush()
            if uploaded_count == 1:
                p = uploaded_photos[0]
                log_operation('photo_upload',
                              f'上传照片「{p.original_filename}」至相册「{album.title}」',
                              resource_type='photo', resource_id=p.id,
                              after_data=model_snapshot(p))
                dispatch_notification(
                    type=Notification.TYPE_UPLOAD,
                    title=f'照片上传成功',
                    content=f'「{p.original_filename}」已上传至相册「{album.title}」',
                    data={'photo_id': p.id, 'album_id': album.id, 'album_title': album.title},
                )
            else:
                is_anomaly = detect_anomaly('photo_upload', count=uploaded_count)
                parent_log = log_operation('photo_upload',
                                           f'批量上传 {uploaded_count} 张照片至相册「{album.title}」',
                                           resource_type='album', resource_id=album.id,
                                           is_anomaly=is_anomaly, commit=False)
                batch_parent, task_id = AggregationService.create_batch_parent(
                    type=Notification.TYPE_UPLOAD_BATCH,
                    title=f'批量上传 {uploaded_count} 张照片',
                    content=f'上传至相册「{album.title}」',
                    data={'album_id': album.id, 'album_title': album.title, 'total': uploaded_count},
                )
                for idx, p in enumerate(uploaded_photos):
                    log_operation('photo_upload',
                                  f'上传照片「{p.original_filename}」',
                                  resource_type='photo', resource_id=p.id,
                                  after_data=model_snapshot(p),
                                  parent_id=parent_log.id, commit=False)
                    AggregationService.add_child(
                        parent_id=batch_parent.id,
                        type=Notification.TYPE_UPLOAD,
                        title=f'照片上传成功',
                        content=f'「{p.original_filename}」上传完成',
                        status=Notification.STATUS_SUCCESS,
                        data={'photo_id': p.id, 'original_filename': p.original_filename},
                        commit=False,
                    )
                AggregationService.finalize_batch(
                    batch_parent.id,
                    status=Notification.STATUS_SUCCESS,
                    data={'total': uploaded_count, 'success': uploaded_count, 'failed': 0,
                          'album_id': album.id, 'album_title': album.title},
                )
                WebhookService.dispatch(batch_parent)
                CleanupService.cleanup_if_needed()
            db.session.commit()

            uploaded_ids = [p.id for p in uploaded_photos]
            loc_thread = threading.Thread(
                target=process_uploaded_locations_async,
                args=(current_app._get_current_object(), uploaded_ids),
                daemon=True
            )
            loc_thread.start()

            flash(f'成功上传 {uploaded_count} 张图片', 'success')
            return redirect(url_for('album_detail', album_id=album.id))
        else:
            flash('未选择有效文件或格式不支持', 'error')

    max_size_mb = int(get_config_value('max_upload_size_mb'))
    return render_template('upload.html', album=album, max_upload_size_mb=max_size_mb)


@admin_bp.route('/photo/delete/<int:photo_id>', endpoint='delete_photo')
@login_required
def delete_photo(photo_id):
    photo = Photo.query.get_or_404(photo_id)
    album_id = photo.album_id
    before_snap = model_snapshot(photo)
    original_filename = photo.original_filename
    log_operation('photo_delete',
                  f'删除照片「{photo.original_filename}」',
                  resource_type='photo', resource_id=photo.id,
                  before_data=before_snap)
    try:
        os.remove(os.path.join(current_app.config['UPLOAD_FOLDER'], photo.filename))
    except OSError:
        pass
    db.session.delete(photo)
    db.session.commit()
    dispatch_notification(
        type=Notification.TYPE_DELETE,
        title=f'照片已删除',
        content=f'「{original_filename}」已被删除',
        data={'photo_id': photo_id, 'original_filename': original_filename},
    )
    flash('图片已删除', 'success')
    return redirect(url_for('album_detail', album_id=album_id))


@admin_bp.route('/admin/tags', methods=['GET', 'POST'], endpoint='manage_tags')
@login_required
def manage_tags():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if not name:
            flash('标签名称不能为空', 'error')
        elif Tag.query.filter_by(name=name).first():
            flash('标签名称已存在，请使用其他名称', 'error')
        else:
            new_tag = Tag(name=name)
            db.session.add(new_tag)
            db.session.flush()
            log_operation('tag_create', f'创建标签「{name}」',
                          resource_type='tag', resource_id=new_tag.id,
                          after_data=model_snapshot(new_tag))
            db.session.commit()
            flash(f'标签「{name}」创建成功', 'success')
        return redirect(url_for('manage_tags'))
    tags = Tag.query.order_by(Tag.created_at.desc()).all()
    tag_photo_counts = {}
    for tag in tags:
        tag_photo_counts[tag.id] = tag.photos.count()
    return render_template('tags.html', tags=tags, tag_photo_counts=tag_photo_counts)


@admin_bp.route('/admin/tag/rename/<int:tag_id>', methods=['POST'], endpoint='rename_tag')
@login_required
def rename_tag(tag_id):
    tag = Tag.query.get_or_404(tag_id)
    new_name = request.form.get('name', '').strip()
    if not new_name:
        flash('标签名称不能为空', 'error')
    elif Tag.query.filter(Tag.name == new_name, Tag.id != tag_id).first():
        flash('标签名称已存在，请使用其他名称', 'error')
    else:
        old_name = tag.name
        before_snap = model_snapshot(tag)
        tag.name = new_name
        after_snap = model_snapshot(tag)
        log_operation('tag_rename',
                      f'标签从「{old_name}」重命名为「{new_name}」',
                      resource_type='tag', resource_id=tag.id,
                      before_data=before_snap, after_data=after_snap)
        db.session.commit()
        flash(f'标签已从「{old_name}」重命名为「{new_name}」', 'success')
    return redirect(url_for('manage_tags'))


@admin_bp.route('/admin/tag/delete/<int:tag_id>', endpoint='delete_tag')
@login_required
def delete_tag(tag_id):
    tag = Tag.query.get_or_404(tag_id)
    tag_name = tag.name
    before_snap = model_snapshot(tag)
    log_operation('tag_delete',
                  f'删除标签「{tag_name}」',
                  resource_type='tag', resource_id=tag.id,
                  before_data=before_snap)
    db.session.delete(tag)
    db.session.commit()
    flash(f'标签「{tag_name}」已删除（关联照片未受影响）', 'success')
    return redirect(url_for('manage_tags'))


@admin_bp.route('/photo/<int:photo_id>/tags', methods=['POST'], endpoint='set_photo_tags')
@login_required
def set_photo_tags(photo_id):
    photo = Photo.query.get_or_404(photo_id)
    old_tag_ids = sorted([t.id for t in photo.tags.all()])
    old_tag_names = [t.name for t in photo.tags.all()]
    tag_ids = request.form.getlist('tag_ids')
    tag_ids = [int(tid) for tid in tag_ids if tid.isdigit()]
    selected_tags = Tag.query.filter(Tag.id.in_(tag_ids)).all() if tag_ids else []
    new_tag_names = [t.name for t in selected_tags]
    before_data = {'photo_id': photo.id, 'tag_ids': old_tag_ids, 'tag_names': old_tag_names}
    after_data = {'photo_id': photo.id, 'tag_ids': sorted(tag_ids), 'tag_names': new_tag_names}
    photo.tags = selected_tags
    log_operation('photo_tag_update',
                  f'更新照片「{photo.original_filename}」标签：{", ".join(old_tag_names) or "无"} → {", ".join(new_tag_names) or "无"}',
                  resource_type='photo', resource_id=photo.id,
                  before_data=before_data, after_data=after_data)
    db.session.commit()
    flash('标签已更新', 'success')
    return redirect(url_for('album_detail', album_id=photo.album_id))


@admin_bp.route('/admin/settings', methods=['GET'], endpoint='site_settings')
@login_required
def site_settings():
    config = get_site_config()
    return render_template('settings.html', config=config)


@admin_bp.route('/admin/settings', methods=['POST'], endpoint='save_site_settings')
@login_required
def save_site_settings():
    site_name = request.form.get('site_name', '').strip()
    welcome_message = request.form.get('welcome_message', '').strip()
    copyright_text = request.form.get('copyright_text', '').strip()
    contact_email = request.form.get('contact_email', '').strip()
    max_upload_size_mb = request.form.get('max_upload_size_mb', '5')
    album_sort_by = request.form.get('album_sort_by', 'created_at')
    show_site_stats = request.form.get('show_site_stats', 'false')

    if not site_name:
        flash('站点名称不能为空', 'error')
        return redirect(url_for('site_settings'))

    try:
        size_mb = int(max_upload_size_mb)
        if size_mb < 1 or size_mb > 10:
            flash('上传大小限制必须在 1-10 MB 之间', 'error')
            return redirect(url_for('site_settings'))
    except (ValueError, TypeError):
        flash('上传大小限制格式无效', 'error')
        return redirect(url_for('site_settings'))

    before_config = get_site_config()
    set_config_value('site_name', site_name)
    set_config_value('welcome_message', welcome_message)
    set_config_value('copyright_text', copyright_text)
    set_config_value('contact_email', contact_email)
    set_config_value('max_upload_size_mb', str(size_mb))
    set_config_value('album_sort_by', album_sort_by)
    set_config_value('show_site_stats', show_site_stats)
    after_config = get_site_config()

    changed_fields = []
    for k in before_config:
        if str(before_config.get(k)) != str(after_config.get(k)):
            changed_fields.append(k)

    if changed_fields:
        log_operation('settings_update',
                      f'更新站点设置：{", ".join(changed_fields)}',
                      before_data={k: before_config.get(k) for k in changed_fields},
                      after_data={k: after_config.get(k) for k in changed_fields})

    current_app.config['MAX_CONTENT_LENGTH'] = size_mb * 1024 * 1024

    flash('站点设置已保存', 'success')
    return redirect(url_for('site_settings'))


def build_log_query():
    operation_types = request.args.getlist('operation_type')
    keyword = request.args.get('keyword', '').strip()
    date_from = request.args.get('date_from', '').strip()
    date_to = request.args.get('date_to', '').strip()

    query = OperationLog.query.filter(OperationLog.parent_id.is_(None))

    if operation_types:
        query = query.filter(OperationLog.operation_type.in_(operation_types))

    if keyword:
        like = f'%{keyword}%'
        query = query.filter(or_(
            OperationLog.summary.like(like),
            OperationLog.resource_type.like(like),
            OperationLog.resource_id.like(like),
        ))

    if date_from:
        try:
            dt_from = datetime.strptime(date_from, '%Y-%m-%d')
            query = query.filter(OperationLog.created_at >= dt_from)
        except ValueError:
            pass

    if date_to:
        try:
            dt_to = datetime.strptime(date_to, '%Y-%m-%d') + timedelta(days=1)
            query = query.filter(OperationLog.created_at < dt_to)
        except ValueError:
            pass

    return query


@admin_bp.route('/admin/logs', endpoint='operation_logs')
@login_required
def operation_logs():
    page = request.args.get('page', 1, type=int)
    per_page = 20
    query = build_log_query().order_by(OperationLog.created_at.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    total = pagination.total
    logs = pagination.items

    operation_types_list = sorted(OperationLog.OPERATION_TYPES.items(), key=lambda x: x[1])
    selected_types = request.args.getlist('operation_type')

    return render_template('operation_logs.html',
                           logs=logs,
                           pagination=pagination,
                           total=total,
                           operation_types=operation_types_list,
                           selected_types=selected_types,
                           keyword=request.args.get('keyword', ''),
                           date_from=request.args.get('date_from', ''),
                           date_to=request.args.get('date_to', ''))


@admin_bp.route('/admin/logs/export', endpoint='export_logs_csv')
@login_required
def export_logs_csv():
    query = build_log_query().order_by(OperationLog.created_at.desc())
    logs = query.all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['操作时间', '操作类型', '摘要', '资源类型', '资源ID', 'IP地址', '是否异常', '变更快照'])

    def flatten_log(log, depth=0):
        rows = []
        prefix = '  ' * depth
        rows.append([
            log.created_at.strftime('%Y-%m-%d %H:%M:%S') if log.created_at else '',
            log.operation_type_label,
            prefix + log.summary,
            log.resource_type or '',
            log.resource_id or '',
            log.ip_address or '',
            '是' if log.is_anomaly else '否',
            '',
        ])
        if log.before_data or log.after_data:
            diffs = diff_snapshots(log.before_data or {}, log.after_data or {})
            for d in diffs:
                rows.append(['', '', '', '', '', '', '',
                             f"{d['field']}: {d['before']} → {d['after']}"])
        for child in log.children.all():
            rows.extend(flatten_log(child, depth + 1))
        return rows

    for log in logs:
        for row in flatten_log(log):
            writer.writerow(row)

    output.seek(0)
    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv; charset=utf-8-sig'
    filename = f"operation_logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    response.headers['Content-Disposition'] = f'attachment; filename={filename}'
    return response


@admin_bp.route('/admin/dashboard', endpoint='admin_dashboard')
@login_required
def admin_dashboard():
    days = request.args.get('days', 7, type=int)
    if days not in (7, 30):
        days = 7
    stats = collect_dashboard_stats(days=days)
    return render_template('dashboard.html', stats=stats, initial_days=days)


@admin_bp.route('/admin/dashboard/print', endpoint='admin_dashboard_print')
@login_required
def admin_dashboard_print():
    days = request.args.get('days', 7, type=int)
    if days not in (7, 30):
        days = 7
    stats = collect_dashboard_stats(days=days)
    config = get_site_config()
    return render_template('dashboard_print.html', stats=stats, days=days, site_config=config, now=datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'))


@admin_bp.route('/album/<int:album_id>/export', methods=['POST'], endpoint='create_export_job')
@login_required
def create_export_job(album_id):
    album = Album.query.get_or_404(album_id)
    if not album.photos:
        return jsonify({'success': False, 'message': '相册为空，无法导出'}), 400

    data = request.get_json() if request.is_json else request.form
    options = {
        'compress_web': bool(data.get('compress_web', False)),
        'include_manifest': bool(data.get('include_manifest', False)),
        'group_by_date': bool(data.get('group_by_date', False)),
    }

    job = ExportJob(
        album_id=album.id,
        status=ExportJob.STATUS_PENDING,
        progress=0,
        total_photos=len(album.photos),
        processed_photos=0,
        options=options,
    )
    db.session.add(job)
    db.session.commit()

    thread = threading.Thread(target=process_export_job, args=(current_app._get_current_object(), job.id), daemon=True)
    thread.start()

    return jsonify({'success': True, 'job': job.to_dict()})


@admin_bp.route('/export/<int:job_id>/status', endpoint='export_status')
@login_required
def export_status(job_id):
    job = ExportJob.query.get_or_404(job_id)
    return jsonify({'success': True, 'job': job.to_dict()})


@admin_bp.route('/export/<int:job_id>/download', endpoint='download_export')
@login_required
def download_export(job_id):
    from ..utils.constants import EXPORT_FOLDER
    job = ExportJob.query.get_or_404(job_id)
    if not job.is_ready:
        abort(404)

    zip_path = os.path.join(EXPORT_FOLDER, job.zip_filename)
    if not os.path.isfile(zip_path):
        abort(404)

    album = Album.query.get(job.album_id)
    safe_title = re.sub(r'[\\/:*?"<>|]', '_', album.title if album else 'album')
    today_str = datetime.now().strftime('%Y%m%d')
    download_name = f"{safe_title}_{today_str}.zip"

    return send_file(
        zip_path,
        as_attachment=True,
        download_name=download_name,
        mimetype='application/zip'
    )


@admin_bp.route('/admin/downloads', endpoint='download_history')
@login_required
def download_history():
    page = request.args.get('page', 1, type=int)
    per_page = 20
    query = DownloadHistory.query.order_by(DownloadHistory.created_at.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    records = pagination.items

    record_dicts = []
    for r in records:
        d = r.to_dict()
        record_dicts.append(d)

    return render_template('download_history.html',
                           records=record_dicts,
                           pagination=pagination,
                           total=pagination.total)


@admin_bp.route('/admin/downloads/<int:history_id>/download', endpoint='redownload_from_history')
@login_required
def redownload_from_history(history_id):
    from ..utils.constants import EXPORT_FOLDER
    record = DownloadHistory.query.get_or_404(history_id)
    if not record.file_exists:
        flash('ZIP 文件已过期或被删除', 'error')
        return redirect(url_for('download_history'))

    zip_path = os.path.join(EXPORT_FOLDER, record.zip_filename)
    safe_title = re.sub(r'[\\/:*?"<>|]', '_', record.album_title or 'album')
    today_str = (record.created_at or datetime.now()).strftime('%Y%m%d')
    download_name = f"{safe_title}_{today_str}.zip"

    return send_file(
        zip_path,
        as_attachment=True,
        download_name=download_name,
        mimetype='application/zip'
    )


@admin_bp.route('/photo/<int:photo_id>/location', methods=['POST'], endpoint='update_photo_location')
@login_required
def update_photo_location(photo_id):
    photo = Photo.query.get_or_404(photo_id)
    data = request.get_json() if request.is_json else request.form

    before = {
        'location_country': photo.location_country,
        'location_province': photo.location_province,
        'location_city': photo.location_city,
        'location_district': photo.location_district,
        'location_address': photo.location_address,
        'gps_latitude': photo.gps_latitude,
        'gps_longitude': photo.gps_longitude,
    }

    country = (data.get('country') or '').strip() or None
    province = (data.get('province') or '').strip() or None
    city = (data.get('city') or '').strip()
    district = (data.get('district') or '').strip() or None
    address = (data.get('address') or '').strip() or None
    latitude = data.get('latitude')
    longitude = data.get('longitude')

    if not city and not address:
        return jsonify({'success': False, 'message': '至少需要填写城市或完整地址'}), 400

    photo.location_country = country
    photo.location_province = province
    photo.location_city = city or None
    photo.location_district = district
    photo.location_address = address
    photo.location_manual = True

    try:
        if latitude is not None and longitude is not None:
            photo.gps_latitude = float(latitude)
            photo.gps_longitude = float(longitude)
    except (ValueError, TypeError):
        pass

    after = {
        'location_country': photo.location_country,
        'location_province': photo.location_province,
        'location_city': photo.location_city,
        'location_district': photo.location_district,
        'location_address': photo.location_address,
        'gps_latitude': photo.gps_latitude,
        'gps_longitude': photo.gps_longitude,
    }

    log_operation('photo_location_update',
                  f'更新照片「{photo.original_filename}」地点信息',
                  resource_type='photo', resource_id=photo.id,
                  before_data=before, after_data=after)
    db.session.commit()

    t = threading.Thread(target=lambda: (
        None,
        None,
        infer_trips(photo_ids=[photo.id])
    ), daemon=True)
    t.start()

    return jsonify({
        'success': True,
        'location': {
            'country': photo.location_country,
            'province': photo.location_province,
            'city': photo.location_city,
            'district': photo.location_district,
            'address': photo.location_address,
            'latitude': photo.gps_latitude,
            'longitude': photo.gps_longitude,
            'display': photo.location_display,
        }
    })


@admin_bp.route('/notifications', endpoint='notifications_page')
@login_required
def notifications_page():
    page = request.args.get('page', 1, type=int)
    per_page = 20
    type_filter = request.args.get('type', '').strip() or None
    status_filter = request.args.get('status', '').strip() or None
    unread_only = request.args.get('unread_only', '').strip() == '1'

    pagination = NotificationService.get_list(
        page=page, per_page=per_page,
        type_filter=type_filter, status_filter=status_filter,
        unread_only=unread_only,
    )

    type_options = sorted(Notification.TYPE_LABELS.items(), key=lambda x: x[1])
    status_options = [
        (Notification.STATUS_PENDING, '处理中'),
        (Notification.STATUS_SUCCESS, '成功'),
        (Notification.STATUS_FAILED, '失败'),
        (Notification.STATUS_PARTIAL, '部分成功'),
    ]

    return render_template(
        'notifications.html',
        notifications=pagination.items,
        pagination=pagination,
        total=pagination.total,
        unread_count=NotificationService.get_unread_count(),
        type_options=type_options,
        status_options=status_options,
        current_type=type_filter or '',
        current_status=status_filter or '',
        unread_only=unread_only,
    )


@admin_bp.route('/admin/webhooks', endpoint='webhooks_page')
@login_required
def webhooks_page():
    configs = WebhookService.list_configs()
    event_type_options = sorted(WebhookConfig.EVENT_TYPES.items(), key=lambda x: x[1])
    return render_template(
        'webhooks.html',
        configs=configs,
        event_type_options=event_type_options,
    )
