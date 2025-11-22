import random

INSPIRATIONAL_QUOTES = [
    "The only way to do great work is to love what you do. - Steve Jobs",
    "Believe you can and you're halfway there. - Theodore Roosevelt",
    "Your time is limited, don't waste it living someone else's life. - Steve Jobs",
    "The future belongs to those who believe in the beauty of their dreams. - Eleanor Roosevelt",
    "Don't watch the clock; do what it does. Keep going. - Sam Levenson",
    "Keep your face always toward the sunshine—and shadows will fall behind you. - Walt Whitman",
    "The best way to predict the future is to create it. - Peter Drucker",
    "You are never too old to set another goal or to dream a new dream. - C.S. Lewis",
    "Happiness is not something ready made. It comes from your own actions. - Dalai Lama",
    "In the middle of every difficulty lies opportunity. - Albert Einstein",
    "Act as if what you do makes a difference. It does. - William James",
    "Success is not final, failure is not fatal: it is the courage to continue that counts. - Winston Churchill",
    "What lies behind us and what lies before us are tiny matters compared to what lies within us. - Ralph Waldo Emerson"
]

def get_random_quote():
    return random.choice(INSPIRATIONAL_QUOTES)
