from .models import db, User, DiaryEntry
from collections import Counter

BADGE_DEFINITIONS = {
    'first_entry': {'name': 'First Step', 'icon': '🌱', 'desc': 'Created your first entry.'},
    'streak_3': {'name': 'Consistency', 'icon': '🔥', 'desc': 'Wrote for 3 consecutive days.'},
    'streak_7': {'name': 'Habit Builder', 'icon': '📅', 'desc': 'Wrote for 7 consecutive days.'},
    'prolific': {'name': 'Prolific Writer', 'icon': '📚', 'desc': 'Wrote 10 or more entries.'},
    'positive_mind': {'name': 'Positive Mind', 'icon': '☀️', 'desc': 'Wrote 3 positive entries.'},
}

def check_badges(user, current_streak):
    """
    Checks if the user has earned new badges based on their stats.
    Returns a list of newly earned badges (definitions).
    """
    new_badges = []
    entries = user.entries
    entry_count = len(entries)

    # 1. First Entry
    if entry_count >= 1 and not user.has_badge('first_entry'):
        user.add_badge('first_entry')
        new_badges.append(BADGE_DEFINITIONS['first_entry'])

    # 2. Prolific
    if entry_count >= 10 and not user.has_badge('prolific'):
        user.add_badge('prolific')
        new_badges.append(BADGE_DEFINITIONS['prolific'])

    # 3. Streaks
    if current_streak >= 3 and not user.has_badge('streak_3'):
        user.add_badge('streak_3')
        new_badges.append(BADGE_DEFINITIONS['streak_3'])

    if current_streak >= 7 and not user.has_badge('streak_7'):
        user.add_badge('streak_7')
        new_badges.append(BADGE_DEFINITIONS['streak_7'])

    # 4. Positive Mind (Simple check: 3 entries with joy)
    if not user.has_badge('positive_mind'):
        positive_count = sum(1 for e in entries if e.dominant_emotion == 'joy')
        if positive_count >= 3:
            user.add_badge('positive_mind')
            new_badges.append(BADGE_DEFINITIONS['positive_mind'])

    if new_badges:
        db.session.commit()

    return new_badges
