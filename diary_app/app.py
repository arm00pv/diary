import os
import click
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session, Response
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
import re
import csv
import io
import json
import markdown
from datetime import datetime, timedelta
from werkzeug.exceptions import abort
from werkzeug.utils import secure_filename
from werkzeug.security import check_password_hash, generate_password_hash
from textblob import TextBlob
from collections import Counter
from sqlalchemy import extract
from .ai_utils import detect_dominant_emotion
from .gamification import check_badges, BADGE_DEFINITIONS
from .quotes import get_random_quote
from .prompts import get_random_prompt

# Import models and db
from .models import db, User, DiaryEntry, GratitudeNote, EntryLike, Habit, HabitCompletion

UPLOAD_FOLDER = 'diary_app/static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webm', 'wav', 'mp3', 'ogg'}

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def calculate_streak(entries):
    """
    Calculates the current streak of consecutive days with entries.

    Args:
        entries (list): List of DiaryEntry objects, sorted by date (descending or ascending).

    Returns:
        int: The number of consecutive days the user has written.
    """
    if not entries:
        return 0

    # Ensure entries are sorted by date descending
    sorted_entries = sorted(entries, key=lambda x: x.entry_date, reverse=True)

    streak = 0
    today = datetime.utcnow().date()

    # Check if there is an entry for today or yesterday to start the streak
    last_entry_date = sorted_entries[0].entry_date

    if last_entry_date == today:
        streak = 1
        current_check_date = today - timedelta(days=1)
    elif last_entry_date == today - timedelta(days=1):
        streak = 1
        current_check_date = today - timedelta(days=2)
    else:
        return 0 # Streak broken

    # Iterate through the rest of the entries
    entry_dates = {e.entry_date for e in sorted_entries}

    while current_check_date in entry_dates:
        streak += 1
        current_check_date -= timedelta(days=1)

    return streak

def get_ai_advice(avg_sentiment, keywords):
    """
    Generates simple advice based on sentiment score and extracted keywords.

    Args:
        avg_sentiment (float): The average sentiment score (-1.0 to 1.0).
        keywords (list): A list of tuples (word, count) representing frequent terms.

    Returns:
        str: A piece of advice or encouragement.
    """
    advice = ""

    # Sentiment-based advice
    if avg_sentiment < -0.5:
        advice = "It seems you've been going through a very difficult time. consider reaching out to a friend or professional. "
    elif avg_sentiment < -0.2:
        advice = "Things have been a bit rough lately. Be kind to yourself and take small breaks. "
    elif avg_sentiment > 0.5:
        advice = "You're doing great! Try to channel this energy into a new project or hobby. "
    else:
        advice = "Consistency is key. Keep observing your daily life. "

    # Keyword-based additions (simple heuristic)
    keywords_flat = [k[0].lower() for k in keywords]

    if 'work' in keywords_flat or 'job' in keywords_flat:
        if avg_sentiment < 0:
            advice += "Work seems to be a stressor. Can you delegate tasks or take some time off?"
        else:
            advice += "Your career seems to be a source of engagement right now."

    if 'sleep' in keywords_flat or 'tired' in keywords_flat:
        advice += " Make sure you are prioritizing your rest."

    return advice

