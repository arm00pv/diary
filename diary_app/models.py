from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)

    # User preferences
    theme_preference = db.Column(db.String(50), default='default')
    font_preference = db.Column(db.String(20), default='sans') # 'sans', 'serif', 'mono'
    avatar_emoji = db.Column(db.String(10), default='👤')

    # Admin & Status
    # Roles: 'user', 'admin', 'super_admin', 'moderator'
    role = db.Column(db.String(20), default='user')
    is_active_user = db.Column(db.Boolean, default=True)

    # For flagging admins (Quality Control)
    is_flagged = db.Column(db.Boolean, default=False)
    flagged_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)

    # Gamification
    badges = db.Column(db.String(500), default='') # Comma separated badge codes

    entries = db.relationship('DiaryEntry', backref='author', lazy=True, cascade="all, delete-orphan")

    def add_badge(self, badge_code):
        if not self.badges:
            self.badges = badge_code
        elif badge_code not in self.badges.split(','):
            self.badges += f",{badge_code}"

    def has_badge(self, badge_code):
        return self.badges and badge_code in self.badges.split(',')

    @property
    def is_admin(self):
        return self.role in ['admin', 'super_admin']

    @property
    def is_super_admin(self):
        return self.role == 'super_admin'

    @property
    def is_moderator(self):
        return self.role == 'moderator'

    @property
    def is_active(self):
        return self.is_active_user

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class DiaryEntry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)
    # Storing date explicitly to allow users to write for past dates easily
    entry_date = db.Column(db.Date, nullable=False, default=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Simple mood tracking for AI analysis later
    mood = db.Column(db.String(50), nullable=True)

    # New fields for AI and Organization
    sentiment_score = db.Column(db.Float, default=0.0) # -1.0 (Negative) to 1.0 (Positive)
    dominant_emotion = db.Column(db.String(50), default='neutral') # AI detected emotion
    tags = db.Column(db.String(200), nullable=True) # Comma separated tags
