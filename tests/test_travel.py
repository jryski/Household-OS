"""Synthetic travel acceptance and regression fixtures only."""
import copy
import json
import tempfile
import threading
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from household_os.travel import (UTC, calendar_item, compare_options, departure_plan,
                                 instant, validate_booking)
from household_os.travel_runtime import TravelRepository, TravelWorker
from household_os.travel_intake import parse_ical
from household_os.travel_adapters import GoogleTrafficRoutes, NotificationWebhook, TravelGoogleCalendar
from household_os.google_calendar import GoogleApiError, GoogleTokenProvider, render_google_event
from household_os.calendar_sync import ProviderCapabilities
from household_os.travel_cli import main

NOW = instant('2030-06-10T10:00:00Z')


def booking():
    return dict(trip_id='trip-demo', booking_id='leg-1', revision=1, kind='flight',
                title='Flight demo', evidence_ref='fixture:booking', location='Airport demo',
                timezone='America/New_York', start='2030-06-10T12:00:00-04:00',
                end='2030-06-10T14:00:00-04:00', transfer=dict(origin='Origin demo',
                    destination='Airport demo terminal', mode='drive', arrival_buffer_minutes=120,
                    fallback_minutes=60, parking_minutes=20, contingency_minutes=10,
                    recipients=['person-1']))


def ical(start='DTSTART;TZID=America/New_York:20300610T120000', end='DTEND;TZID=America/Chicago:20300610T133000', extra=''):
    return f'''BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:event-demo
DTSTAMP:20300601T000000Z
SUMMARY:FLIGHT - demo
LOCATION:Airport demo
{start}
{end}
{extra}
END:VEVENT
END:VCALENDAR
'''


