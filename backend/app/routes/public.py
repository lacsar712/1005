from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, url_for, jsonify
from sqlalchemy import or_, func

from ..db import db, Album, Photo, Tag, Comment, Trip
from ..utils import (
    get_config_value,
    fuzzy_match,
    highlight_keywords,
)

public_bp = Blueprint('public', __name__)


@public_bp.route('/', endpoint='index')
def index():
    sort_by = get_config_value('album_sort_by')
    query = Album.query
    if sort_by == 'photo_count':
        albums = query.outerjoin(Photo).group_by(Album.id).order_by(func.count(Photo.id).desc()).all()
    elif sort_by == 'name':
        albums = query.order_by(Album.title.asc()).all()
    else:
        albums = query.order_by(Album.created_at.desc()).all()
    tags = Tag.query.order_by(Tag.name).all()

    total_albums = Album.query.count()
    total_photos = Photo.query.count()
    total_tags = Tag.query.count()
    total_comments = Comment.query.count()
    site_stats = {
        'total_albums': total_albums,
        'total_photos': total_photos,
        'total_tags': total_tags,
        'total_comments': total_comments
    }

    return render_template('index.html', albums=albums, tags=tags, site_stats=site_stats)


@public_bp.route('/album/<int:album_id>', endpoint='album_detail')
def album_detail(album_id):
    album = Album.query.get_or_404(album_id)
    all_tags = Tag.query.order_by(Tag.name).all()
    return render_template('album.html', album=album, all_tags=all_tags)


@public_bp.route('/tags', endpoint='browse_tags')
def browse_tags():
    tags = Tag.query.order_by(Tag.name).all()
    tag_photo_counts = {}
    for tag in tags:
        tag_photo_counts[tag.id] = tag.photos.count()
    return render_template('tag_browse.html', tags=tags, tag_photo_counts=tag_photo_counts)


@public_bp.route('/tag/<int:tag_id>', endpoint='view_tag')
def view_tag(tag_id):
    tag = Tag.query.get_or_404(tag_id)
    photos = tag.photos.all()
    photo_data = []
    for photo in photos:
        photo_data.append({
            'photo': photo,
            'album': Album.query.get(photo.album_id)
        })
    all_tags = Tag.query.order_by(Tag.name).all()
    return render_template('tag_browse.html', tags=all_tags, current_tag=tag, photo_data=photo_data, tag_photo_counts={t.id: t.photos.count() for t in all_tags})


@public_bp.route('/search', endpoint='search')
def search():
    query = request.args.get('q', '').strip()
    filter_album_id = request.args.get('album_id', type=int)
    date_from = request.args.get('date_from', '').strip()
    date_to = request.args.get('date_to', '').strip()
    filter_format = request.args.get('format', '').strip()
    filter_gps = request.args.get('has_gps', '').strip()

    matched_albums = []
    matched_photos = []

    all_albums = Album.query.order_by(Album.title.asc()).all()
    all_formats = sorted(set(
        f for f in db.session.query(Photo.image_format).distinct().all()
        if f and f[0]
    ), key=lambda x: x[0].lower())
    all_formats = [f[0] for f in all_formats]

    if query:
        albums_raw = Album.query.all()
        for album in albums_raw:
            text_parts = [album.title or '', album.description or '']
            if any(fuzzy_match(query, t) for t in text_parts):
                matched_albums.append(album)

        photos_raw = Photo.query.all()
        for photo in photos_raw:
            tag_names = ' '.join([t.name for t in photo.tags.all()])
            taken_at_str = photo.taken_at.strftime('%Y-%m-%d %H:%M:%S') if photo.taken_at else ''
            text_parts = [
                photo.original_filename or '',
                photo.description or '',
                photo.camera_model or '',
                taken_at_str,
                tag_names,
            ]
            if any(fuzzy_match(query, t) for t in text_parts):
                matched_photos.append(photo)

        if filter_album_id:
            matched_photos = [p for p in matched_photos if p.album_id == filter_album_id]

        if date_from:
            try:
                dt_from = datetime.strptime(date_from, '%Y-%m-%d')
                matched_photos = [
                    p for p in matched_photos
                    if (p.taken_at or p.uploaded_at) >= dt_from
                ]
            except ValueError:
                pass

        if date_to:
            try:
                dt_to = datetime.strptime(date_to, '%Y-%m-%d') + timedelta(days=1)
                matched_photos = [
                    p for p in matched_photos
                    if (p.taken_at or p.uploaded_at) < dt_to
                ]
            except ValueError:
                pass

        if filter_format:
            matched_photos = [p for p in matched_photos if p.image_format == filter_format]

        if filter_gps == 'yes':
            matched_photos = [p for p in matched_photos if p.gps_latitude is not None and p.gps_longitude is not None]
        elif filter_gps == 'no':
            matched_photos = [p for p in matched_photos if p.gps_latitude is None or p.gps_longitude is None]

    matched_albums_data = []
    for album in matched_albums:
        matched_albums_data.append({
            'id': album.id,
            'title': highlight_keywords(album.title or '', query),
            'title_raw': album.title or '',
            'description': highlight_keywords(album.description or '', query),
            'description_raw': album.description or '',
            'photo_count': len(album.photos),
            'cover_photo': album.photos[-1] if album.photos else None,
            'url': url_for('album_detail', album_id=album.id),
            'created_at': album.created_at,
        })

    matched_photos_data = []
    for photo in matched_photos:
        tag_names_html = ', '.join([
            highlight_keywords(t.name, query) for t in photo.tags.all()
        ])
        taken_at = photo.taken_at or photo.uploaded_at
        taken_at_str = taken_at.strftime('%Y-%m-%d %H:%M:%S') if taken_at else ''
        matched_photos_data.append({
            'id': photo.id,
            'original_filename': highlight_keywords(photo.original_filename or '', query),
            'original_filename_raw': photo.original_filename or '',
            'description': highlight_keywords(photo.description or '', query),
            'description_raw': photo.description or '',
            'camera_model': highlight_keywords(photo.camera_model or '', query),
            'camera_model_raw': photo.camera_model or '',
            'taken_at': highlight_keywords(taken_at_str, query),
            'taken_at_raw': taken_at_str,
            'has_gps': photo.gps_latitude is not None and photo.gps_longitude is not None,
            'image_format': photo.image_format or '',
            'tag_names_html': tag_names_html,
            'album': Album.query.get(photo.album_id),
            'album_id': photo.album_id,
            'filename': photo.filename,
            'url': url_for('album_detail', album_id=photo.album_id),
        })

    active_filters = {}
    if filter_album_id:
        active_filters['album_id'] = filter_album_id
    if date_from:
        active_filters['date_from'] = date_from
    if date_to:
        active_filters['date_to'] = date_to
    if filter_format:
        active_filters['format'] = filter_format
    if filter_gps:
        active_filters['has_gps'] = filter_gps

    return render_template(
        'search.html',
        query=query,
        matched_albums=matched_albums_data,
        matched_photos=matched_photos_data,
        all_albums=all_albums,
        all_formats=all_formats,
        filter_album_id=filter_album_id,
        date_from=date_from,
        date_to=date_to,
        filter_format=filter_format,
        filter_gps=filter_gps,
        active_filters=active_filters,
        total_count=len(matched_albums_data) + len(matched_photos_data),
    )


