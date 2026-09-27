"""User-reported daily observations, not diagnostic scores or device measurements."""
import datetime
import math
import re

FIELDS = ('sleep_hours', 'sleep_start', 'sleep_end', 'mood', 'energy')

def validate(body):
    day = body.get('date')
    if not isinstance(day, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', day):
        raise ValueError('invalid_date')
    datetime.date.fromisoformat(day)
    values = {}
    for field in FIELDS:
        value = body.get(field)
        if value is None or value == '':
            values[field] = None
        elif field in ('sleep_start', 'sleep_end'):
            if not isinstance(value, str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', value):
                raise ValueError('invalid_time')
            values[field] = value
        elif field == 'sleep_hours':
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 24:
                raise ValueError('invalid_sleep')
            values[field] = round(value, 2)
        else:
            if type(value) is not int or value not in range(-2, 3):
                raise ValueError('invalid_feeling')
            values[field] = value
    return day, {**values, 'date': day, 'source': 'self_report'}
