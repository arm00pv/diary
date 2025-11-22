import unittest
from diary_app.app import create_app, db
from diary_app.models import User, DiaryEntry
from datetime import datetime

class DiaryTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:', 'WTF_CSRF_ENABLED': False})
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def register(self, username, password):
        return self.client.post('/register', data=dict(
            username=username,
            password=password
        ), follow_redirects=True)

    def login(self, username, password):
        return self.client.post('/login', data=dict(
            username=username,
            password=password
        ), follow_redirects=True)

    def logout(self):
        return self.client.get('/logout', follow_redirects=True)

    def test_register_login_logout(self):
        # Test Registration
        rv = self.register('testuser', 'password')
        self.assertIn(b'Your Diary', rv.data) # Should be redirected to index

        # Test Logout
        rv = self.logout()
        self.assertIn(b'Login', rv.data)

        # Test Login
        rv = self.login('testuser', 'password')
        self.assertIn(b'Your Diary', rv.data)

        # Logout again to test invalid login
        self.logout()

        # Test Invalid Login
        rv = self.login('testuser', 'wrongpass')
        self.assertIn(b'Invalid username or password', rv.data)

    def test_entry_creation(self):
        self.register('testuser', 'password')
        rv = self.client.post('/entry/new', data=dict(
            content='Dear Diary, today was great.',
            entry_date='2023-10-27',
            mood='Happy',
            tags='life, fun'
        ), follow_redirects=True)
        self.assertIn(b'Dear Diary, today was great.', rv.data)
        self.assertIn(b'Happy', rv.data)
        self.assertIn(b'life', rv.data)

    def test_search(self):
        self.register('testuser', 'password')
        # Create entry 1
        self.client.post('/entry/new', data=dict(
            content='Apple pie recipe',
            entry_date='2023-10-27',
            mood='Happy',
            tags='food'
        ), follow_redirects=True)
        # Create entry 2
        self.client.post('/entry/new', data=dict(
            content='Coding python',
            entry_date='2023-10-28',
            mood='Neutral',
            tags='work'
        ), follow_redirects=True)

        # Search for 'Apple'
        rv = self.client.get('/?q=Apple', follow_redirects=True)
        self.assertIn(b'Apple pie recipe', rv.data)
        self.assertNotIn(b'Coding python', rv.data)

        # Search for tag 'work'
        rv = self.client.get('/?q=work', follow_redirects=True)
        self.assertNotIn(b'Apple pie recipe', rv.data)
        self.assertIn(b'Coding python', rv.data)

    def test_persona_access(self):
        self.register('testuser', 'password')
        rv = self.client.get('/persona')
        self.assertIn(b'AI Companion', rv.data)

    def test_theme_change(self):
        self.register('testuser', 'password')
        # Default theme check
        rv = self.client.get('/')
        self.assertIn(b'bootstrap.min.css', rv.data)

        # Change theme to dark
        rv = self.client.post('/settings', data=dict(theme='dark'), follow_redirects=True)
        self.assertIn(b'Preferences updated successfully', rv.data)

        # Verify dark theme is loaded
        rv = self.client.get('/')
        self.assertIn(b'darkly/bootstrap.min.css', rv.data)

    def test_streak_calculation(self):
        self.register('testuser', 'password')

        # Today's entry
        today = datetime.utcnow().strftime('%Y-%m-%d')
        self.client.post('/entry/new', data=dict(
            content='Today',
            entry_date=today,
            mood='Happy'
        ))

        rv = self.client.get('/')
        self.assertIn(b'Current Streak: 1', rv.data)

    def test_emotion_detection(self):
        self.register('emo_user', 'pass')

        # Create Angry Entry
        self.client.post('/entry/new', data=dict(
            content='I am furious and angry and mad!',
            entry_date='2023-11-01',
            mood='Angry'
        ))

        # Verify DB
        with self.app.app_context():
            user = User.query.filter_by(username='emo_user').first()
            entry = user.entries[0]
            self.assertEqual(entry.dominant_emotion, 'anger')

        # Create Happy Entry
        self.client.post('/entry/new', data=dict(
            content='What a wonderful and amazing day! I love it.',
            entry_date='2023-11-02',
            mood='Happy'
        ))

        # Verify DB
        with self.app.app_context():
            user = User.query.filter_by(username='emo_user').first()
            entry = user.entries[1]
            self.assertEqual(entry.dominant_emotion, 'joy')

    def test_emoji_emotion(self):
        self.register('emoji_user', 'pass')

        # Entry with just emojis
        self.client.post('/entry/new', data=dict(
            content='😭😭😭',
            entry_date='2023-11-05',
            mood='Sad'
        ))

        with self.app.app_context():
            user = User.query.filter_by(username='emoji_user').first()
            entry = user.entries[0]
            # Should detect sadness from emojis
            self.assertEqual(entry.dominant_emotion, 'sadness')

    def test_badges_and_export(self):
        self.register('badge_user', 'pass')

        # Create first entry
        self.client.post('/entry/new', data=dict(
            content='My first entry!',
            entry_date='2023-11-01',
            mood='Neutral'
        ))

        # Verify First Step Badge
        with self.app.app_context():
            user = User.query.filter_by(username='badge_user').first()
            self.assertTrue(user.has_badge('first_entry'))
            self.assertFalse(user.has_badge('prolific'))

        # Test Export
        rv = self.client.get('/export')
        self.assertEqual(rv.status_code, 200)
        self.assertIn(b'My first entry!', rv.data)
        self.assertIn('diary_export.json', rv.headers['Content-Disposition'])

    def test_calendar_tags(self):
        self.register('cal_user', 'pass')
        self.client.post('/entry/new', data=dict(
            content='Meeting #work',
            entry_date='2023-11-10',
            mood='Neutral',
            tags='work, busy'
        ))

        # Test Calendar Access
        rv = self.client.get('/calendar')
        self.assertEqual(rv.status_code, 200)
        self.assertIn(b'Neutral', rv.data) # Check title (Mood) present in events JSON

        # Test Tags Page
        rv = self.client.get('/tags')
        self.assertEqual(rv.status_code, 200)
        self.assertIn(b'work', rv.data)
        self.assertIn(b'busy', rv.data)

    def test_super_admin_dashboard(self):
        # Create Super Admin directly in DB
        with self.app.app_context():
            u = User(username='super', role='super_admin')
            u.set_password('pass')
            db.session.add(u)
            db.session.commit()

        self.login('super', 'pass')
        rv = self.client.get('/admin/', follow_redirects=True)
        self.assertIn(b'Super Admin Dashboard', rv.data)
        self.assertIn(b'Assign New Staff', rv.data)

    def test_moderator_action(self):
        # Create Users directly
        with self.app.app_context():
            mod = User(username='mod', role='moderator')
            mod.set_password('pass')
            db.session.add(mod)

            bad_admin = User(username='bad_admin', role='admin')
            bad_admin.set_password('pass')
            db.session.add(bad_admin)
            db.session.commit()

            # Capture ID for test
            target_id = bad_admin.id

        self.login('mod', 'pass')

        # Flag Admin
        rv = self.client.post(f'/admin/flag_admin/{target_id}', follow_redirects=True)
        self.assertIn(b'has been flagged for review', rv.data)

        # Verify flag in DB
        with self.app.app_context():
            target = User.query.get(target_id)
            self.assertTrue(target.is_flagged)

    def test_admin_block_user(self):
        # Create Users directly
        with self.app.app_context():
            admin = User(username='admin', role='admin')
            admin.set_password('pass')
            db.session.add(admin)

            normal = User(username='normal', role='user')
            normal.set_password('pass')
            db.session.add(normal)
            db.session.commit()

            target_id = normal.id

        self.login('admin', 'pass')

        # Block user
        rv = self.client.post(f'/admin/user/{target_id}/toggle_status', follow_redirects=True)
        self.assertIn(b'User normal has been blocked', rv.data)
        self.logout()

        # Try to login
        rv = self.login('normal', 'pass')
        self.assertIn(b'Your account has been blocked', rv.data)

if __name__ == '__main__':
    unittest.main()
