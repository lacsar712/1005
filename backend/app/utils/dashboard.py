import os
from datetime import datetime, timedelta
from sqlalchemy import func

from .constants import UPLOAD_FOLDER
from ..db import db, Album, Photo


def estimate_disk_usage_bytes():
    total_bytes = 0
    try:
        for filename in os.listdir(UPLOAD_FOLDER):
            filepath = os.path.join(UPLOAD_FOLDER, filename)
            if os.path.isfile(filepath):
                total_bytes += os.path.getsize(filepath)
    except OSError:
        pass
    return total_bytes


def format_bytes(num_bytes):
    if num_bytes < 1024:
        return f"{num_bytes} B"
    elif num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f} KB"
    elif num_bytes < 1024 * 1024 * 1024:
        return f"{num_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{num_bytes / (1024 * 1024 * 1024):.2f} GB"


def get_daily_uploads(days=7, end_date=None):
    if end_date is None:
        end_date = datetime.utcnow().date()
    start_date = end_date - timedelta(days=days - 1)
    start_dt = datetime.combine(start_date, datetime.min.time())

    results = db.session.query(
        func.date(Photo.uploaded_at),
        func.count(Photo.id)
    ).filter(
        Photo.uploaded_at >= start_dt
    ).group_by(
        func.date(Photo.uploaded_at)
    ).all()

    date_counts = {str(d): 0 for d in [start_date + timedelta(days=i) for i in range(days)]}
    for date_val, count in results:
        date_counts[str(date_val)] = count

    dates = sorted(date_counts.keys())
    return {
        'labels': dates,
        'counts': [date_counts[d] for d in dates]
    }


def get_album_photo_counts(limit=15):
    results = db.session.query(
        Album.id,
        Album.title,
        func.count(Photo.id).label('photo_count')
    ).outerjoin(
        Photo, Photo.album_id == Album.id
    ).group_by(
        Album.id, Album.title
    ).order_by(
        func.count(Photo.id).desc()
    ).all()

    top_albums = []
    others_count = 0
    for idx, (album_id, title, count) in enumerate(results):
        if idx < limit:
            top_albums.append({
                'id': album_id,
                'title': title,
                'count': count
            })
        else:
            others_count += count

    if others_count > 0 or len(results) > limit:
        top_albums.append({
            'id': None,
            'title': '其他',
            'count': others_count
        })

    return top_albums


def get_format_distribution():
    results = db.session.query(
        Photo.image_format,
        func.count(Photo.id)
    ).group_by(
        Photo.image_format
    ).all()

    format_data = []
    for fmt, count in results:
        format_data.append({
            'format': (fmt or 'unknown').upper(),
            'count': count
        })
    return sorted(format_data, key=lambda x: x['count'], reverse=True)


def get_heatmap_data():
    end_date = datetime.utcnow().date()
    weekday = end_date.weekday()
    days_to_sunday = (6 - weekday) % 7
    end_date = end_date + timedelta(days=days_to_sunday)

    start_date = end_date - timedelta(weeks=52) + timedelta(days=1)
    start_dt = datetime.combine(start_date, datetime.min.time())

    results = db.session.query(
        func.date(Photo.uploaded_at),
        func.count(Photo.id)
    ).filter(
        Photo.uploaded_at >= start_dt
    ).group_by(
        func.date(Photo.uploaded_at)
    ).all()

    date_counts = {}
    for date_val, count in results:
        date_counts[str(date_val)] = count

    weeks = []
    current_date = start_date
    while current_date <= end_date:
        week_days = []
        for i in range(7):
            d = current_date + timedelta(days=i)
            if d >= start_date and d <= end_date:
                week_days.append({
                    'date': str(d),
                    'count': date_counts.get(str(d), 0)
                })
            else:
                week_days.append(None)
        weeks.append(week_days)
        current_date += timedelta(days=7)

    return weeks


def get_most_active_albums(days=30, limit=5):
    start_dt = datetime.utcnow() - timedelta(days=days)
    results = db.session.query(
        Album.id,
        Album.title,
        func.count(Photo.id).label('upload_count')
    ).join(
        Photo, Photo.album_id == Album.id
    ).filter(
        Photo.uploaded_at >= start_dt
    ).group_by(
        Album.id, Album.title
    ).order_by(
        func.count(Photo.id).desc()
    ).limit(limit).all()

    return [{
        'id': aid,
        'title': title,
        'count': cnt
    } for aid, title, cnt in results]


def get_storage_growth_trend(days=30):
    end_date = datetime.utcnow().date()
    start_date = end_date - timedelta(days=days - 1)
    start_dt = datetime.combine(start_date, datetime.min.time())

    daily_results = db.session.query(
        func.date(Photo.uploaded_at),
        func.count(Photo.id)
    ).filter(
        Photo.uploaded_at >= start_dt
    ).group_by(
        func.date(Photo.uploaded_at)
    ).all()

    date_counts = {}
    for date_val, count in daily_results:
        date_counts[str(date_val)] = count

    labels = []
    cumulative = []
    total = 0
    existing_count = Photo.query.filter(Photo.uploaded_at < start_dt).count()
    total = existing_count

    for i in range(days):
        d = start_date + timedelta(days=i)
        date_str = str(d)
        count = date_counts.get(date_str, 0)
        total += count
        labels.append(date_str)
        cumulative.append(total)

    n = len(labels)
    if n > 1:
        x_mean = (n - 1) / 2
        y_mean = sum(cumulative) / n
        numerator = sum((i - x_mean) * (cumulative[i] - y_mean) for i in range(n))
        denominator = sum((i - x_mean) ** 2 for i in range(n))
        slope = numerator / denominator if denominator != 0 else 0
    else:
        slope = 0

    return {
        'labels': labels,
        'cumulative': cumulative,
        'slope': slope,
        'projected_30d': cumulative[-1] + slope * 30 if cumulative else 0
    }


def collect_dashboard_stats(days=7):
    disk_bytes = estimate_disk_usage_bytes()
    today = datetime.utcnow().date()
    today_start = datetime.combine(today, datetime.min.time())
    today_uploads = Photo.query.filter(Photo.uploaded_at >= today_start).count()

    current_data = get_daily_uploads(days=days)
    prev_end = today - timedelta(days=days)
    prev_data = get_daily_uploads(days=days, end_date=prev_end)

    return {
        'summary': {
            'total_albums': Album.query.count(),
            'total_photos': Photo.query.count(),
            'today_uploads': today_uploads,
            'disk_usage': format_bytes(disk_bytes),
            'disk_usage_bytes': disk_bytes
        },
        'daily_uploads': {
            'current': current_data,
            'previous': prev_data
        },
        'album_counts': get_album_photo_counts(15),
        'format_distribution': get_format_distribution(),
        'heatmap': get_heatmap_data(),
        'active_albums': get_most_active_albums(30, 5),
        'storage_trend': get_storage_growth_trend(30)
    }
