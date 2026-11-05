from __future__ import annotations

import asyncio
import datetime as dt
from types import SimpleNamespace

import pytest
from aiohttp.test_utils import TestClient, TestServer

from schedule_api import create_schedule_app
from vp_10e_plan import LessonBlock


class FakeService:
    def __init__(self, plan=None):
        self.profiles = {'luca': object(), 'jasper': object(), '8g': object()}
        self.plan = plan
        self.calls = []

    async def fetch_profile_plan(self, day, profile_id):
        self.calls.append((day, profile_id))
        return self.plan


def test_schedule_api_requires_token_and_luca_profile():
    with pytest.raises(ValueError, match='Token'):
        create_schedule_app(FakeService(), '')

    service = FakeService()
    service.profiles.pop('luca')
    with pytest.raises(ValueError, match="Profil 'luca'"):
        create_schedule_app(service, 'secret')


def test_schedule_api_rejects_missing_or_wrong_bearer_token_without_fetch():
    service = FakeService()

    async def request():
        async with TestClient(TestServer(create_schedule_app(service, 'secret'))) as client:
            response = await client.get('/api/v1/schedule/2026-11-05')
            return response.status, await response.text()

    status, body = asyncio.run(request())
    assert status == 401
    assert 'Unauthorized' in body
    assert service.calls == []


def test_schedule_api_returns_only_luca_plan_and_published_blocks():
    day = dt.date(2026, 11, 5)
    block = LessonBlock(
        profile_id='luca', profile_label='Gian', display_class='12/2', day=day,
        plan_timestamp='2026-11-05 06:00', lesson_nr='455', occurrence=0,
        course='DEU3', original_subject='DEU3', original_teacher='Meier',
        start_period=1, end_period=1, start_time='07:15', end_time='08:45',
        subject='DEU3', teacher='Meier', room='243', info='',
        subject_changed=False, teacher_changed=False, room_changed=False,
    )
    service = FakeService(SimpleNamespace(
        day=day, plan_timestamp='2026-11-05 06:00', blocks=(block,), exams=('09:05 · 90 Min.',),
    ))

    async def request():
        async with TestClient(TestServer(create_schedule_app(service, 'secret'))) as client:
            response = await client.get(
                f'/api/v1/schedule/{day.isoformat()}',
                headers={'Authorization': 'Bearer secret'},
            )
            return response.status, await response.json()

    status, body = asyncio.run(request())
    assert status == 200
    assert body['published'] is True
    assert body['blocks'][0]['teacher'] == 'Meier'
    assert body['blocks'][0]['day'] == day.isoformat()
    assert body['exams'] == ['09:05 · 90 Min.']
    assert service.calls == [(day, 'luca')]


def test_weekend_is_unpublished_without_calling_monitor():
    service = FakeService()

    async def request():
        async with TestClient(TestServer(create_schedule_app(service, 'secret'))) as client:
            response = await client.get(
                '/api/v1/schedule/2026-11-07',
                headers={'Authorization': 'Bearer secret'},
            )
            return response.status, await response.json()

    status, body = asyncio.run(request())
    assert status == 200
    assert body == {'date': '2026-11-07', 'published': False, 'blocks': [], 'exams': []}
    assert service.calls == []
