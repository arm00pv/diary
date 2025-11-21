import os
from datetime import datetime, timedelta
from flask import Blueprint, render_template, redirect, url_for, flash, request, abort, current_app
from flask_login import login_required, current_user
from functools import wraps
from .models import db, User, DiaryEntry
from sqlalchemy import func, desc

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

def role_required(roles):
    def decorator(f):
        @wraps(f)
        @login_required
        def decorated_function(*args, **kwargs):
            if current_user.role not in roles:
                abort(403)
            return f(*args, **kwargs)
        return decorated_function
    return decorator

@admin_bp.route('/')
@role_required(['admin', 'super_admin', 'moderator'])
def dashboard():
    # Common data
    flagged_admins = User.query.filter_by(is_flagged=True).all()

    # SUPER ADMIN VIEW
    if current_user.role == 'super_admin':
        # Can see all admins and moderators to manage them
        staff_users = User.query.filter(User.role.in_(['admin', 'moderator'])).all()
        return render_template('admin/dashboard_super.html', staff_users=staff_users, flagged_admins=flagged_admins)

    # MODERATOR VIEW
    if current_user.role == 'moderator':
        # Can see admins to flag them
        admin_users = User.query.filter_by(role='admin').all()
        return render_template('admin/dashboard_moderator.html', admin_users=admin_users)

    # ADMIN VIEW (Full Access to App Data)
    if current_user.role == 'admin':
        if current_user.is_flagged:
            flash("Your account has been flagged for review. Some actions may be restricted.", "warning")

        # Stats
        total_users = User.query.filter_by(role='user').count()
        total_entries = DiaryEntry.query.count()

        # Top Users (Users with most entries)
        top_users = db.session.query(
            User.username,
            func.count(DiaryEntry.id).label('entry_count')
        ).join(DiaryEntry).group_by(User.id).order_by(desc('entry_count')).limit(5).all()

        # Risk Monitoring
        at_risk_users = []
        users = User.query.filter_by(role='user').all()
        for user in users:
            recent_entries = DiaryEntry.query.filter_by(user_id=user.id)\
                .order_by(DiaryEntry.entry_date.desc()).limit(5).all()

            if not recent_entries:
                continue

            avg_sentiment = sum(e.sentiment_score for e in recent_entries) / len(recent_entries)
            worst_entry = min(e.sentiment_score for e in recent_entries)

            if avg_sentiment < -0.5 or worst_entry < -0.8:
                at_risk_users.append({
                    'user': user,
                    'avg_sentiment': round(avg_sentiment, 2),
                    'worst_score': round(worst_entry, 2)
                })

        # All Users List
        all_users = User.query.filter_by(role='user').all()

        # Global Activity Chart (Last 30 Days)
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)
        daily_activity = db.session.query(
            func.date(DiaryEntry.entry_date), func.count(DiaryEntry.id)
        ).filter(DiaryEntry.entry_date >= thirty_days_ago)\
         .group_by(func.date(DiaryEntry.entry_date)).all()

        # Format for Chart.js
        activity_dates = [str(day[0]) for day in daily_activity]
        activity_counts = [day[1] for day in daily_activity]

        # System Health
        db_path = current_app.config['SQLALCHEMY_DATABASE_URI'].replace('sqlite:///', '')
        try:
            db_size = round(os.path.getsize(db_path) / 1024, 2) # KB
        except OSError:
            db_size = "Unknown"

        system_health = {
            'db_size_kb': db_size,
            'server_time': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC'),
            'status': 'Healthy'
        }

        return render_template('admin/dashboard.html',
                            total_users=total_users,
                            total_entries=total_entries,
                            top_users=top_users,
                            at_risk_users=at_risk_users,
                            all_users=all_users,
                            activity_dates=activity_dates,
                            activity_counts=activity_counts,
                            system_health=system_health)

# --- Super Admin Actions ---

@admin_bp.route('/staff/create', methods=['POST'])
@role_required(['super_admin'])
def create_staff():
    username = request.form.get('username')
    password = request.form.get('password')
    role = request.form.get('role') # 'admin' or 'moderator'

    if User.query.filter_by(username=username).first():
        flash('Username already exists')
        return redirect(url_for('admin.dashboard'))

    new_user = User(username=username, role=role)
    new_user.set_password(password)
    db.session.add(new_user)
    db.session.commit()
    flash(f'New {role} created: {username}')
    return redirect(url_for('admin.dashboard'))

@admin_bp.route('/resolve_flag/<int:user_id>/<action>', methods=['POST'])
@role_required(['super_admin'])
def resolve_flag(user_id, action):
    user = User.query.get_or_404(user_id)
    if action == 'dismiss':
        user.is_flagged = False
        user.flagged_by_id = None
        flash(f"Flag dismissed for {user.username}")
    elif action == 'revoke':
        user.role = 'user' # Demote to normal user
        user.is_flagged = False
        user.flagged_by_id = None
        flash(f"{user.username} has been demoted to user.")

    db.session.commit()
    return redirect(url_for('admin.dashboard'))

# --- Moderator Actions ---

@admin_bp.route('/flag_admin/<int:user_id>', methods=['POST'])
@role_required(['moderator'])
def flag_admin(user_id):
    user = User.query.get_or_404(user_id)
    if user.role != 'admin':
        flash("Can only flag Admins.")
        return redirect(url_for('admin.dashboard'))

    user.is_flagged = True
    user.flagged_by_id = current_user.id
    db.session.commit()
    flash(f"Admin {user.username} has been flagged for review.")
    return redirect(url_for('admin.dashboard'))

# --- Admin Actions ---

@admin_bp.route('/user/<int:user_id>/toggle_status', methods=['POST'])
@role_required(['admin'])
def toggle_status(user_id):
    user = User.query.get_or_404(user_id)
    # Admins cannot block other admins or super admins
    if user.role in ['admin', 'super_admin']:
        flash("Cannot modify other admins.")
        return redirect(url_for('admin.dashboard'))

    user.is_active_user = not user.is_active_user
    db.session.commit()
    status = "activated" if user.is_active_user else "blocked"
    flash(f"User {user.username} has been {status}.")
    return redirect(url_for('admin.dashboard'))

@admin_bp.route('/user/<int:user_id>/delete', methods=['POST'])
@role_required(['admin'])
def delete_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.role in ['admin', 'super_admin']:
        flash("Cannot delete admins.")
        return redirect(url_for('admin.dashboard'))

    db.session.delete(user)
    db.session.commit()
    flash(f"User {user.username} deleted.")
    return redirect(url_for('admin.dashboard'))
