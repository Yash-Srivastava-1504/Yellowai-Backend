"""
Manah Backend — Crisis Detection
Keyword matching + helpline response (same as Node version).
"""

CRISIS_KEYWORDS = [
    "suicide",
    "suicidal",
    "kill myself",
    "end my life",
    "want to die",
    "no reason to live",
    "self harm",
    "self-harm",
    "hurt myself",
    "hurting myself",
    "cutting myself",
    "i want to end it",
    "end it all",
    "not worth living",
]

HELPLINE_RESPONSE = {
    "crisis": True,
    "reply": (
        "Main yahan hoon, tumhari baat sun raha hoon 💙\n\n"
        "If you're going through something really tough right now, please know you're not alone. "
        "Trained counsellors are available right now — completely free and confidential:\n\n"
        "📞 **iCall**: 9152987821 (Mon–Sat, 8am–10pm)\n"
        "📞 **KIRAN Mental Health Helpline**: 1800-599-0019 (24/7, FREE)\n"
        "📞 **Vandrevala Foundation**: 1860-2662-345 (24/7)\n\n"
        "Please reach out to them. I care about you, and I'm here to keep talking too. 💙"
    ),
    "helplines": [
        {"name": "iCall", "number": "9152987821", "hours": "Mon–Sat, 8am–10pm"},
        {"name": "KIRAN", "number": "1800-599-0019", "hours": "24/7 FREE"},
        {"name": "Vandrevala Foundation", "number": "1860-2662-345", "hours": "24/7"},
    ],
}


def detect_crisis(message: str) -> bool:
    """Returns True if the message contains any crisis keywords."""
    lower = (message or "").lower()
    return any(kw in lower for kw in CRISIS_KEYWORDS)