class ModelTests(unittest.TestCase):
    def test_departure_includes_traffic_parking_and_contingency(self):
        b = validate_booking(booking())
        p = departure_plan(b, NOW)
        self.assertEqual(instant(p['leave_by']), instant('2030-06-10T12:30:00Z'))
        self.assertEqual(p['quality'], 'estimate')

    def test_exact_route_and_refinement(self):
        calls = []
        def route(origin, dest, departure, mode):
            calls.append(departure)
            return dict(minutes=80, observed_at=NOW.isoformat(), origin=origin,
                        destination=dest, mode=mode, source='synthetic traffic')
        p = departure_plan(booking(), NOW, route)
        self.assertEqual(instant(p['leave_by']), instant('2030-06-10T12:10:00Z'))
        self.assertEqual(p['quality'], 'traffic_forecast')
        self.assertEqual(len(calls), 3)
        self.assertLess(calls[-1], instant(booking()['start']))

    def test_route_observed_after_http_request_is_accepted(self):
        def route(origin,dest,departure,mode):
            return dict(minutes=80,observed_at=(NOW+timedelta(seconds=2)).isoformat(),
                        origin=origin,destination=dest,mode=mode,source='fixture')
        self.assertEqual(departure_plan(booking(),NOW,route)['quality'],'traffic_forecast')

    def test_route_from_future_is_rejected(self):
        def route(origin,dest,departure,mode):
            return dict(minutes=80,observed_at=(NOW+timedelta(hours=1)).isoformat(),
                        origin=origin,destination=dest,mode=mode,source='fixture')
        self.assertEqual(departure_plan(booking(),NOW,route)['quality'],'estimate')

    def test_stale_route_uses_conservative_previous(self):
        def stale(*args):
            return dict(minutes=5, observed_at=(NOW-timedelta(hours=1)).isoformat())
        p = departure_plan(booking(), NOW, stale, {'travel_minutes': 100})
        self.assertEqual(p['travel_minutes'], 100)
        self.assertEqual(p['quality'], 'estimate')

    def test_delayed_operational_departure_does_not_relax_deadline(self):
        b = booking(); b['operational_departure'] = '2030-06-10T18:00:00Z'
        self.assertEqual(departure_plan(b, NOW)['arrive_by'], '2030-06-10T14:00:00+00:00')

    def test_train_from_hotel_has_local_leave_message(self):
        b=booking(); b['kind']='train'; b['transfer']['origin']='Hotel demo'; b['transfer']['mode']='taxi'
        b['transfer']['origin_timezone']='America/New_York'
        plan=departure_plan(validate_booking(b),NOW)
        self.assertEqual(plan['origin'],'Hotel demo')
        self.assertIn('EDT',plan['message'])
        self.assertFalse(plan['transport_quotes_available'])

    def test_earlier_cutoff_wins(self):
        b = booking(); b['transfer']['cutoff_at'] = '2030-06-10T13:00:00Z'
        self.assertEqual(departure_plan(b, NOW)['arrive_by'], '2030-06-10T13:00:00+00:00')

    def test_arrival_other_zone_is_same_instant_on_calendar(self):
        b = booking(); b['arrival_timezone'] = 'America/Chicago'; b['end'] = '2030-06-10T13:00:00-05:00'
        item = calendar_item(validate_booking(b), 'target-demo', 'calendar-demo')
        rendered = render_google_event(item, ProviderCapabilities()).body
        self.assertEqual(instant(rendered['end']['dateTime']), instant(b['end']))

    def test_hotel_checkout_exclusive(self):
        b = booking(); b.update(kind='hotel', start='2030-06-10', end='2030-06-13'); b.pop('transfer')
        item = calendar_item(validate_booking(b), 'target-demo', 'calendar-demo')
        rendered = render_google_event(item, ProviderCapabilities()).body
        self.assertEqual(rendered['end']['date'], '2030-06-13')

    def test_reject_bad_zone_offset_nonexistent_time(self):
        b = booking(); b['start'] = '2030-03-10T02:30:00-05:00'
        with self.assertRaises(ValueError): validate_booking(b)

    def test_reject_missing_origin_buffer_or_recipient(self):
        for key in ('origin', 'arrival_buffer_minutes', 'recipients'):
            b = booking(); del b['transfer'][key]
            with self.subTest(key=key), self.assertRaises((ValueError, KeyError)): validate_booking(b)

    def test_negative_and_nonfinite_durations_rejected(self):
        for value in (-1, float('inf'), True):
            b = booking(); b['transfer']['fallback_minutes'] = value
            with self.subTest(value=value), self.assertRaises(ValueError): validate_booking(b)

    def test_quote_total_capacity_and_freshness(self):
        q = dict(provider='taxi-demo', price_kind='published_fare', price=35, fees=5, parking=10,
                 return_price=35, currency='USD', source_ref='fixture:tariff', observed_at=NOW.isoformat(),
                 travel_minutes=40, pickup_minutes=10, passenger_capacity=4, bag_capacity=3)
        compared = compare_options([q], NOW, passengers=2, bags=2)[0]
        self.assertEqual(compared['total_cost'], 85)
        self.assertEqual(compared['total_minutes'], 50)
        self.assertTrue(compared['comparable'])
        self.assertFalse(compare_options([q], NOW+timedelta(hours=1))[0]['comparable'])
        self.assertFalse(compare_options([q], NOW, passengers=6)[0]['comparable'])

    def test_missing_quote_is_not_invented(self):
        q = dict(provider='ride-demo', price_kind='unavailable', observed_at=NOW.isoformat())
        self.assertIsNone(compare_options([q], NOW)[0]['total_cost'])


