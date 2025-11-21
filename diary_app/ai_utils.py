import re
from collections import Counter

# Simple Lexicon-based Emotion Detection
# In a production app, this would be replaced by a trained ML model (e.g., BERT or NaiveBayes)
# But for a lightweight app, a robust keyword list works surprisingly well.

EMOTION_LEXICON = {
    'joy': [
        'happy', 'joy', 'excited', 'wonderful', 'great', 'good', 'love', 'fantastic', 'amazing',
        'fun', 'smile', 'laugh', 'pleased', 'delighted', 'glad', 'cheerful', 'blessed', 'sunny',
        'enjoy', 'beautiful', 'peace', 'calm', 'content', 'proud', 'win', 'success', 'yay'
    ],
    'sadness': [
        'sad', 'down', 'unhappy', 'cry', 'tears', 'grief', 'loss', 'miss', 'lonely', 'hurt',
        'pain', 'sorry', 'regret', 'bad', 'fail', 'disappointed', 'heartbroken', 'tired',
        'exhausted', 'depressed', 'blue', 'hopeless', 'dark'
    ],
    'anger': [
        'angry', 'mad', 'furious', 'hate', 'annoyed', 'irritated', 'frustrated', 'stupid',
        'idiot', 'rage', 'yell', 'scream', 'unfair', 'jealous', 'envy', 'disgust', 'awful',
        'terrible', 'worst', 'fight', 'argument'
    ],
    'fear': [
        'scared', 'afraid', 'fear', 'anxious', 'nervous', 'worried', 'panic', 'terrified',
        'horror', 'stress', 'stressed', 'dread', 'uneasy', 'tense', 'pressure', 'overwhelmed'
    ],
    'surprise': [
        'wow', 'shock', 'shocked', 'surprise', 'surprised', 'unbelievable', 'unexpected',
        'sudden', 'strange', 'weird', 'crazy', 'wild', 'omg'
    ]
}

def detect_dominant_emotion(text):
    """
    Analyzes text and returns the dominant emotion based on keyword frequency.
    Returns 'neutral' if no strong emotion is found.
    """
    if not text:
        return 'neutral'

    text = text.lower()
    # Tokenize simply by splitting (removes punctuation in a real NLP pipeline,
    # but here we keep it simple or use regex)
    words = re.findall(r'\w+', text)

    scores = Counter()

    for word in words:
        for emotion, keywords in EMOTION_LEXICON.items():
            if word in keywords:
                scores[emotion] += 1

    if not scores:
        return 'neutral'

    # Get the emotion with the highest count
    best_emotion, count = scores.most_common(1)[0]

    # If the count is very low relative to length, might still be neutral
    # But for now, we return the best match.
    return best_emotion
