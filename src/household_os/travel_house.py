"""Publish staged observations to canonical HOUSE before external travel actions.

No DDL, source schema changes, or automatic calendar/category creation. The
operator must bind an existing category, owner, visibility and service identity.
"""
from __future__ import annotations

import json
from datetime import datetime
from urllib.error import HTTPError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, build_opener

from .travel import UTC, calendar_item, digest, instant
from .travel_adapters import NoRedirect


FIELDS = ('identity_key', 'title', 'description', 'category_key', 'start_date', 'end_date',
          'start_time', 'end_time', 'all_day', 'timezone', 'location', 'owner', 'visibility', 'status', 'source_agent')


def projection_hash(row):
    fields = {k: row.get(k) for k in FIELDS}
    for k in ('start_time', 'end_time'):
        if fields[k]:
            fields[k] = str(fields[k])[:8]  # PostgreSQL time normalizes seconds.
    return digest(fields)


class HouseTravelPublisher:
    def __init__(self, url, key, *, owner, visibility, category, source_agent, transport=None):
        parsed = urlparse(url)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('HOUSE service URL must be a configured HTTPS origin')
        if not all((key, owner, category, source_agent)) or visibility not in ('private', 'shared'):
            raise ValueError('explicit HOUSE owner/category/visibility/service identity required')
        self.url, self.key = url.rstrip('/'), key
        self.owner, self.visibility, self.category, self.source_agent = owner, visibility, category, source_agent
        self.request = transport or self._http

    def _http(self, method, path, body=None):
        request = Request(self.url + '/rest/v1/' + path,
                          data=json.dumps(body).encode() if body is not None else None,
                          headers={'apikey': self.key, 'Authorization': 'Bearer ' + self.key,
                                   'Content-Type': 'application/json', 'Prefer': 'return=representation'}, method=method)
        with build_opener(NoRedirect()).open(request, timeout=20) as response:
            return json.loads(response.read(1_000_000))

    def publish(self, b):
        item = calendar_item(b, 'canonical-only', 'canonical-only')
        # HOUSE currently stores time-without-timezone. UTC projection avoids DST
        # folds and preserves cross-zone instants; original local zones stay in metadata.
        if b['kind'] == 'hotel':
            sd, ed, st, et, zone = item.start_date.isoformat(), item.end_date.isoformat(), None, None, b['timezone']
        else:
            start, end = instant(b['start']), instant(b['end'])
            sd, ed, st, et, zone = start.date().isoformat(), end.date().isoformat(), start.strftime('%H:%M:%S'), end.strftime('%H:%M:%S'), 'UTC'
        identity = digest(['household-os-travel', b['trip_id'], b['booking_id']])
        row = dict(identity_key=identity, title=b['title'], description=None, category_key=self.category,
                   start_date=sd, end_date=ed, start_time=st, end_time=et, all_day=item.all_day,
                   timezone=zone, location=b['location'], owner=self.owner, visibility=self.visibility,
                   status='cancelled' if b['status'] == 'cancelled' else 'active', source_agent=self.source_agent)
        metadata = {'travel_revision': b['revision'], 'travel_observation_hash': digest(b),
                    'travel_projection_hash': projection_hash(row), 'travel_evidence_ref': b['evidence_ref'],
                    'travel_trip_id': b['trip_id'], 'travel_booking_id': b['booking_id'],
                    'travel_original_timezone': b['timezone'], 'travel_arrival_timezone': b.get('arrival_timezone')}
        def read():
            return self.request('GET', 'household_events?' + urlencode({'identity_key': 'eq.' + identity, 'select': '*'}))
        existing = read()
        if not existing:
            try:
                self.request('POST', 'household_events', {**row, 'metadata': metadata})
            except HTTPError as exc:
                if exc.code != 409:
                    raise
            existing = read()
        if len(existing) != 1:
            raise ValueError('canonical travel write/readback failed')
        old = existing[0]
        m = old.get('metadata', {})
        if old.get('source_agent') != self.source_agent or m.get('travel_projection_hash') != projection_hash(old):
            raise ValueError('canonical event changed outside travel intake; review required')
        if b['revision'] < m.get('travel_revision', 0):
            raise ValueError('canonical event is newer than staged observation')
        if b['revision'] == m.get('travel_revision') and digest(b) != m.get('travel_observation_hash'):
            raise ValueError('canonical revision conflicts with observation')
        if m.get('travel_observation_hash') != digest(b):
            # Compare-and-swap all managed fields as well as updated_at. Human
            # edits cannot be silently overwritten even if a timestamp trigger is absent.
            filters = {'id': 'eq.' + old['id'], 'updated_at': 'eq.' + old['updated_at']}
            filters.update({k: 'is.null' if old.get(k) is None else 'eq.' + (str(old[k]).lower() if isinstance(old[k], bool) else str(old[k])) for k in FIELDS})
            changed = self.request('PATCH', 'household_events?' + urlencode(filters),
                                   {**row, 'metadata': {**m, **metadata}, 'updated_at': datetime.now(UTC).isoformat()})
            if not isinstance(changed, list) or len(changed) != 1:
                raise ValueError('canonical event changed concurrently; review required')
            old = read()[0]
        if old.get('metadata', {}).get('travel_observation_hash') != digest(b) or projection_hash(old) != metadata['travel_projection_hash']:
            raise ValueError('canonical readback mismatch')
        return old['id']
