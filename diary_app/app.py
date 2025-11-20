import os
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from datetime import datetime
from werkzeug.exceptions import abort

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
        entries = DiaryEntry.query.filter_by(user_id=current_user.id).order_by(DiaryEntry.entry_date.desc()).all()
        return render_template('index.html', entries=entries)

    @main_bp.route('/entry/new', methods=['GET', 'POST'])
    @login_required
    def new_entry():
        if request.method == 'POST':
            content = request.form.get('content')
            date_str = request.form.get('entry_date')
            mood = request.form.get('mood')

            try:
                entry_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            except ValueError:
                entry_date = datetime.utcnow().date()

            entry = DiaryEntry(
                user_id=current_user.id,
                content=content,
                entry_date=entry_date,
                mood=mood
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
        # Placeholder for AI Persona logic
        # In the future, this will aggregate data from entries
        user_entries = DiaryEntry.query.filter_by(user_id=current_user.id).all()
        entry_count = len(user_entries)

        # Simple word count as a placeholder analysis
        total_words = sum(len(e.content.split()) for e in user_entries)

        ai_insight = "I am getting to know you. Keep writing!"
        if entry_count > 5:
            ai_insight = f"You are a prolific writer! You have written {total_words} words. I sense you are a thoughtful person."

        return render_template('persona.html', ai_insight=ai_insight, entry_count=entry_count)

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(ai_bp)

    return app
