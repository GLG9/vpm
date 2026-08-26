"""Discord-Bot für persönliche Indiware-Vertretungspläne."""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import tempfile
from collections import defaultdict
from pathlib import Path

import discord
import requests
from discord.ext import commands
from dotenv import load_dotenv

from monitor_config import AppConfig, load_config
from monitor_service import MonitorService
from monitor_state import Delivery, StateStore
from notification_format import (
    NotificationField,
    NotificationSpec,
    block_label,
    build_notification_specs,
    german_date,
    paginate_fields,
)
from vp_10e_plan import ProfilePlan

LOG = logging.getLogger("vpm")


def configure_logging() -> None:
    Path("state").mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler("state/monitor.log", encoding="utf-8"),
        ],
    )


def to_embed(spec: NotificationSpec) -> discord.Embed:
    embed = discord.Embed(
        title=spec.title,
        description=spec.description,
        color=spec.color,
    )
    for field in spec.fields:
        embed.add_field(name=field.name, value=field.value, inline=field.inline)
    if spec.footer:
        embed.set_footer(text=spec.footer)
    return embed


def specs_for_deliveries(deliveries: list[Delivery]) -> list[NotificationSpec]:
    groups: dict[tuple, list[Delivery]] = defaultdict(list)
    for delivery in deliveries:
        event = delivery.event
        groups[
            (
                delivery.status,
                event.profile_id,
                event.day,
                event.kind,
            )
        ].append(delivery)
    specs: list[NotificationSpec] = []
    for key in sorted(groups, key=lambda value: (value[2], value[1], value[0], value[3].value)):
        specs.extend(
            build_notification_specs(
                sorted(groups[key], key=lambda item: item.event.start_period)
            )
        )
    return specs


def plan_specs(plan: ProfilePlan, title: str) -> list[NotificationSpec]:
    fields: list[NotificationField] = []
    for block in plan.blocks:
        lines = [f"📚 {block.course}"]
        if block.teacher:
            lines.append(f"👩‍🏫 {block.teacher}")
        if block.room:
            lines.append(f"📍 Raum {block.room}")
        if block.info:
            lines.append(f"📝 {block.info}")
        fields.append(
            NotificationField(
                name=(
                    f"{block_label(block.start_period, block.end_period)} · "
                    f"{block.start_time or '--'}–{block.end_time or '--'}"
                ),
                value="\n".join(lines),
            )
        )
    if not fields:
        fields.append(NotificationField("Status", "Keine ausgewählten Stunden."))
    if plan.general_notes:
        fields.append(
            NotificationField(
                "Allgemeine Hinweise",
                "\n".join(f"• {note}" for note in plan.general_notes),
            )
        )
    if plan.exams:
        fields.append(
            NotificationField(
                "Klausuren", "\n".join(f"• {exam}" for exam in plan.exams)
            )
        )
    embed_title = f"📅 {title} · {plan.profile.label}"
    description = german_date(plan.day)
    footer = f"Planstand: {plan.plan_timestamp or 'unbekannt'}"
    return [
        NotificationSpec(
            title=embed_title,
            description=description,
            color=0x5865F2,
            fields=page,
            footer=footer,
        )
        for page in paginate_fields(
            fields,
            title=embed_title,
            description=description,
            footer=footer,
        )
    ]


class PlanCommands(commands.Cog):
    def __init__(self, bot: MonitorBot) -> None:
        self.bot = bot

    async def _send(
        self,
        ctx: commands.Context,
        day: dt.date,
        title: str,
        profile_id: str | None,
    ) -> None:
        profile_key = (profile_id or "").casefold()
        if profile_key not in self.bot.service.profiles:
            names = ", ".join(self.bot.service.profiles)
            await ctx.send(f"Bitte Profil angeben: `{names}`")
            return
        try:
            plan = await self.bot.service.fetch_profile_plan(day, profile_key)
        except (requests.RequestException, ValueError) as exc:
            LOG.warning("Planbefehl fehlgeschlagen: %s", exc)
            await ctx.send("Plan ist momentan nicht verfügbar.")
            return
        if plan is None:
            await ctx.send(f"Für den {day:%d.%m.%Y} ist kein Plan verfügbar.")
            return
        for spec in plan_specs(plan, title):
            await ctx.send(embed=to_embed(spec))

    @commands.command(name="heute")
    async def today(self, ctx: commands.Context, profile: str | None = None) -> None:
        await self._send(ctx, dt.datetime.now(self.bot.config.timezone).date(), "Heute", profile)

    @commands.command(name="morgen")
    async def tomorrow(self, ctx: commands.Context, profile: str | None = None) -> None:
        day = dt.datetime.now(self.bot.config.timezone).date() + dt.timedelta(days=1)
        await self._send(ctx, day, "Morgen", profile)

    @commands.command(name="übermorgen", aliases=["uebermorgen"])
    async def day_after(self, ctx: commands.Context, profile: str | None = None) -> None:
        day = dt.datetime.now(self.bot.config.timezone).date() + dt.timedelta(days=2)
        await self._send(ctx, day, "Übermorgen", profile)


