"""Read-only Gmail calendar attachment intake; never marks mail read or sends mail."""
from __future__ import annotations

import base64
import json
import re
from urllib.parse import quote, urlencode
from urllib.request import Request, build_opener

from .travel import digest
from .travel_adapters import NoRedirect
from .travel_intake import parse_ical


def gmail_get(path, token):
    request = Request('https://gmail.googleapis.com/gmail/v1/users/me/' + path,
                      headers={'Authorization': 'Bearer ' + token})
    with build_opener(NoRedirect()).open(request, timeout=20) as response:
        return json.loads(response.read(4_000_000))


class GmailCalendarIntake:
    def __init__(self, token_provider, *, query, date_timezone=None, transport=gmail_get):
        if not query or not query.strip():
            raise ValueError('a configured travel mailbox query is required')
        self.tokens, self.query, self.date_timezone, self.transport = token_provider, query, date_timezone, transport

    def _get(self, path):
        return self.transport(path, self.tokens.get_token())

    def attachments(self, message_id):
        message = self._get('messages/' + quote(message_id, safe='') + '?format=full')
        pending = [message.get('payload', {})]
        while pending:
            part = pending.pop()
            pending.extend(part.get('parts', []))
            if part.get('mimeType', '').lower() != 'text/calendar' and not part.get('filename', '').lower().endswith('.ics'):
                continue
            body = part.get('body', {})
            if body.get('size', 0) > 2_000_000:
                raise ValueError('calendar attachment too large')
            if body.get('attachmentId'):
                body = self._get('messages/' + quote(message_id, safe='') + '/attachments/' + quote(body['attachmentId'], safe=''))
            encoded = body.get('data', '')
            if len(encoded) > 3_000_000:
                raise ValueError('calendar attachment too large')
            yield base64.b64decode(encoded + '=' * (-len(encoded) % 4), altchars=b'-_', validate=True).decode('utf-8-sig')

    def poll(self, repository, now, *, limit=25):
        if not 1 <= limit <= 100:
            raise ValueError('mail page limit must be 1..100')
        db = repository.db
        db.executescript('''CREATE TABLE IF NOT EXISTS travel_mail_seen (
            source_key TEXT PRIMARY KEY, state TEXT NOT NULL, checked_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS travel_mail_cursor (query_key TEXT PRIMARY KEY, token TEXT);''')
        query_key = digest(self.query)
        cursor = db.execute('SELECT token FROM travel_mail_cursor WHERE query_key=?', (query_key,)).fetchone()
        params = dict(q=self.query, maxResults=limit)
        if cursor and cursor['token']:
            params['pageToken'] = cursor['token']
        result = self._get('messages?' + urlencode(params))
        summary = {'messages': 0, 'bookings': 0, 'review': 0, 'failed': 0}
        for entry in result.get('messages', []):
            message_id = entry['id']
            source_key = digest(message_id)
            if db.execute('SELECT 1 FROM travel_mail_seen WHERE source_key=?', (source_key,)).fetchone():
                continue
            summary['messages'] += 1
            try:
                attachments = list(self.attachments(message_id))
            except Exception:
                summary['failed'] += 1
                continue  # Transport failure remains retryable, not accepted as data.
            state = 'accepted'
            try:
                if not attachments:
                    raise ValueError('mail needs PDF/HTML extraction review')
                parsed = []
                for content in attachments:
                    # Only an explicit provider calendar identity groups multiple
                    # segments automatically. Otherwise grouping needs review.
                    unfolded = re.sub(r'\r?\n[ \t]', '', content)
                    match = re.search(r'^X-WR-RELCALID:(.+)$', unfolded, re.M)
                    if not match:
                        raise ValueError('trip grouping identity requires review')
                    parsed.extend(parse_ical(content, trip_id=digest(match[1].strip()),
                                             evidence_ref='gmail:' + message_id, date_timezone=self.date_timezone))
                for booking in parsed:
                    repository.ingest(booking, now)
                    summary['bookings'] += 1
            except Exception:
                state = 'review'
                summary['review'] += 1
            with repository.transaction():
                db.execute('INSERT OR REPLACE INTO travel_mail_seen VALUES(?,?,?)', (source_key, state, now.isoformat()))
        # Query-specific cursors prevent a busy inbox from starving older pages.
        # A failed page retries next run. A completed sweep restarts for new mail.
        with repository.transaction():
            db.execute('INSERT OR REPLACE INTO travel_mail_cursor VALUES(?,?)', (query_key, result.get('nextPageToken')))
        return summary