def create_app(test_config=None):
    """
    Application Factory function to create and configure the Flask app.

    Args:
        test_config (dict): Configuration dictionary for testing purposes.

    Returns:
        Flask: The configured Flask application instance.
    """
    app = Flask(__name__, instance_relative_config=True)

    # Configuration
    app.config.from_mapping(
        SECRET_KEY='dev', # Change this in production
        SQLALCHEMY_DATABASE_URI='sqlite:///' + os.path.join(app.instance_path, 'diary.sqlite'),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        UPLOAD_FOLDER=UPLOAD_FOLDER
    )

    if test_config is None:
        # load the instance config, if it exists, when not testing
        try:
            os.makedirs(app.instance_path)
        except OSError:
            pass
    else:
        # load the test config if passed in
        app.config.from_mapping(test_config)

    # Initialize extensions
    db.init_app(app)

    login_manager = LoginManager()
    login_manager.login_view = 'auth.login'
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        """Callback to reload the user object from the user ID stored in the session."""
        return User.query.get(int(user_id))

    with app.app_context():
        db.create_all()

    # --- Routes ---

    from flask import Blueprint
    auth_bp = Blueprint('auth', __name__)
    main_bp = Blueprint('main', __name__)
    ai_bp = Blueprint('ai', __name__)

    # Auth Routes
    @auth_bp.route('/login', methods=['GET', 'POST'])
    def login():
        """Handle user login."""
        if current_user.is_authenticated:
            return redirect(url_for('main.index'))

        if request.method == 'POST':
            username = request.form.get('username')
            password = request.form.get('password')
            user = User.query.filter_by(username=username).first()

            if user and user.check_password(password):
                if not user.is_active_user:
                    flash('Your account has been blocked. Please contact admin.')
                    return render_template('login.html')

                login_user(user)
                return redirect(url_for('main.index'))
            else:
                flash('Invalid username or password')

        return render_template('login.html')

    @auth_bp.route('/register', methods=['GET', 'POST'])
    def register():
        """Handle user registration."""
        if current_user.is_authenticated:
            return redirect(url_for('main.index'))

        if request.method == 'POST':
            username = request.form.get('username')
            password = request.form.get('password')

            user = User.query.filter_by(username=username).first()
            if user:
                flash('Username already exists')
            else:
                new_user = User(username=username)
                new_user.set_password(password)
                db.session.add(new_user)
                db.session.commit()
                login_user(new_user)
                return redirect(url_for('main.index'))

        return render_template('register.html')

    @auth_bp.route('/logout')
    @login_required
    def logout():
        """Handle user logout."""
        logout_user()
        return redirect(url_for('auth.login'))

    # Main Routes
    @main_bp.route('/tags')
    @login_required
    def tags():
        """View all tags and their frequencies."""
        entries = DiaryEntry.query.filter_by(user_id=current_user.id).all()
        tag_counts = Counter()

        for e in entries:
            if e.tags:
                # Split by comma and strip whitespace
                tags_list = [t.strip() for t in e.tags.split(',') if t.strip()]
                tag_counts.update(tags_list)

        return render_template('tags.html', tags=tag_counts.most_common())

    @main_bp.route('/api/prompt')
    @login_required
    def api_prompt():
        """Get a random writing prompt."""
        return jsonify({'prompt': get_random_prompt()})

    @main_bp.route('/read')
    @login_required
    def read_mode():
        """Reading Mode: Chronological view of unlocked entries."""
        today = datetime.utcnow().date()
        entries = DiaryEntry.query.filter(
            DiaryEntry.user_id == current_user.id,
            (DiaryEntry.is_locked == False) | (DiaryEntry.unlock_date <= today)
        ).order_by(DiaryEntry.entry_date.asc()).all()

        return render_template('read_mode.html', entries=entries)

    @main_bp.route('/gratitude', methods=['GET', 'POST'])
    @login_required
    def gratitude():
        """Gratitude Jar view."""
        if request.method == 'POST':
            content = request.form.get('content')
            if content:
                note = GratitudeNote(user_id=current_user.id, content=content)
                db.session.add(note)
                db.session.commit()
                flash('Added to your Gratitude Jar! 🌟', 'success')
            return redirect(url_for('main.gratitude'))

        notes = GratitudeNote.query.filter_by(user_id=current_user.id).order_by(GratitudeNote.created_at.desc()).all()
        return render_template('gratitude.html', notes=notes)

    @main_bp.route('/community')
    @login_required
    def community():
        """Community Feed."""
        # Show public entries from all users, anonymous by default
        entries = DiaryEntry.query.filter_by(is_public=True).order_by(DiaryEntry.created_at.desc()).limit(50).all()

        # Get list of entry IDs liked by current user for UI state
        user_likes = [like.entry_id for like in EntryLike.query.filter_by(user_id=current_user.id).all()]

        return render_template('community.html', entries=entries, user_likes=user_likes)

    @main_bp.route('/community/like/<int:entry_id>', methods=['POST'])
    @login_required
    def like_entry(entry_id):
        """Toggle like/hug on an entry."""
        entry = DiaryEntry.query.get_or_404(entry_id)
        if not entry.is_public:
            abort(403)

        existing_like = EntryLike.query.filter_by(user_id=current_user.id, entry_id=entry_id).first()

        if existing_like:
            db.session.delete(existing_like)
            flash('Hug removed.', 'info')
        else:
            new_like = EntryLike(user_id=current_user.id, entry_id=entry_id)
            db.session.add(new_like)
            flash('You sent a hug! 🫂', 'success')

        db.session.commit()
        return redirect(url_for('main.community'))

    @main_bp.route('/habits', methods=['GET', 'POST'])
    @login_required
    def habits():
        """Manage Habits."""
        if request.method == 'POST':
            name = request.form.get('name')
            icon = request.form.get('icon', '✅')

            if name:
                habit = Habit(user_id=current_user.id, name=name, icon=icon)
                db.session.add(habit)
                db.session.commit()
                flash('Habit added!', 'success')
            return redirect(url_for('main.habits'))

        user_habits = Habit.query.filter_by(user_id=current_user.id).all()
        return render_template('habits.html', habits=user_habits)

    @main_bp.route('/habits/delete/<int:habit_id>', methods=['POST'])
    @login_required
    def delete_habit(habit_id):
        habit = Habit.query.get_or_404(habit_id)
        if habit.user_id != current_user.id:
            abort(403)
        db.session.delete(habit)
        db.session.commit()
        flash('Habit deleted.', 'success')
        return redirect(url_for('main.habits'))

    @main_bp.route('/habits/toggle/<int:habit_id>', methods=['POST'])
    @login_required
    def toggle_habit(habit_id):
        habit = Habit.query.get_or_404(habit_id)
        if habit.user_id != current_user.id:
            abort(403)

        # Toggle for Today (or provided date, but simplifying to today for widget)
        date_str = request.form.get('date')
        if date_str:
            try:
                target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            except ValueError:
                target_date = datetime.utcnow().date()
        else:
            target_date = datetime.utcnow().date()

        completion = HabitCompletion.query.filter_by(habit_id=habit_id, date=target_date).first()

        if completion:
            db.session.delete(completion)
            status = "unchecked"
        else:
            new_comp = HabitCompletion(habit_id=habit_id, date=target_date)
            db.session.add(new_comp)
            status = "checked"

        db.session.commit()

        # If AJAX request, return JSON
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'status': status})

        return redirect(url_for('main.index'))

    @main_bp.route('/calendar')
    @login_required
    def calendar():
        """View entries in a calendar format."""
        entries = DiaryEntry.query.filter_by(user_id=current_user.id).all()
        events = []

        # Map moods/emotions to colors
        color_map = {
            'joy': '#198754', # Green
            'happy': '#198754',
            'sadness': '#0d6efd', # Blue
            'sad': '#0d6efd',
            'anger': '#dc3545', # Red
            'angry': '#dc3545',
            'fear': '#6f42c1', # Purple
            'anxious': '#6f42c1',
            'neutral': '#6c757d', # Gray
            'surprise': '#ffc107' # Yellow
        }

        for e in entries:
            # Determine color based on dominant emotion or mood
            key = e.dominant_emotion if e.dominant_emotion != 'neutral' else (e.mood.lower() if e.mood else 'neutral')
            color = color_map.get(key, '#6c757d')

            events.append({
                'title': e.mood or e.dominant_emotion or 'Entry',
                'start': e.entry_date.strftime('%Y-%m-%d'),
                'url': url_for('main.view_entry', entry_id=e.id),
                'backgroundColor': color,
                'borderColor': color
            })

        return render_template('calendar.html', events=events)

    @main_bp.route('/settings', methods=['GET', 'POST'])
    @login_required
    def settings():
        """User settings page for changing themes and preferences."""
        if request.method == 'POST':
            theme = request.form.get('theme')
            font = request.form.get('font')
            avatar = request.form.get('avatar')

            if theme:
                current_user.theme_preference = theme
            if font:
                current_user.font_preference = font
            if avatar:
                current_user.avatar_emoji = avatar

            db.session.commit()
            flash('Preferences updated successfully!')
            return redirect(url_for('main.settings'))

        return render_template('settings.html')

    @main_bp.route('/settings/profile', methods=['POST'])
    @login_required
    def update_profile():
        """Update user profile (username/password)."""
        username = request.form.get('username')
        password = request.form.get('password')

        if username and username != current_user.username:
            # Check if taken
            if User.query.filter_by(username=username).first():
                flash('Username already taken.')
                return redirect(url_for('main.settings'))
            current_user.username = username

        if password:
            current_user.set_password(password)

        # Secret PIN Update
        pin = request.form.get('secret_pin')
        if pin:
            current_user.secret_pin_hash = generate_password_hash(pin)

        db.session.commit()
        flash('Profile updated successfully!')
        return redirect(url_for('main.settings'))

    @main_bp.route('/')
    @login_required
    def index():
        """Dashboard showing diary entries, search results, and flashbacks."""
        quote = get_random_quote()
        today = datetime.utcnow().date()

        query = request.args.get('q')
        mood_filter = request.args.get('mood')
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')

        # Base Query
        base_query = DiaryEntry.query.filter(
            DiaryEntry.user_id == current_user.id,
            (DiaryEntry.is_locked == False) | (DiaryEntry.unlock_date <= today)
        )

        # 1. Search Logic with Highlighting
        if query:
            base_query = base_query.filter(
                (DiaryEntry.content.contains(query) | DiaryEntry.tags.contains(query))
            )

        # 2. Advanced Filters
        if mood_filter:
            base_query = base_query.filter(DiaryEntry.mood == mood_filter)

        if start_date:
            try:
                s_date = datetime.strptime(start_date, '%Y-%m-%d').date()
                base_query = base_query.filter(DiaryEntry.entry_date >= s_date)
            except ValueError:
                pass

        if end_date:
            try:
                e_date = datetime.strptime(end_date, '%Y-%m-%d').date()
                base_query = base_query.filter(DiaryEntry.entry_date <= e_date)
            except ValueError:
                pass

        entries = base_query.order_by(DiaryEntry.entry_date.desc()).all()

        if query:
            # Highlight terms
            for entry in entries:
                pattern = re.compile(re.escape(query), re.IGNORECASE)
                entry.content = pattern.sub(lambda m: f'<mark>{m.group(0)}</mark>', entry.content)

        # 2. On This Day Logic (Flashbacks)
        flashbacks = []
        if not query: # Only show flashbacks on main dashboard, not search results
            flashbacks = DiaryEntry.query.filter(
                DiaryEntry.user_id == current_user.id,
                extract('month', DiaryEntry.entry_date) == today.month,
                extract('day', DiaryEntry.entry_date) == today.day,
                extract('year', DiaryEntry.entry_date) != today.year,
                (DiaryEntry.is_locked == False) | (DiaryEntry.unlock_date <= today)
            ).all()

        # Calculate Streak
        all_user_entries = DiaryEntry.query.filter_by(user_id=current_user.id).all()
        streak = calculate_streak(all_user_entries)

        # Habits for Widget
        habits = Habit.query.filter_by(user_id=current_user.id).all()
        # Attach completion status for today
        for habit in habits:
            habit.completed_today = HabitCompletion.query.filter_by(habit_id=habit.id, date=today).first() is not None

        return render_template('index.html', entries=entries, streak=streak, quote=quote, flashbacks=flashbacks, habits=habits)

    # Markdown Filter
    @app.template_filter('markdown')
    def markdown_filter(text):
        if not text:
            return ""
        return markdown.markdown(text)

    # Context Processor to inject theme URL into all templates
    @app.context_processor
    def inject_theme():
        """Injects the correct CSS URL based on the user's theme preference."""
        theme_map = {
            'default': 'https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css',
            'dark': 'https://cdn.jsdelivr.net/npm/bootswatch@5.3.0/dist/darkly/bootstrap.min.css',
            'nature': 'https://cdn.jsdelivr.net/npm/bootswatch@5.3.0/dist/minty/bootstrap.min.css',
            'warm': 'https://cdn.jsdelivr.net/npm/bootswatch@5.3.0/dist/sandstone/bootstrap.min.css',
            'professional': 'https://cdn.jsdelivr.net/npm/bootswatch@5.3.0/dist/cosmo/bootstrap.min.css',
            'purple': 'https://cdn.jsdelivr.net/npm/bootswatch@5.3.0/dist/lux/bootstrap.min.css'
        }

        current_theme_url = theme_map.get('default')
        if current_user.is_authenticated:
            current_theme_url = theme_map.get(current_user.theme_preference, theme_map['default'])

        return dict(current_theme_url=current_theme_url)

    @main_bp.route('/entry/new', methods=['GET', 'POST'])
    @login_required
    def new_entry():
        """Create a new diary entry."""
        if request.method == 'POST':
            content = request.form.get('content')
            date_str = request.form.get('entry_date')
            mood = request.form.get('mood')
            weather = request.form.get('weather')
            tags = request.form.get('tags')

            # Time Capsule
            unlock_date_str = request.form.get('unlock_date')
            unlock_date = None
            is_locked = False
            if unlock_date_str:
                try:
                    unlock_date = datetime.strptime(unlock_date_str, '%Y-%m-%d').date()
                    if unlock_date > datetime.utcnow().date():
                        is_locked = True
                except ValueError:
                    pass

            try:
                entry_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            except ValueError:
                entry_date = datetime.utcnow().date()

            # Handle Image Upload
            image_filename = None
            if 'image' in request.files:
                file = request.files['image']
                if file and allowed_file(file.filename):
                    filename = secure_filename(file.filename)
                    unique_filename = f"img_{current_user.id}_{datetime.utcnow().timestamp()}_{filename}"
                    file.save(os.path.join(app.config['UPLOAD_FOLDER'], unique_filename))
                    image_filename = unique_filename

            # Handle Audio Upload (Blob or File)
            audio_filename = None
            if 'audio' in request.files:
                file = request.files['audio']
                if file and allowed_file(file.filename):
                    filename = secure_filename(file.filename)
                    unique_filename = f"audio_{current_user.id}_{datetime.utcnow().timestamp()}_{filename}"
                    file.save(os.path.join(app.config['UPLOAD_FOLDER'], unique_filename))
                    audio_filename = unique_filename

            # Calculate Sentiment
            sentiment = TextBlob(content).sentiment.polarity

            # Calculate Emotion
            emotion = detect_dominant_emotion(content)

            entry = DiaryEntry(
                user_id=current_user.id,
                content=content,
                entry_date=entry_date,
                mood=mood,
                weather=weather,
                tags=tags,
                sentiment_score=sentiment,
                dominant_emotion=emotion,
                is_locked=is_locked,
                unlock_date=unlock_date,
                is_public = 'is_public' in request.form,
                is_secret = 'is_secret' in request.form,
                image_filename=image_filename,
                audio_filename=audio_filename
            )
            db.session.add(entry)
            db.session.commit()

            # Check for badges
            # Need to recalculate streak potentially, or just check basic ones
            # For simplicity, we calculate streak here (inefficient but works for small app)
            all_entries = DiaryEntry.query.filter_by(user_id=current_user.id).all()
            streak = calculate_streak(all_entries)
            new_badges = check_badges(current_user, streak)

            if new_badges:
                for b in new_badges:
                    flash(f"🏆 New Badge Unlocked: {b['name']}!", "success")

            return redirect(url_for('main.index'))

        today = datetime.utcnow().strftime('%Y-%m-%d')
        return render_template('entry.html', entry=None, today=today)

    @main_bp.route('/entry/<int:entry_id>', methods=['GET', 'POST'])
    @login_required
    def view_entry(entry_id):
        """View and edit an existing diary entry."""
        entry = DiaryEntry.query.get_or_404(entry_id)
        if entry.user_id != current_user.id:
            abort(403)

        # Secret PIN Verification
        if entry.is_secret:
            # Check if PIN provided in session or form
            # For simplicity, we use a simple form check on the unlock page
            if 'pin_verified_entry' not in session or session['pin_verified_entry'] != entry_id:
                if request.method == 'POST' and 'unlock_pin' in request.form:
                    pin = request.form.get('unlock_pin')
                    if current_user.secret_pin_hash and check_password_hash(current_user.secret_pin_hash, pin):
                        session['pin_verified_entry'] = entry_id
                        return redirect(url_for('main.view_entry', entry_id=entry_id))
                    else:
                        flash('Incorrect PIN', 'danger')

                # If verified, continue to view
                # If not verified and just GET or failed POST, show unlock screen
                if 'pin_verified_entry' not in session or session['pin_verified_entry'] != entry_id:
                    return render_template('unlock_entry.html', entry=entry)

        if request.method == 'POST':
            entry.content = request.form.get('content')
            date_str = request.form.get('entry_date')
            entry.mood = request.form.get('mood')
            entry.weather = request.form.get('weather')
            entry.tags = request.form.get('tags')
            entry.is_secret = 'is_secret' in request.form

            # Recalculate sentiment and emotion
            entry.sentiment_score = TextBlob(entry.content).sentiment.polarity
            entry.dominant_emotion = detect_dominant_emotion(entry.content)

            try:
                entry.entry_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            except ValueError:
                pass # Keep old date if invalid

            db.session.commit()
            flash('Entry updated')
            return redirect(url_for('main.index'))

        return render_template('entry.html', entry=entry)

    @main_bp.route('/entry/<int:entry_id>/delete', methods=['POST'])
    @login_required
    def delete_entry(entry_id):
        """Delete a diary entry."""
        entry = DiaryEntry.query.get_or_404(entry_id)
        if entry.user_id != current_user.id:
            abort(403)
        db.session.delete(entry)
        db.session.commit()
        flash('Entry deleted')
        return redirect(url_for('main.index'))

    # AI Routes
    @ai_bp.route('/persona')
    @login_required
    def persona():
        """
        AI Analytics page.
        Calculates sentiment trends, word counts, keyword extraction, and generates advice.
        """
        user_entries = DiaryEntry.query.filter_by(user_id=current_user.id).order_by(DiaryEntry.entry_date.asc()).all()
        entry_count = len(user_entries)

        if not user_entries:
            return render_template('persona.html',
                                   ai_insight="Write some entries so I can get to know you!",
                                   entry_count=0,
                                   dates=[],
                                   sentiments=[],
                                   question="How are you feeling right now?",
                                   keywords=[],
                                   advice="Start writing to unlock insights!",
                                   weekly_recap={},
                                   activity_data={},
                                   badges=BADGE_DEFINITIONS)

        # Prepare data for chart
        dates = [e.entry_date.strftime('%Y-%m-%d') for e in user_entries]
        sentiments = [e.sentiment_score for e in user_entries]

        # Aggregate all content for analysis
        full_text = " ".join([e.content for e in user_entries])
        blob = TextBlob(full_text)

        # Extract Noun Phrases (Keywords)
        # We filter for longer phrases or frequent words to avoid noise
        noun_phrases = blob.noun_phrases
        # Count frequencies
        phrase_counts = Counter(noun_phrases).most_common(5)

        # Calculate stats
        total_words = len(full_text.split())
        avg_sentiment = sum(sentiments) / entry_count if entry_count > 0 else 0

        # Generate Insights
        ai_insight = "I am getting to know you. "
        if entry_count > 5:
            ai_insight += f"You are a prolific writer ({total_words} words)! "

        if avg_sentiment > 0.3:
            ai_insight += "You seem generally positive and optimistic."
        elif avg_sentiment < -0.3:
            ai_insight += "You seem to be going through a tough time. Remember to take care of yourself."
        else:
            ai_insight += "Your days seem balanced."

        # Question of the day logic
        last_entry = user_entries[-1]
        if last_entry.sentiment_score < -0.2:
            question = "It seems like things were tough recently. What is one small thing that could bring you joy today?"
        elif last_entry.sentiment_score > 0.5:
            question = "You've been feeling great! How can you share this positivity with others?"
        else:
            question = "What is the most interesting thing that happened to you recently?"

        # Generate Advice
        advice = get_ai_advice(avg_sentiment, phrase_counts)

        # --- Weekly Recap Logic ---
        today = datetime.utcnow().date()
        week_start = today - timedelta(days=7)

        # Filter for last 7 days
        weekly_entries = [e for e in user_entries if e.entry_date >= week_start]

        weekly_recap = {}
        if weekly_entries:
            w_sentiment = sum(e.sentiment_score for e in weekly_entries) / len(weekly_entries)
            w_emotions = [e.dominant_emotion for e in weekly_entries]
            w_top_emotion = Counter(w_emotions).most_common(1)[0][0]
            w_count = len(weekly_entries)

            recap_text = f"This week you wrote {w_count} entries. "
            if w_sentiment > 0.2:
                recap_text += "It was a generally positive week! "
            elif w_sentiment < -0.2:
                recap_text += "It was a challenging week. "
            else:
                recap_text += "It was a balanced week. "

            recap_text += f"Your dominant emotion was '{w_top_emotion}'."

            weekly_recap = {
                'count': w_count,
                'avg_sentiment': round(w_sentiment, 2),
                'top_emotion': w_top_emotion,
                'text': recap_text
            }

        # --- Activity Heatmap Data ---
        # We need a list of {date: "YYYY-MM-DD", count: N} for the last 365 days?
        # Or simpler: just pass a dictionary of date->count to the template and let JS/Jinja handle it.
        activity_data = {}
        for e in user_entries:
            d_str = e.entry_date.strftime('%Y-%m-%d')
            activity_data[d_str] = activity_data.get(d_str, 0) + 1

        return render_template('persona.html',
                               ai_insight=ai_insight,
                               entry_count=entry_count,
                               dates=dates,
                               sentiments=sentiments,
                               question=question,
                               keywords=phrase_counts,
                               advice=advice,
                               weekly_recap=weekly_recap,
                               activity_data=activity_data,
                               badges=BADGE_DEFINITIONS)

    @main_bp.route('/export')
    @login_required
    def export_data():
        """Export all user entries as JSON."""
        entries = DiaryEntry.query.filter_by(user_id=current_user.id).all()
        data = []
        for e in entries:
            data.append({
                'date': e.entry_date.strftime('%Y-%m-%d'),
                'content': e.content,
                'mood': e.mood,
                'weather': e.weather,
                'emotion': e.dominant_emotion,
                'sentiment': e.sentiment_score,
                'tags': e.tags
            })

        response = jsonify(data)
        response.headers.set('Content-Disposition', 'attachment; filename=diary_export.json')
        return response

    @main_bp.route('/export/csv')
    @login_required
    def export_data_csv():
        """Export all user entries as CSV."""
        entries = DiaryEntry.query.filter_by(user_id=current_user.id).all()

        # Create CSV in memory
        si = io.StringIO()
        cw = csv.writer(si)
        cw.writerow(['Date', 'Content', 'Mood', 'Weather', 'Emotion', 'Sentiment', 'Tags'])

        for e in entries:
            cw.writerow([
                e.entry_date.strftime('%Y-%m-%d'),
                e.content,
                e.mood or '',
                e.weather or '',
                e.dominant_emotion,
                e.sentiment_score,
                e.tags or ''
            ])

        output = si.getvalue()
        return Response(
            output,
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment;filename=diary_export.csv"}
        )

    @main_bp.route('/import', methods=['POST'])
    @login_required
    def import_data():
        """Import entries from a JSON file."""
        if 'file' not in request.files:
            flash('No file part')
            return redirect(url_for('main.settings'))

        file = request.files['file']
        if file.filename == '':
            flash('No selected file')
            return redirect(url_for('main.settings'))

        if file:
            try:
                data = json.load(file)
                count = 0
                for item in data:
                    # Basic validation
                    if 'content' not in item or 'date' not in item:
                        continue

                    entry_date = datetime.strptime(item['date'], '%Y-%m-%d').date()

                    # Check for duplicate (same date and same content start)
                    # Or simpler: allow multiple entries per day, but check exact content match
                    exists = DiaryEntry.query.filter_by(
                        user_id=current_user.id,
                        entry_date=entry_date,
                        content=item['content']
                    ).first()

                    if not exists:
                        new_entry = DiaryEntry(
                            user_id=current_user.id,
                            content=item['content'],
                            entry_date=entry_date,
                            mood=item.get('mood'),
                            weather=item.get('weather'),
                            tags=item.get('tags'),
                            dominant_emotion=item.get('emotion', detect_dominant_emotion(item['content'])),
                            sentiment_score=item.get('sentiment', TextBlob(item['content']).sentiment.polarity)
                        )
                        db.session.add(new_entry)
                        count += 1

                db.session.commit()
                flash(f'Successfully imported {count} entries!')

            except Exception as e:
                flash(f'Error importing data: {str(e)}')

        return redirect(url_for('main.settings'))

    from .admin import admin_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(ai_bp)
    app.register_blueprint(admin_bp)

    # CLI Command to create admin
    @app.cli.command("create-super-admin")
    @click.argument("username")
    @click.argument("password")
    def create_super_admin(username, password):
        """Create a new Super Admin (Assignment User)."""
        user = User(username=username, role='super_admin')
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        print(f"Super Admin {username} created successfully. You can now assign other admins.")

    return app
