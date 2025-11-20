import os
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from datetime import datetime
from werkzeug.exceptions import abort
from textblob import TextBlob

# Import models and db
from .models import db, User, DiaryEntry

def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)

    # Configuration
    app.config.from_mapping(
        SECRET_KEY='dev', # Change this in production
        SQLALCHEMY_DATABASE_URI='sqlite:///' + os.path.join(app.instance_path, 'diary.sqlite'),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
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
        if current_user.is_authenticated:
            return redirect(url_for('main.index'))

        if request.method == 'POST':
            username = request.form.get('username')
            password = request.form.get('password')
            user = User.query.filter_by(username=username).first()

            if user and user.check_password(password):
                login_user(user)
                return redirect(url_for('main.index'))
            else:
                flash('Invalid username or password')

        return render_template('login.html')

    @auth_bp.route('/register', methods=['GET', 'POST'])
    def register():
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
        logout_user()
        return redirect(url_for('auth.login'))

    # Main Routes
    @main_bp.route('/')
    @login_required
    def index():
        query = request.args.get('q')
        if query:
            # Simple search: content or tags
            entries = DiaryEntry.query.filter(
                DiaryEntry.user_id == current_user.id,
                (DiaryEntry.content.contains(query) | DiaryEntry.tags.contains(query))
            ).order_by(DiaryEntry.entry_date.desc()).all()
        else:
            entries = DiaryEntry.query.filter_by(user_id=current_user.id).order_by(DiaryEntry.entry_date.desc()).all()
        return render_template('index.html', entries=entries)

    @main_bp.route('/entry/new', methods=['GET', 'POST'])
    @login_required
    def new_entry():
        if request.method == 'POST':
            content = request.form.get('content')
            date_str = request.form.get('entry_date')
            mood = request.form.get('mood')
            tags = request.form.get('tags')

            try:
                entry_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            except ValueError:
                entry_date = datetime.utcnow().date()

            # Calculate Sentiment
            sentiment = TextBlob(content).sentiment.polarity

            entry = DiaryEntry(
                user_id=current_user.id,
                content=content,
                entry_date=entry_date,
                mood=mood,
                tags=tags,
                sentiment_score=sentiment
            )
            db.session.add(entry)
            db.session.commit()
            return redirect(url_for('main.index'))

        today = datetime.utcnow().strftime('%Y-%m-%d')
        return render_template('entry.html', entry=None, today=today)

    @main_bp.route('/entry/<int:entry_id>', methods=['GET', 'POST'])
    @login_required
    def view_entry(entry_id):
        entry = DiaryEntry.query.get_or_404(entry_id)
        if entry.user_id != current_user.id:
            abort(403)

        if request.method == 'POST':
            entry.content = request.form.get('content')
            date_str = request.form.get('entry_date')
            entry.mood = request.form.get('mood')
            entry.tags = request.form.get('tags')

            # Recalculate sentiment
            entry.sentiment_score = TextBlob(entry.content).sentiment.polarity

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
        user_entries = DiaryEntry.query.filter_by(user_id=current_user.id).order_by(DiaryEntry.entry_date.asc()).all()
        entry_count = len(user_entries)

        if not user_entries:
            return render_template('persona.html',
                                   ai_insight="Write some entries so I can get to know you!",
                                   entry_count=0,
                                   dates=[],
                                   sentiments=[],
                                   question="How are you feeling right now?")

        # Prepare data for chart
        dates = [e.entry_date.strftime('%Y-%m-%d') for e in user_entries]
        sentiments = [e.sentiment_score for e in user_entries]

        # Simple word count
        total_words = sum(len(e.content.split()) for e in user_entries)
        avg_sentiment = sum(sentiments) / entry_count if entry_count > 0 else 0

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

        return render_template('persona.html',
                               ai_insight=ai_insight,
                               entry_count=entry_count,
                               dates=dates,
                               sentiments=sentiments,
                               question=question)

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(ai_bp)

    return app