class IntakeTests(unittest.TestCase):
    def test_ics_cross_zone_and_folded_lines(self):
        content = ical().replace('SUMMARY:FLIGHT - demo', 'SUMMARY:FLIGHT - de\r\n mo')
        b = parse_ical(content, trip_id='trip-demo', evidence_ref='fixture:ics')[0]
        self.assertEqual(b['title'], 'FLIGHT - demo')
        self.assertEqual(b['arrival_timezone'], 'America/Chicago')
        self.assertEqual((instant(b['end'])-instant(b['start'])).total_seconds(), 9000)

    def test_sequence_and_cancel(self):
        b = parse_ical(ical(extra='SEQUENCE:3\nSTATUS:CANCELLED'), trip_id='trip-demo', evidence_ref='fixture:ics')[0]
        self.assertEqual(b['revision'], 4); self.assertEqual(b['status'], 'cancelled')

    def test_recurrence_floating_and_ambiguous_rejected(self):
        for data in (ical(extra='RRULE:FREQ=DAILY'), ical(start='DTSTART:20300610T120000'),
                     ical(start='DTSTART;TZID=America/New_York:20301103T013000')):
            with self.assertRaises(ValueError): parse_ical(data, trip_id='trip-demo', evidence_ref='fixture:ics')

    def test_ignores_timezone_recurrences_and_alarm(self):
        data = ical().replace('BEGIN:VEVENT', 'BEGIN:VTIMEZONE\nRRULE:FREQ=YEARLY\nEND:VTIMEZONE\nBEGIN:VEVENT')
        data = data.replace('END:VEVENT', 'BEGIN:VALARM\nACTION:DISPLAY\nDESCRIPTION:ignore\nEND:VALARM\nEND:VEVENT')
        self.assertEqual(len(parse_ical(data, trip_id='trip-demo', evidence_ref='fixture:ics')), 1)

    def test_unrecognized_event_requires_kind(self):
        with self.assertRaises(ValueError):
            parse_ical(ical().replace('FLIGHT', 'Dinner'), trip_id='trip-demo', evidence_ref='fixture:ics')


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.repo = TravelRepository(':memory:')
        self.addCleanup(self.repo.close)

    def worker(self, **kwargs):
        return TravelWorker(self.repo, recipients=['person-1'], **kwargs)

    def test_duplicate_stale_and_conflicting_revisions(self):
        b = booking(); self.assertEqual(self.repo.ingest(b, NOW), 'created')
        self.assertEqual(self.repo.ingest(b, NOW), 'duplicate')
        b['revision']=2; self.assertEqual(self.repo.ingest(b, NOW), 'updated')
        self.assertEqual(self.repo.ingest(booking(), NOW), 'stale')
        b['title']='different'
        with self.assertRaises(ValueError): self.repo.ingest(b, NOW)

    def test_repeated_tick_only_delivers_once(self):
        calls=[]
        self.repo.ingest(booking(), NOW)
        worker=self.worker(notify=lambda *args: calls.append(args) or 'receipt-demo')
        worker.tick(NOW); worker.tick(NOW+timedelta(minutes=6))
        self.assertEqual(len(calls), 1)

    def test_retry_after_restart_and_cancellation(self):
        def fail(*args): raise RuntimeError('private payload must not be logged')
        self.repo.ingest(booking(), NOW)
        self.assertEqual(self.worker(notify=fail).tick(NOW)['failed'], 1)
        delivered=[]
        self.worker(notify=lambda *args: delivered.append(args) or 'receipt-demo').tick(NOW+timedelta(minutes=3))
        self.assertEqual(len(delivered),1)
        b=booking(); b.update(revision=2,status='cancelled'); self.repo.ingest(b,NOW)
        self.assertEqual(self.worker(notify=fail).tick(NOW+timedelta(minutes=6))['failed'],0)

    def test_revision_invalidates_pending_alerts(self):
        self.repo.ingest(booking(),NOW); self.worker().tick(NOW)
        b=booking(); b['revision']=2; b['start']='2030-06-11T12:00:00-04:00'; b['end']='2030-06-11T14:00:00-04:00'
        self.repo.ingest(b,NOW)
        self.assertEqual(self.repo.db.execute("SELECT count(*) FROM travel_notifications WHERE state='pending'").fetchone()[0],0)

    def test_no_catchup_spam_after_deadline(self):
        calls=[]; self.repo.ingest(booking(),NOW)
        self.worker(notify=lambda *args: calls.append(args) or 'receipt-demo').tick(NOW+timedelta(hours=10))
        self.assertEqual(calls,[])

    def test_only_latest_stage_when_first_tick_late(self):
        calls=[]; self.repo.ingest(booking(),NOW)
        self.worker(notify=lambda *args: calls.append(args) or 'receipt-demo').tick(NOW+timedelta(hours=3))
        self.assertEqual([c[1] for c in calls],['leave_now'])

    def test_revoked_recipient_never_sent(self):
        self.repo.ingest(booking(),NOW); self.worker().tick(NOW)
        calls=[]
        TravelWorker(self.repo,notify=lambda *args: calls.append(args) or 'receipt-demo',recipients=[]).tick(NOW+timedelta(minutes=6))
        self.assertFalse(calls)

    def test_calendar_receipt_idempotence_and_cancellation(self):
        calls=[]
        class Calendar:
            def upsert(self,item): calls.append(('upsert',item.event_id))
            def delete(self,item): calls.append(('delete',item.event_id))
        self.repo.ingest(booking(),NOW)
        worker=self.worker(calendar=Calendar(),target='target-demo',calendar_ref='calendar-demo')
        worker.tick(NOW);worker.tick(NOW+timedelta(minutes=6))
        b=booking();b.update(revision=2,status='cancelled');self.repo.ingest(b,NOW)
        worker.tick(NOW+timedelta(minutes=7))
        self.assertEqual([c[0] for c in calls],['upsert','delete'])
        self.assertEqual(calls[0][1],calls[1][1])

    def test_two_local_workers_do_not_duplicate_delivery(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=str(Path(tmp)/'state.sqlite');repo=TravelRepository(path);repo.ingest(booking(),NOW);repo.close()
            calls=[]
            def run():
                r=TravelRepository(path)
                try: TravelWorker(r,recipients=['person-1'],notify=lambda *args:calls.append(args) or 'receipt-demo').tick(NOW)
                finally:r.close()
            threads=[threading.Thread(target=run) for _ in range(2)]
            for t in threads:t.start()
            for t in threads:t.join()
            self.assertEqual(len(calls),1)

    def test_dry_run_leaves_persistent_state_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=str(Path(tmp)/'state.sqlite');r=TravelRepository(path);r.ingest(booking(),NOW);r.close()
            with patch('builtins.print'): self.assertEqual(main(['tick','--db',path]),0)
            r=TravelRepository(path)
            self.assertIsNone(r.db.execute('SELECT next_check FROM travel_bookings').fetchone()[0]);r.close()


class AdapterTests(unittest.TestCase):
    def test_google_route_headers_and_departure(self):
        calls=[]
        route=GoogleTrafficRoutes('fixture-token',lambda *args:calls.append(args) or {'routes':[{'duration':'601.2s'}]})
        result=route('Origin demo','Airport demo',NOW,'drive')
        self.assertEqual(result['minutes'],11)
        self.assertEqual(calls[0][1]['routingPreference'],'TRAFFIC_AWARE_OPTIMAL')
        self.assertNotIn('fixture-token',calls[0][0])

    def test_webhook_requires_receipt_and_fixed_https_endpoint(self):
        with self.assertRaises(ValueError): NotificationWebhook('http://invalid.test','token')
        hook=NotificationWebhook('https://notify.example.test/receive','fixture-token',lambda *args:{})
        with self.assertRaises(ValueError): hook('person-1','brief',{},'key-demo')

    def test_calendar_delete_absent_is_idempotent(self):
        for code in (404,410):
            def transport(*args):raise GoogleApiError(code,'missing')
            calendar=TravelGoogleCalendar(GoogleTokenProvider({'HOUSE_GOOGLE_ACCESS_TOKEN':'fixture-token'}),transport=transport)
            calendar.delete(calendar_item(booking(),'target-demo','calendar-demo'))




class ExtendedRuntimeTests(unittest.TestCase):
    setUp = RuntimeTests.setUp
    worker = RuntimeTests.worker
    def test_manual_transfer_survives_booking_update(self):
        from household_os.travel import digest
        b=booking(); self.repo.ingest(b,NOW)
        key=digest([b['trip_id'],b['booking_id']])
        override=copy.deepcopy(b['transfer']); override['origin']='Hotel demo'; override['fallback_minutes']=90
        self.repo.configure_transfer(key,override)
        b['revision']=2; b.pop('transfer'); self.repo.ingest(b,NOW)
        self.worker().tick(NOW)
        plan=json.loads(self.repo.db.execute('SELECT plan FROM travel_bookings').fetchone()[0])
        self.assertEqual(plan['travel_minutes'],90)

    def test_changed_route_supersedes_pending_advice(self):
        b=booking(); self.repo.ingest(b,NOW); self.worker().tick(NOW)
        def route(origin,dest,departure,mode):
            return dict(minutes=90, observed_at=(NOW+timedelta(minutes=6)).isoformat(),origin=origin,destination=dest,mode=mode,source='fixture')
        self.worker(route=route).tick(NOW+timedelta(minutes=6))
        pending=self.repo.db.execute("SELECT payload FROM travel_notifications WHERE state='pending'").fetchall()
        self.assertTrue(pending)
        for row in pending:
            self.assertEqual(json.loads(row['payload'])['travel_minutes'],90)

    def test_canonical_conflict_blocks_calendar_and_notifications(self):
        calls=[]
        class Canonical:
            def publish(self,b): raise ValueError('human edit conflict')
        self.repo.ingest(booking(),NOW)
        self.worker(canonical=Canonical(),notify=lambda *args:calls.append(args)).tick(NOW)
        self.assertFalse(calls)
        self.assertIn('canonical_conflict',self.repo.db.execute('SELECT last_error FROM travel_bookings').fetchone()[0])


class HousePublisherTests(unittest.TestCase):
    def publisher(self,transport):
        from household_os.travel_house import HouseTravelPublisher
        return HouseTravelPublisher('https://house.example.test','fixture-token',owner='person-demo',
                    visibility='private',category='travel',source_agent='agent-demo',transport=transport)

    def fake(self):
        state=[]
        def request(method,path,body=None):
            if method=='GET': return copy.deepcopy(state)
            if method=='POST': state.append({**copy.deepcopy(body),'id':'event-demo','updated_at':NOW.isoformat()}); return state
            if method=='PATCH': state[0].update(copy.deepcopy(body)); return state
        return state,request

    def test_publish_readback_duplicate_revision_update(self):
        state,request=self.fake(); publisher=self.publisher(request); b=validate_booking(booking())
        self.assertEqual(publisher.publish(b),'event-demo')
        publisher.publish(b); self.assertEqual(len(state),1)
        b['revision']=2; b['title']='Updated demo'; publisher.publish(b)
        self.assertEqual(state[0]['title'],'Updated demo')
        self.assertEqual(state[0]['timezone'],'UTC')

    def test_manual_edit_is_preserved(self):
        state,request=self.fake(); publisher=self.publisher(request); b=validate_booking(booking())
        publisher.publish(b); state[0]['title']='Manual title'
        b['revision']=2
        with self.assertRaises(ValueError): publisher.publish(b)
        self.assertEqual(state[0]['title'],'Manual title')

    def test_concurrent_change_is_not_overwritten(self):
        state,request=self.fake(); publisher=self.publisher(request); b=validate_booking(booking()); publisher.publish(b)
        def racing(method,path,body=None):
            return [] if method=='PATCH' else request(method,path,body)
        publisher.request=racing; b['revision']=2; b['title']='Updated demo'
        with self.assertRaises(ValueError):publisher.publish(b)


class MailIntakeTests(unittest.TestCase):
    def test_ics_attachment_ingest_is_read_only_and_idempotent(self):
        import base64
        from household_os.travel_mail import GmailCalendarIntake
        data=ical().replace('VERSION:2.0','VERSION:2.0\nX-WR-RELCALID:trip-demo')
        encoded=base64.urlsafe_b64encode(data.encode()).decode()
        calls=[]
        def transport(path,token):
            calls.append(path)
            if path.startswith('messages?'):return {'messages':[{'id':'mail-demo'}]}
            return {'payload':{'parts':[{'mimeType':'text/calendar','filename':'calendar.ics','body':{'data':encoded}}]}}
        repo=TravelRepository(':memory:');self.addCleanup(repo.close)
        intake=GmailCalendarIntake(GoogleTokenProvider({'HOUSE_GOOGLE_ACCESS_TOKEN':'fixture-token'}),query='label:travel-demo',transport=transport)
        self.assertEqual(intake.poll(repo,NOW)['bookings'],1)
        self.assertEqual(intake.poll(repo,NOW)['messages'],0)
        self.assertFalse(any('modify' in path or 'send' in path for path in calls))

    def test_mail_without_supported_calendar_is_reviewable(self):
        from household_os.travel_mail import GmailCalendarIntake
        def transport(path,token):
            return {'messages':[{'id':'mail-demo'}]} if path.startswith('messages?') else {'payload':{'mimeType':'text/html'}}
        repo=TravelRepository(':memory:');self.addCleanup(repo.close)
        intake=GmailCalendarIntake(GoogleTokenProvider({'HOUSE_GOOGLE_ACCESS_TOKEN':'fixture-token'}),query='label:travel-demo',transport=transport)
        self.assertEqual(intake.poll(repo,NOW)['review'],1)
        self.assertEqual(repo.db.execute('SELECT state FROM travel_mail_seen').fetchone()[0],'review')


if __name__=='__main__': unittest.main()
