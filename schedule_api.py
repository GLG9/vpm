"""Authenticated, Luca-only JSON view for Jarvis timetable availability."""

from __future__ import annotations

import hmac
import logging
from dataclasses import asdict
from datetime import date

from aiohttp import web

LOG = logging.getLogger("vpm.schedule_api")


def create_schedule_app(service, token: str) -> web.Application:
    if not token:
        raise ValueError("Ein Token ist für die Stundenplan-API erforderlich")
    if "luca" not in service.profiles:
        raise ValueError("Die Stundenplan-API benötigt das Profil 'luca'")

    async def schedule(request: web.Request) -> web.Response:
        supplied = request.headers.get("Authorization", "")
        expected = f"Bearer {token}"
        if not hmac.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8")):
            raise web.HTTPUnauthorized(headers={"WWW-Authenticate": "Bearer"})
        try:
            day = date.fromisoformat(request.match_info["day"])
        except ValueError as error:
            raise web.HTTPBadRequest(text="Datum muss YYYY-MM-DD sein") from error
        if day.weekday() >= 5:
            return web.json_response({"date": day.isoformat(), "published": False, "blocks": [], "exams": []})

        try:
            plan = await service.fetch_profile_plan(day, "luca")
        except Exception:
            LOG.exception("Stundenplan konnte für %s nicht geladen werden", day)
            raise web.HTTPBadGateway(text="Stundenplan momentan nicht abrufbar")
        if plan is None:
            return web.json_response({"date": day.isoformat(), "published": False, "blocks": [], "exams": []})

        blocks = []
        for block in plan.blocks:
            row = asdict(block)
            row["day"] = block.day.isoformat()
            blocks.append(row)
        return web.json_response({
            "date": plan.day.isoformat(),
            "published": True,
            "plan_timestamp": plan.plan_timestamp,
            "blocks": blocks,
            "exams": list(plan.exams),
        })

    app = web.Application(client_max_size=1024)
    app.router.add_get("/api/v1/schedule/{day}", schedule)
    return app


async def start_schedule_api(service, token: str, host: str, port: int):
    app = create_schedule_app(service, token)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    try:
        await site.start()
    except Exception:
        await runner.cleanup()
        raise
    LOG.info("Geschützte Luca-Stundenplan-API lauscht auf %s:%d", host, port)
    return runner
