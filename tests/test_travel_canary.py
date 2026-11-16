"""Exercise travel CLI against disposable, loopback HTTPS destinations.

Run with PYTHONPATH=src python3 tests/test_travel_canary.py. Requires OpenSSL.
All input, credentials, times, account bindings, and provider responses are fixtures.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import ssl
import subprocess
import tempfile
import threading
import unittest
from collections import Counter
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from household_os import google_calendar, travel_adapters, travel_cli
from household_os.travel import digest, instant
from household_os.travel_runtime import TravelRepository


class TestDestinations:
    def __init__(self, directory):
        cert, key = directory / 'cert.pem', directory / 'key.pem'
        subprocess.run([
            'openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
            '-subj', '/CN=127.0.0.1', '-addext', 'subjectAltName=IP:127.0.0.1',
            '-keyout', str(key), '-out', str(cert),
        ], check=True, capture_output=True)
        self.cert = cert
        self.house = {}
        self.calendar = {}
        self.receipts = {}
        self.attempts = Counter()
        self.calendar_attempts = Counter()
        self.route_requests = []
        self.duration = 40
        self.route_fallback = False
        self.lose_first_calendar_ack = True
        self.lose_first_notification_ack = {'brief', 'changed'}
        self.now = instant('2030-06-10T10:00:00Z')
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def handle_request(self):
                size = int(self.headers.get('Content-Length', '0'))
                body = json.loads(self.rfile.read(size)) if size else None
                status, result = fixture.dispatch(self.command, self.path, self.headers, body)
                data = json.dumps(result).encode() if status != 204 else b''
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = handle_request

        self.server = HTTPServer(('127.0.0.1', 0), Handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert, key)
        self.server.socket = context.wrap_socket(self.server.socket, server_side=True)
        self.url = f'https://127.0.0.1:{self.server.server_port}'
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.server.shutdown()
        self.thread.join()
        self.server.server_close()

    def dispatch(self, method, url, headers, body):
        url = urlsplit(url)
        if url.path == '/rest/v1/household_events':
            if headers.get('apikey') != 'fixture-house' or headers.get('Authorization') != 'Bearer fixture-house':
                return 401, {}
            filters = parse_qs(url.query)
            if method == 'GET':
                row = self.house.get(filters['identity_key'][0].removeprefix('eq.'))
                return 200, [row] if row else []
            if method == 'POST':
                row = {**body, 'id': 'fixture-event-id', 'updated_at': self.now.isoformat()}
                self.house[body['identity_key']] = row
                return 201, [row]
            if method == 'PATCH':
                old = self.house[body['identity_key']]
                for field, (condition,) in filters.items():
                    value = old[field]
                    expected = 'is.null' if value is None else f'eq.{str(value).lower() if isinstance(value, bool) else value}'
                    if condition != expected:
                        return 200, []
                old.update(body)
                return 200, [old]
        if url.path.startswith('/calendar/v3/calendars/fixture-calendar/events'):
            if headers.get('Authorization') != 'Bearer fixture-calendar':
                return 401, {}
            self.calendar_attempts[method] += 1
            if method == 'POST':
                if body['id'] in self.calendar:
                    return 409, {'error': {'message': 'fixture already exists'}}
                self.calendar[body['id']] = body
                if self.lose_first_calendar_ack:
                    self.lose_first_calendar_ack = False
                    return 503, {}
                return 201, body
            event_id = url.path.rsplit('/', 1)[-1]
            if method == 'PUT' and event_id in self.calendar and body['id'] == event_id:
                self.calendar[event_id] = body
                return 200, body
            if method == 'DELETE' and parse_qs(url.query).get('sendUpdates') == ['none']:
                return (204, None) if self.calendar.pop(event_id, None) else (404, {})
        if url.path == '/directions/v2:computeRoutes' and method == 'POST':
            assert headers.get('X-Goog-Api-Key') == 'fixture-routes'
            assert body['routingPreference'] == 'TRAFFIC_AWARE_OPTIMAL'
            assert body['origin'] == {'address': 'Fixture hotel'}
            assert body['destination'] == {'address': 'Fixture terminal'}
            self.route_requests.append(body)
            if 'departureTime' in body and instant(body['departureTime']) <= self.now:
                return 400, {'error': {'message': 'fixture rejects past drive timestamp'}}
            result = {'routes': [{'duration': f'{self.duration * 60}s'}]}
            if self.route_fallback and 'fallbackInfo' in headers['X-Goog-FieldMask'].split(','):
                result['fallbackInfo'] = {'routingMode': 'FALLBACK_TRAFFIC_UNAWARE'}
            return 200, result
        if url.path == '/notify' and method == 'POST':
            assert headers.get('Authorization') == 'Bearer fixture-notify'
            assert body['recipient_key'] == 'fixture-recipient'
            delivery_id = headers['Idempotency-Key']
            self.attempts[delivery_id] += 1
            record = self.receipts.setdefault(delivery_id, body)
            assert record == body
            if body['kind'] in self.lose_first_notification_ack:
                self.lose_first_notification_ack.remove(body['kind'])
                return 503, {}
            return 200, {'receipt_id': f'fixture-receipt-{delivery_id}'}
        return 404, {}


def itinerary(sequence=0, start='110000', end='120000', status='CONFIRMED'):
    return f'''BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:fixture-leg@example.test
SEQUENCE:{sequence}
DTSTART;TZID=America/New_York:20300610T{start}
DTEND;TZID=America/Chicago:20300610T{end}
SUMMARY:Flight fixture
LOCATION:Fixture terminal
STATUS:{status}
END:VEVENT
END:VCALENDAR
'''


def run(directory, fixture):
    class FixtureClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixture.now.astimezone(tz) if tz else fixture.now.replace(tzinfo=None)

    def route_transport(url, body, headers):
        assert url == 'https://routes.googleapis.com/directions/v2:computeRoutes'
        return travel_adapters.post_json(fixture.url + '/directions/v2:computeRoutes', body, headers)

    def routes(api_key):
        return travel_adapters.GoogleTrafficRoutes(api_key, transport=route_transport)

    env = dict(
        SSL_CERT_FILE=str(fixture.cert), NO_PROXY='127.0.0.1',
        HOUSE_SUPABASE_URL=fixture.url, HOUSE_SUPABASE_SERVICE_ROLE_KEY='fixture-house',
        HOUSE_TRAVEL_OWNER='fixture-owner', HOUSE_TRAVEL_VISIBILITY='private',
        HOUSE_TRAVEL_CATEGORY='fixture-travel', HOUSE_TRAVEL_SOURCE_AGENT='fixture-agent',
        HOUSE_ROUTES_API_KEY='fixture-routes', HOUSE_GOOGLE_ACCESS_TOKEN='fixture-calendar',
        HOUSE_TRAVEL_NOTIFY_URL=fixture.url + '/notify', HOUSE_TRAVEL_NOTIFY_TOKEN='fixture-notify',
        HOUSE_TRAVEL_TARGET='fixture-target', HOUSE_TRAVEL_CALENDAR_REF='fixture-calendar',
        HOUSE_TRAVEL_RECIPIENTS='fixture-recipient',
    )
    database = directory / 'state.sqlite'
    booking_file = directory / 'fixture.ics'
    transfer_file = directory / 'transfer.json'
    booking_file.write_text(itinerary())
    transfer_file.write_text(json.dumps(dict(
        origin='Fixture hotel', destination='Fixture terminal', mode='drive',
        arrival_buffer_minutes=120, fallback_minutes=45, parking_minutes=20,
        recipients=['fixture-recipient'],
    )))

    def cli(*args, result=0):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            assert travel_cli.main([*args, '--db', str(database)]) == result, stdout.getvalue()
        return json.loads(stdout.getvalue())

    def ingest(source='fixture:original'):
        return cli('ingest', '--input', str(booking_file), '--trip', 'fixture-trip', '--evidence', source)['results']

    def tick(clock, *, result=0):
        fixture.now = instant(clock)
        return cli('tick', '--live', result=result)

    def read_plan():
        repo = TravelRepository(str(database))
        try:
            return json.loads(repo.db.execute('SELECT plan FROM travel_bookings').fetchone()[0])
        finally:
            repo.close()

    with (patch.dict(os.environ, env, clear=True),
          patch.object(travel_cli, 'datetime', FixtureClock),
          patch.object(travel_adapters, 'datetime', FixtureClock),
          patch.object(travel_cli, 'GoogleTrafficRoutes', routes),
          patch.object(google_calendar, 'GOOGLE_CALENDAR_API', fixture.url + '/calendar/v3')):
        assert ingest() == ['created']
        assert ingest() == ['duplicate']
        assert ingest('fixture:forwarded-copy') == ['duplicate']
        assert ingest('fixture:forwarded-copy') == ['duplicate']
        repo = TravelRepository(str(database))
        try:
            count = repo.db.execute('SELECT count(*) FROM travel_observations').fetchone()[0]
            assert count == 2
        finally:
            repo.close()
        booking_key = digest(['fixture-trip', digest('fixture-leg@example.test')])
        cli('configure-transfer', '--booking-id', booking_key, '--input', str(transfer_file))
        first = tick('2030-06-10T10:00:00Z', result=1)
        assert first['failed'] == 2 and len(fixture.calendar) == len(fixture.house) == 1
        original_id = next(iter(fixture.calendar))
        assert next(iter(fixture.house.values()))['metadata']['travel_evidence_ref'] == 'fixture:original'
        assert fixture.calendar[original_id]['visibility'] == 'private'
        retried = tick('2030-06-10T10:06:00Z')
        assert retried['calendar_written'] == retried['notified'] == 1
        assert next(iter(fixture.attempts.values())) == 2
        assert cli('status')['bookings'] == 1
        assert fixture.calendar_attempts == {'POST': 2, 'PUT': 1}
        assert fixture.calendar[original_id]['end']['dateTime'].endswith('13:00:00-04:00')

        booking_file.write_text(itinerary(1, start='111500', end='121500'))
        assert ingest() == ['updated']
        assert ingest() == ['duplicate']
        revision = tick('2030-06-10T10:09:00Z')
        assert revision['calendar_written'] == 1 and list(fixture.calendar) == [original_id]
        assert instant(fixture.calendar[original_id]['start']['dateTime']) == instant('2030-06-10T15:15:00Z')
        before = instant(read_plan()['leave_by'])
        fixture.duration = 65
        tick('2030-06-10T10:15:00Z', result=1)
        assert before - instant(read_plan()['leave_by']) == timedelta(minutes=25)
        tick('2030-06-10T10:21:00Z')
        changed = [key for key, value in fixture.receipts.items() if value['kind'] == 'changed']
        assert len(changed) == 1 and fixture.attempts[changed[0]] == 2
        assert cli('status')['notifications']['delivered'] == 3

        fixture.route_fallback = True
        fixture.duration = 15  # Routing provider returned a traffic-unaware result.
        tick('2030-06-10T10:27:00Z')
        assert read_plan()['quality'] == 'estimate' and read_plan()['travel_minutes'] == 65
        fixture.route_fallback = False
        fixture.duration = 65
        tick('2030-06-10T11:54:00Z')
        assert [r['kind'] for r in fixture.receipts.values()].count('leave_now') == 1
        assert read_plan()['quality'] == 'traffic_forecast'
        assert all('departureTime' not in request for request in fixture.route_requests[-3:])
        assert all(not value['plan']['transport_quotes_available'] for value in fixture.receipts.values())

        booking_file.write_text(itinerary(2, start='111500', end='121500', status='CANCELLED'))
        assert ingest() == ['updated']
        tick('2030-06-10T11:55:00Z')
        assert not fixture.calendar and len(fixture.house) == 1
        assert next(iter(fixture.house.values()))['status'] == 'cancelled'
        count = len(fixture.receipts)
        tick('2030-06-10T12:01:00Z')
        assert count == len(fixture.receipts) and cli('status')['bookings_with_errors'] == 0

    return {
        'canonical_rows': len(fixture.house), 'calendar_ids_created': 1, 'calendar_cancelled': True,
        'traffic_advance_minutes': 25, 'routing_fallback_quality': 'estimate',
        'unique_change_reminders': len(changed), 'change_delivery_attempts': fixture.attempts[changed[0]],
        'notification_receipt_count': count, 'live_provider_calls': 0,
    }


def canary():
    with tempfile.TemporaryDirectory(prefix='travel-canary-') as work:
        directory = Path(work)
        with TestDestinations(directory) as destinations:
            return run(directory, destinations)


class TravelCanaryTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which('openssl'), 'disposable HTTPS certificates require OpenSSL')
    def test_ics_calendar_and_departure_reminders_over_https(self):
        canary()


if __name__ == '__main__':
    print(json.dumps(canary(), sort_keys=True))