@public_bp.route('/map', endpoint='map_view')
def map_view():
    return render_template('map.html')


@public_bp.route('/photo/<int:photo_id>/location', methods=['GET'], endpoint='get_photo_location')
def get_photo_location(photo_id):
    photo = Photo.query.get_or_404(photo_id)
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
            'manual': photo.location_manual,
            'has_gps': photo.has_gps,
        }
    })


def comment_to_dict(comment):
    return {
        'id': comment.id,
        'photo_id': comment.photo_id,
        'nickname': comment.nickname,
        'content': comment.content,
        'created_at': comment.created_at.strftime('%Y-%m-%d %H:%M:%S')
    }


@public_bp.route('/api/photo/<int:photo_id>/comments', methods=['GET'], endpoint='get_photo_comments')
def get_photo_comments(photo_id):
    photo = Photo.query.get_or_404(photo_id)
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 5, type=int)
    offset = (page - 1) * per_page

    query = Comment.query.filter_by(photo_id=photo_id).order_by(Comment.created_at.desc())
    total = query.count()
    comments = query.offset(offset).limit(per_page).all()

    return jsonify({
        'success': True,
        'comments': [comment_to_dict(c) for c in comments],
        'total': total,
        'page': page,
        'per_page': per_page,
        'has_more': (offset + len(comments)) < total
    })


@public_bp.route('/api/photo/<int:photo_id>/comments', methods=['POST'], endpoint='add_photo_comment')
def add_photo_comment(photo_id):
    photo = Photo.query.get_or_404(photo_id)
    data = request.get_json() if request.is_json else request.form

    nickname = (data.get('nickname') or '').strip() or '匿名访客'
    content = (data.get('content') or '').strip()

    if not content:
        return jsonify({'success': False, 'message': '评论内容不能为空'}), 400

    if len(content) > 500:
        return jsonify({'success': False, 'message': '评论内容不能超过500字'}), 400

    if len(nickname) > 50:
        return jsonify({'success': False, 'message': '昵称不能超过50字'}), 400

    new_comment = Comment(
        photo_id=photo_id,
        nickname=nickname,
        content=content
    )
    db.session.add(new_comment)
    db.session.commit()

    return jsonify({
        'success': True,
        'comment': comment_to_dict(new_comment)
    })


@public_bp.route('/api/search/autocomplete', endpoint='api_search_autocomplete')
def api_search_autocomplete():
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify({'success': True, 'suggestions': []})
    q_lower = query.lower()
    albums = Album.query.all()
    suggestions = []
    for album in albums:
        title = album.title or ''
        if title.lower().startswith(q_lower) or q_lower in title.lower():
            suggestions.append({
                'id': album.id,
                'title': title,
                'url': url_for('album_detail', album_id=album.id)
            })
        if len(suggestions) >= 8:
            break
    return jsonify({'success': True, 'suggestions': suggestions})


@public_bp.route('/api/map/photos', endpoint='api_map_photos')
def api_map_photos():
    photos = Photo.query.filter(
        Photo.gps_latitude.isnot(None),
        Photo.gps_longitude.isnot(None)
    ).all()
    result = []
    for p in photos:
        album = Album.query.get(p.album_id)
        taken_at = p.taken_at or p.uploaded_at
        result.append({
            'id': p.id,
            'latitude': p.gps_latitude,
            'longitude': p.gps_longitude,
            'original_filename': p.original_filename,
            'thumbnail_url': url_for('static', filename='uploads/' + p.filename),
            'address': p.location_display,
            'city': p.location_city,
            'district': p.location_district,
            'album_id': p.album_id,
            'album_title': album.title if album else '',
            'album_url': url_for('album_detail', album_id=p.album_id),
            'taken_at': taken_at.strftime('%Y-%m-%d %H:%M:%S') if taken_at else None,
            'trip_id': p.trip_id,
        })
    return jsonify({'success': True, 'photos': result})


@public_bp.route('/api/map/trips', endpoint='api_map_trips')
def api_map_trips():
    trips = Trip.query.order_by(Trip.start_time.desc().nullslast()).all()
    result = [t.to_dict() for t in trips]
    return jsonify({'success': True, 'trips': result})