class MonitorBot(commands.Bot):
    def __init__(self, config: AppConfig) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)
        self.config = config
        self.service = MonitorService(config)
        self.monitor_task: asyncio.Task | None = None

    async def setup_hook(self) -> None:
        await self.add_cog(PlanCommands(self))
        self.monitor_task = asyncio.create_task(
            self._monitor_forever(), name="vertretungsplan-monitor"
        )

    async def close(self) -> None:
        if self.monitor_task:
            self.monitor_task.cancel()
        await super().close()

    async def on_ready(self) -> None:
        LOG.info("Bot online: %s", self.user)

    async def _channel(self) -> discord.abc.Messageable:
        channel = self.get_channel(self.config.channel_id)
        if channel is None:
            channel = await self.fetch_channel(self.config.channel_id)
        return channel

    async def _send_specs(self, specs: list[NotificationSpec]) -> None:
        channel = await self._channel()
        for spec in specs:
            await channel.send(embed=to_embed(spec))

    async def _run_scan(self) -> None:
        now = dt.datetime.now(self.config.timezone)
        result = await self.service.scan(now)
        for error in result.errors:
            LOG.warning("Abruffehler: %s", error)
        if result.fetched_days:
            LOG.info(
                "Neue Pläne geladen: %s",
                ", ".join(day.isoformat() for day in result.fetched_days),
            )

        if result.deliveries:
            deliveries = list(result.deliveries)
            try:
                await self._send_specs(specs_for_deliveries(deliveries))
            except discord.DiscordException:
                LOG.exception("Discord-Versand fehlgeschlagen; wird wiederholt")
            else:
                self.service.acknowledge_deliveries(deliveries)

        for profile_id in result.overview_profiles:
            try:
                await self._send_specs(self.service.overview_specs(profile_id))
            except discord.DiscordException:
                LOG.exception("Überblick für %s fehlgeschlagen", profile_id)
            else:
                self.service.acknowledge_overview(profile_id, now)

    async def _monitor_forever(self) -> None:
        await self.wait_until_ready()
        while not self.is_closed():
            started = asyncio.get_running_loop().time()
            try:
                await self._run_scan()
            except asyncio.CancelledError:
                raise
            except Exception:
                LOG.exception("Monitorlauf fehlgeschlagen")
            elapsed = asyncio.get_running_loop().time() - started
            await asyncio.sleep(max(1, self.config.check_seconds - elapsed))


def render_console(spec: NotificationSpec) -> str:
    lines = [spec.title, spec.description]
    for field in spec.fields:
        lines.extend((f"\n{field.name}", field.value))
    if spec.footer:
        lines.append(f"\n{spec.footer}")
    return "\n".join(lines)


async def dry_run(config: AppConfig) -> int:
    """Ein echter Abruf ohne Discord und ohne produktiven Zustand."""

    with tempfile.TemporaryDirectory(prefix="vpm-dry-run-") as directory:
        service = MonitorService(
            config,
            store=StateStore(Path(directory) / "monitor.json"),
        )
        now = dt.datetime.now(config.timezone)
        result = await service.scan(now, force=True)
        for error in result.errors:
            print(f"WARNUNG: {error}")
        print(
            "Geladene Pläne:",
            ", ".join(day.isoformat() for day in result.fetched_days) or "keine neuen",
        )
        for profile in config.profiles:
            for spec in service.overview_specs(profile.profile_id):
                print("\n" + render_console(spec))
        return 1 if result.errors and not service.state.initialized else 0


def main() -> int:
    load_dotenv()
    configure_logging()
    try:
        config = load_config()
    except ValueError as exc:
        LOG.error("Konfigurationsfehler: %s", exc)
        return 2
    if config.dry_run:
        return asyncio.run(dry_run(config))
    bot = MonitorBot(config)
    bot.run(config.discord_token, log_handler=None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
