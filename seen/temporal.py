"""Calendar filters in the computer's local timezone; database timestamps are UTC epochs."""
import re
from datetime import datetime, timedelta


def interpret(query, now=None):
    # Naive local datetimes let timestamp() apply the system's DST rules for each date.
    now = now or datetime.now()
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    patterns = [
        (r"\bthis morning\b", midnight, midnight.replace(hour=12)),
        (r"\byesterday\b", midnight - timedelta(days=1), midnight),
        (r"\btoday\b", midnight, midnight + timedelta(days=1)),
        (r"\blast week\b", midnight - timedelta(days=midnight.weekday() + 7), midnight - timedelta(days=midnight.weekday())),
    ]
    for pattern, start, end in patterns:
        if re.search(pattern, query, re.I):
            return re.sub(pattern, " ", query, flags=re.I).strip(), (start.timestamp(), end.timestamp())
    match = re.search(r"\b(\d+|one|two|three|four|five|six|seven) days? ago\b", query, re.I)
    if match:
        numbers = dict(zip("one two three four five six seven".split(), range(1, 8)))
        token = match[1].lower()
        days = int(token) if token.isdigit() else numbers[token]
        if days <= 36500:
            start = midnight - timedelta(days=days)
            return query[:match.start()] + query[match.end():], (start.timestamp(), (start + timedelta(days=1)).timestamp())
    return query, None
