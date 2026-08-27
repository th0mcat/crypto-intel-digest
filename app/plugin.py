"""Crypto Intel Digest — maubot plugin entry point.

Lifecycle
---------
``start()``
    1. Load config from ``base-config.yaml`` (via ``self.config``).
    2. Populate the module-level ``app.config.settings`` shim so that the
       rest of the ``app`` package — which imports ``from app.config import
       settings`` — gets the values from the maubot config rather than .env.
    3. Run DB migrations (idempotent).
    4. Start background asyncio tasks: heartbeat loop, digest loop, and one
       collector loop per source (RSS × n, Reddit × n, NVD).

``stop()``
    Cancel all background tasks and close the asyncpg connection pool.

Commands (``!`` prefix, operator-only)
---------------------------------------
``!help`` / ``!start``  — list available commands
``!status``             — DB reachability, schema version, uptime
``!sources``            — per-collector health (last run, consecutive failures)
``!kills``              — triage keep/kill counts for the last 24 h
``!digest``             — trigger the daily digest immediately
"""
from __future__ import annotations

import asyncio
import logging
from typing import ClassVar

from maubot import Plugin
from maubot.handlers import command
from mautrix.util.config import BaseProxyConfig, ConfigUpdateHelper

from app import VERSION, db
from app.commands import kills_text, sources_text, start_text, status_text
from app import config as _cfg_module
from app import digest as _digest_module
from app import scheduler as _scheduler_module
from app.heartbeat import heartbeat_loop
from app.notifier import MaubotNotifier


class Config(BaseProxyConfig):
    """Typed wrapper around base-config.yaml.

    ``do_update`` copies every key from the default config into the live
    config, which means new keys added in a plugin upgrade are automatically
    populated for existing installs.
    """

    def do_update(self, helper: ConfigUpdateHelper) -> None:
        helper.copy("database_url")
        helper.copy("room_id")
        helper.copy("operator_user_id")
        helper.copy("digest_hour_utc")
        helper.copy("triage_keep_threshold")
        helper.copy("rss_interval_seconds")
        helper.copy("reddit_interval_seconds")
        helper.copy("nvd_interval_seconds")
        helper.copy("reddit_client_id")
        helper.copy("reddit_client_secret")
        helper.copy("reddit_user_agent")
        helper.copy("nvd_api_key")
        helper.copy("healthcheck_url")
        helper.copy("heartbeat_interval_seconds")


class CryptoIntelPlugin(Plugin):
    """Main maubot plugin class.

    Maubot instantiates this class once per enabled instance and calls
    ``start()`` / ``stop()`` around the plugin's active lifetime.  The
    ``@command.new`` decorators register Matrix command handlers that maubot
    dispatches for every ``m.room.message`` event the bot receives.
    """

    #: Background tasks started in ``start()`` and cancelled in ``stop()``.
    _tasks: ClassVar[set[asyncio.Task]] = set()

    @classmethod
    def get_config_class(cls) -> type[Config]:
        return Config

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Initialise settings, DB, and background tasks."""
        # Merge any new keys from base-config.yaml into the stored config.
        self.config.load_and_update()

        # Populate the module-level settings shim so all app.* modules that
        # do ``from app.config import settings`` pick up these values.
        s = _cfg_module.settings
        s.database_url = self.config["database_url"]
        s.matrix_room_id = self.config["room_id"]
        s.matrix_operator_user_id = self.config["operator_user_id"]
        s.digest_hour_utc = int(self.config["digest_hour_utc"])
        s.triage_keep_threshold = float(self.config["triage_keep_threshold"])
        s.rss_interval_seconds = int(self.config["rss_interval_seconds"])
        s.reddit_interval_seconds = int(self.config["reddit_interval_seconds"])
        s.nvd_interval_seconds = int(self.config["nvd_interval_seconds"])
        s.reddit_client_id = self.config["reddit_client_id"]
        s.reddit_client_secret = self.config["reddit_client_secret"]
        s.reddit_user_agent = self.config["reddit_user_agent"]
        s.nvd_api_key = self.config["nvd_api_key"]
        s.healthcheck_url = self.config["healthcheck_url"]
        s.heartbeat_interval_seconds = int(self.config["heartbeat_interval_seconds"])

        self.log.info("Starting crypto-intel-digest v%s", VERSION)

        # Verify DB connectivity and apply any pending migrations.
        if not await db.ping():
            self.log.error("Postgres unreachable at startup — plugin disabled")
            return
        await db.migrate()
        self.log.info("DB ready")

        # Build the notifier that sends to the configured Matrix room.
        room_id = self.config["room_id"]
        notifier = MaubotNotifier(self.client, room_id)

        # Start background tasks; keep references so they can be cancelled.
        self._tasks = set()
        self._tasks.add(asyncio.create_task(heartbeat_loop()))
        self._tasks.add(asyncio.create_task(_digest_module.digest_loop(notifier)))
        _scheduler_module.start(self._tasks)

        self.log.info(
            "Plugin started — %d background tasks running", len(self._tasks)
        )

    async def stop(self) -> None:
        """Cancel background tasks and close the DB pool."""
        self.log.info("Stopping crypto-intel-digest")
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        await db.close_pool()
        self.log.info("Plugin stopped")

    # ------------------------------------------------------------------
    # Access control helper
    # ------------------------------------------------------------------

    def _is_operator(self, sender: str) -> bool:
        """Return True if *sender* is the configured operator user id.

        When ``operator_user_id`` is empty every user is treated as the
        operator (useful for testing), mirroring the old behaviour.
        """
        op = self.config["operator_user_id"]
        return not op or sender == op

    def _in_room(self, room_id: str) -> bool:
        """Return True if the event is in the configured digest room."""
        configured = self.config["room_id"]
        return not configured or room_id == configured

    # ------------------------------------------------------------------
    # Command handlers
    # ------------------------------------------------------------------

    @command.new("help", aliases=["start"])
    async def cmd_help(self, evt) -> None:
        """Show available commands."""
        if not self._is_operator(evt.sender) or not self._in_room(evt.room_id):
            return
        await evt.respond(start_text("!"))

    @command.new("status")
    async def cmd_status(self, evt) -> None:
        """Health check: DB, schema version, uptime."""
        if not self._is_operator(evt.sender) or not self._in_room(evt.room_id):
            return
        text = await status_text(healthcheck_url=self.config["healthcheck_url"])
        await evt.respond(text)

    @command.new("sources")
    async def cmd_sources(self, evt) -> None:
        """Per-collector health report."""
        if not self._is_operator(evt.sender) or not self._in_room(evt.room_id):
            return
        text = await sources_text()
        await evt.respond(text)

    @command.new("kills")
    async def cmd_kills(self, evt) -> None:
        """Triage keep/kill stats for the last 24 h."""
        if not self._is_operator(evt.sender) or not self._in_room(evt.room_id):
            return
        text = await kills_text()
        await evt.respond(text)

    @command.new("digest")
    async def cmd_digest(self, evt) -> None:
        """Send the daily digest immediately."""
        if not self._is_operator(evt.sender) or not self._in_room(evt.room_id):
            return
        await evt.respond("Building brief…")
        room_id = self.config["room_id"]
        notifier = MaubotNotifier(self.client, room_id)
        try:
            await _digest_module.send_now(notifier)
        except Exception as exc:  # pragma: no cover
            self.log.error("Digest command failed: %s", exc)
            await evt.respond(f"Error building digest: {exc}")
