import random

WRITING_PROMPTS = [
    "What made you smile today?",
    "Describe a place where you felt perfectly content.",
    "What is one thing you want to achieve this week?",
    "Who are you most grateful for right now and why?",
    "If you could talk to your younger self, what would you say?",
    "What is a challenge you overcame recently?",
    "Describe your perfect day.",
    "What is something new you learned today?",
    "How are you feeling right now, really?",
    "What is a small win you had today?",
    "Write about a song that means a lot to you.",
    "What is your favorite memory from childhood?",
    "If you could travel anywhere, where would you go?",
    "What is a fear you want to conquer?",
    "Write a letter to your future self.",
    "What are three things you like about yourself?",
    "Describe a dream you had recently.",
    "What is the best advice you've ever received?",
    "What is something you're looking forward to?",
    "If you had a superpower, what would it be?"
]

def get_random_prompt():
    return random.choice(WRITING_PROMPTS)
