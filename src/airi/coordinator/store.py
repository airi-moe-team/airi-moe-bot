"""Durable single-process channel scheduler and participation policy enforcement."""

from __future__ import annotations

import json
import logging
import math
import re
import sqlite3
import time
import uuid

from .policy import ParticipationPolicy

log = logging.getLogger(__name__)
DECISION_REASONS = frozenset(
    {
        "invitation",
        "relevant",
        "sibling",
        "no_contribution",
        "humans_talking",
        "repetition",
        "error",
    }
)
TERMINAL = frozenset({"published", "silent", "failed", "cancelled", "decided"})


class Conflict(ValueError):
    pass


class ChannelCoordinator:
    def __init__(
        self,
        path,
        bots,
        *,
        channel_id,
        clock=time.time,
        debounce=3,
        reply_delay=None,
        ttl=360,
        worker_ttl=45,
        policy=None,
    ):
        if (
            len(bots) != 2
            or len(set(bots.values())) != 2
            or any(
                not isinstance(uid, str) or not uid.isdigit() or int(uid) <= 0
                for uid in bots.values()
            )
        ):
            raise ValueError("Exactly two distinct bot identities are required")
        self.bots = dict(bots)
        self.primary = next(iter(bots))
        self.channel = str(channel_id)
        if not self.channel.isdigit() or int(self.channel) <= 0:
            raise ValueError("A positive Discord channel id is required")
        self.policy = policy or ParticipationPolicy()
        self.clock, self.debounce = clock, debounce
        self.reply_delay = self.policy.turn_delay_seconds if reply_delay is None else reply_delay
        self.ttl, self.worker_ttl = ttl, worker_ttl
        if any(not math.isfinite(v) or v < 0 for v in (debounce, self.reply_delay)):
            raise ValueError("Invalid coordinator interval")
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, status TEXT NOT NULL,
                bot TEXT NOT NULL, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS state(key TEXT PRIMARY KEY, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS rounds(id TEXT PRIMARY KEY, payload TEXT NOT NULL);
        """)
        configuration = json.dumps({"bots": self.bots, "channel": self.channel}, sort_keys=True)
        saved = self.db.execute("SELECT payload FROM state WHERE key='configuration'").fetchone()
        if saved and saved[0] != configuration:
            self.db.close()
            raise ValueError(
                "Database belongs to different Discord identities/channel; use a separate database"
            )
        with self.db:
            self.db.execute(
                "INSERT OR IGNORE INTO state VALUES ('configuration',?)", (configuration,)
            )
            state = self._state()
            state.setdefault("activity_at", self.clock())
            state.setdefault("proactive_next", self.primary)
            state.setdefault("cooldown_until", 0)
            state.setdefault("daily_counts", {})
            # Resume with one future opportunity, never replay missed idle ticks.
            state["next_proactive_at"] = max(
                state.get("next_proactive_at", 0), self.clock() + self.policy.recheck_seconds
            )
            self._save_state(state)
            for row in self.db.execute(
                "SELECT payload FROM jobs WHERE status IN ('queued','generating','publishing')"
            ).fetchall():
                job = json.loads(row[0])
                if job["status"] == "publishing":
                    self._save_job(job, "uncertain")
                elif (
                    job["status"] == "generating"
                    or job["kind"] in ("decision", "peer", "proactive")
                    or job["kind"] == "human"
                    and "round_mode" not in job
                ):
                    self._save_job(job, "cancelled")
                    self._end_round(job)
        self.workers = {}

    def close(self):
        self.db.close()

    def _state(self):
        row = self.db.execute("SELECT payload FROM state WHERE key='channel'").fetchone()
        return json.loads(row[0]) if row else {"revision": 0, "next": self.primary}

    def _save_state(self, state):
        self.db.execute("INSERT OR REPLACE INTO state VALUES ('channel',?)", (json.dumps(state),))

    def _save_job(self, job, status):
        job["status"] = status
        self.db.execute(
            "INSERT OR REPLACE INTO jobs VALUES (?,?,?,?)",
            (job["id"], status, job["bot"], json.dumps(job)),
        )
        log.info(
            "coordination channel=%s bot=%s job=%s round=%s revision=%s status=%s",
            self.channel,
            job["bot"],
            job["id"],
            job["round"],
            job["revision"],
            status,
        )

    def _round(self, job):
        row = self.db.execute("SELECT payload FROM rounds WHERE id=?", (job["round"],)).fetchone()
        return (
            json.loads(row[0])
            if row
            else {
                "id": job["round"],
                "mode": job.get("round_mode", "human"),
                "count": 0,
                "ended": None,
                "started": None,
            }
        )

    def _save_round(self, value):
        self.db.execute(
            "INSERT OR REPLACE INTO rounds VALUES (?,?)", (value["id"], json.dumps(value))
        )

    def _end_round(self, job):
        value = self._round(job)
        if value["ended"] is not None:
            return
        value["ended"] = self.clock()
        self._save_round(value)
        if value["mode"] == "proactive":
            state = self._state()
            if value["count"]:
                state["cooldown_until"] = max(
                    state.get("cooldown_until", 0), self.clock() + self.policy.cooldown_seconds
                )
            state["next_proactive_at"] = max(
                state.get("next_proactive_at", 0), self.clock() + self.policy.recheck_seconds
            )
            self._save_state(state)

    def _record_publication(self, job):
        if job.get("accounted"):
            return
        value = self._round(job)
        value["count"] += 1
        value["last_published_at"] = self.clock()
        if value["started"] is None:
            value["started"] = self.clock()
            if value["mode"] == "proactive":
                state = self._state()
                day = self.policy.local_date(self.clock())
                counts = state.setdefault("daily_counts", {})
                counts[day] = counts.get(day, 0) + 1
                # Keep a small durable calendar history, including the current date.
                state["daily_counts"] = dict(sorted(counts.items())[-8:])
                self._save_state(state)
        self._save_round(value)
        job["accounted"] = True

    def get_job(self, job_id, bot):
        row = self.db.execute(
            "SELECT payload FROM jobs WHERE id=? AND bot=?", (job_id, bot)
        ).fetchone()
        if row is None:
            raise Conflict("Unknown job")
        return json.loads(row[0])

    def register(self, bot, *, discord_id, date_active=False, available=True):
        if self.bots.get(bot) != str(discord_id):
            raise Conflict("Discord identity mismatch")
        self.workers[bot] = {
            "seen": self.clock(),
            "date": bool(date_active),
            "available": bool(available),
        }

    def _available(self, bot):
        worker = self.workers.get(bot, {})
        return (
            worker.get("available", False)
            and self.clock() - worker.get("seen", 0) < self.worker_ttl
        )

    def date_owner(self):
        return next((bot for bot, value in self.workers.items() if value["date"]), None)

    def history(self):
        # Empty/operational component events are activity, not LLM conversation.
        rows = self.db.execute("SELECT payload FROM events ORDER BY length(id) DESC,id DESC")
        result, remaining = [], 16000
        for row in rows:
            event = json.loads(row[0])
            if not event["content"].strip() or event.get("component"):
                continue
            text = event["content"][-remaining:]
            result.append({**event, "content": text})
            remaining -= len(text)
            if len(result) >= 30 or remaining <= 0:
                break
        return list(reversed(result))

    def _event_time(self, event):
        timestamp = event.get("timestamp")
        if timestamp is None:
            # Compatibility for previously persisted Discord outboxes.
            timestamp = (
                ((int(event["id"]) >> 22) + 1420070400000) / 1000
                if len(event["id"]) >= 17
                else self.clock()
            )
        if (
            isinstance(timestamp, bool)
            or not isinstance(timestamp, (int, float))
            or not math.isfinite(timestamp)
        ):
            raise ValueError("Invalid event timestamp")
        return min(float(timestamp), self.clock())

    def _cancel_queued(self):
        for row in self.db.execute("SELECT payload FROM jobs WHERE status='queued'").fetchall():
            job = json.loads(row[0])
            self._save_job(job, "cancelled")
            self._end_round(job)

    def _enqueue(self, job, *, decision=False, delay=0):
        job = {
            **job,
            "id": uuid.uuid4().hex,
            "created": self.clock(),
            "due": self.clock() + delay,
            "sent": [],
            "accounted": False,
        }
        for field in ("expires", "intents", "history"):
            job.pop(field, None)
        if decision:
            job["target_kind"] = job["kind"]
            job["kind"] = "decision"
        self._save_job(job, "queued")
        return job

    def ingest(self, event):
        event = dict(event)
        required = ("id", "channel_id", "author_id", "name", "kind", "content")
        if any(not isinstance(event.get(k), str) for k in required):
            raise ValueError("Event fields must be strings")
        if (
            event["channel_id"] != self.channel
            or not event["id"].isdigit()
            or not event["author_id"].isdigit()
        ):
            raise ValueError("Invalid channel or message id")
        if len(event["content"]) > 16000:
            raise ValueError("Message too large")
        author_bot = next(
            (key for key, value in self.bots.items() if value == event["author_id"]), None
        )
        if event["kind"] not in ("human", "bot") or (event["kind"] == "bot") != bool(author_bot):
            raise ValueError("Invalid participant type")
        event["timestamp"] = self._event_time(event)
        with self.db:
            inserted = self.db.execute(
                "INSERT OR IGNORE INTO events VALUES (?,?)", (event["id"], json.dumps(event))
            ).rowcount
            if not inserted:
                return {"duplicate": True}
            state = self._state()
            state["activity_at"] = max(state.get("activity_at", 0), event["timestamp"])
            if author_bot:
                self._save_state(state)
                return {"duplicate": False}
            if int(event["id"]) <= int(state.get("last_human", "0")):
                self._save_state(state)
                return {"duplicate": False, "historical": True}
            state["last_human"] = event["id"]
            if self.clock() - event["timestamp"] > self.ttl:
                self._save_state(state)
                return {"duplicate": False, "historical": True}
            state["revision"] += 1
            state["next_proactive_at"] = max(
                state.get("next_proactive_at", 0), event["timestamp"] + self.policy.idle_seconds
            )
            mentions = [b for b, uid in self.bots.items() if uid in event.get("mentions", [])]
            content = event["content"].strip()
            prefix = re.match(r"^(?:<@!?\d+>\s*)+", content)
            if prefix and content[prefix.end() :].startswith("!"):
                content = content[prefix.end() :]
                leading = re.findall(r"<@!?(\d+)>", prefix[0])
                mentions = [b for b, uid in self.bots.items() if uid in leading]
            command = content.startswith("!")
            if command and not prefix:
                mentions = []
            reply = next(
                (b for b, uid in self.bots.items() if uid == event.get("reply_author_id")), None
            )
            owner = self.date_owner()
            selected = (self.primary if len(mentions) == 2 else mentions[0]) if mentions else reply
            selected = selected or (self.primary if command else owner or state["next"])
            queued = self.db.execute(
                "SELECT payload FROM jobs WHERE status='queued' ORDER BY rowid DESC"
            ).fetchall()
            previous = json.loads(queued[0][0]) if queued else None
            previous_kind = previous.get("target_kind", previous["kind"]) if previous else None
            merge = bool(
                previous
                and not command
                and not mentions
                and not reply
                and previous_kind == "human"
                and previous.get("author_id") == event["author_id"]
                and previous["due"] > self.clock()
            )
            if merge:
                selected = previous["bot"]
            if not command and not mentions and not reply and not owner and not merge and content:
                state["next"] = next(b for b in self.bots if b != selected)
            parts, source_ids = [content], [event["id"]]
            if (
                previous
                and not command
                and previous_kind == "human"
                and previous.get("author_id") == event["author_id"]
                and previous["bot"] == selected
                and previous["due"] > self.clock()
            ):
                parts, source_ids = previous["parts"] + parts, previous["source_ids"] + source_ids
            # Save before ending previous rounds so their cooldown writes cannot
            # be overwritten by an older channel state snapshot.
            self._save_state(state)
            self._cancel_queued()
            if not content:
                return {"duplicate": False}
            job = {
                "bot": selected,
                "revision": state["revision"],
                "round": event["id"],
                "round_mode": "human",
                "kind": "command" if command else "human",
                "author_id": event["author_id"],
                "source_ids": source_ids,
                "parts": parts,
                "event": {**event, "content": content},
                "allow_reply": not command
                and (len(mentions) == 2 or not mentions and not reply)
                and not owner,
            }
            self._save_round(self._round(job))
            self._enqueue(
                job,
                decision=not command and not mentions and not reply and not owner,
                delay=0 if command else self.debounce,
            )
        return {"duplicate": False}

    def _busy(self):
        return bool(
            self.db.execute(
                "SELECT 1 FROM jobs WHERE status IN ('queued','generating','publishing','uncertain')"
            ).fetchone()
        )

    def _allows_proactive_start(self):
        state, now = self._state(), self.clock()
        return (
            self.policy.proactive_enabled
            and not self.date_owner()
            and all(self._available(bot) for bot in self.bots)
            and now - state.get("activity_at", now) >= self.policy.idle_seconds
            and now >= state.get("cooldown_until", 0)
            and self.policy.allows_start(now)
            and state.get("daily_counts", {}).get(self.policy.local_date(now), 0)
            < self.policy.max_per_day
        )

    def tick(self):
        """Offer one idle decision at a time; never run a catch-up loop."""
        self._expire()
        if self._busy() or not self._allows_proactive_start():
            return None
        state = self._state()
        now = self.clock()
        if now < state.get("next_proactive_at", 0):
            return None
        with self.db:
            bot = state.get("proactive_next", self.primary)
            state["proactive_next"] = next(b for b in self.bots if b != bot)
            state["next_proactive_at"] = now + self.policy.recheck_seconds
            self._save_state(state)
            job = {
                "bot": bot,
                "kind": "proactive",
                "round_mode": "proactive",
                "round": "proactive-" + uuid.uuid4().hex,
                "revision": state["revision"],
                "allow_reply": True,
                "source_ids": [],
                "parts": [],
            }
            self._save_round(self._round(job))
            return self._enqueue(job, decision=True)

    def _expire(self):
        with self.db:
            for row in self.db.execute(
                "SELECT payload FROM jobs WHERE status IN ('generating','publishing')"
            ).fetchall():
                job = json.loads(row[0])
                if self.clock() > job["expires"]:
                    status = "uncertain" if job["status"] == "publishing" else "failed"
                    self._save_job(job, status)
                    if status == "failed":
                        self._end_round(job)

    def claim(self, bot):
        self._expire()
        if not all(self._available(b) for b in self.bots):
            return None
        if self.db.execute(
            "SELECT 1 FROM jobs WHERE status IN ('generating','publishing','uncertain')"
        ).fetchone():
            return None
        row = self.db.execute(
            "SELECT payload FROM jobs WHERE status='queued' AND bot=? ORDER BY rowid LIMIT 1",
            (bot,),
        ).fetchone()
        if not row:
            return None
        job = json.loads(row[0])
        if job["due"] > self.clock():
            return None
        owner = self.date_owner()
        autonomous = job.get("target_kind", job["kind"]) in ("peer", "proactive")
        if (
            job["revision"] != self._state()["revision"]
            or self.clock() - job["created"] > self.ttl
            or owner
            and (autonomous or job["bot"] != owner and job["kind"] != "command")
        ):
            with self.db:
                self._save_job(job, "cancelled")
                self._end_round(job)
            return None
        job["expires"] = self.clock() + self.ttl
        job["history"] = self.history()
        with self.db:
            self._save_job(job, "generating")
        return job

    def ready(self, job_id, bot):
        self._expire()
        job = self.get_job(job_id, bot)
        if job["kind"] == "decision":
            raise Conflict("Decisions cannot publish")
        if job["status"] == "publishing":
            return job
        if (
            job["status"] != "generating"
            or job["revision"] != self._state()["revision"]
            or not self._available(bot)
            or self._round(job)["count"] >= self.policy.max_interventions
        ):
            raise Conflict("Job expired or superseded")
        if self.date_owner() and job["kind"] in ("peer", "proactive"):
            raise Conflict("Date active")
        if (
            job["kind"] == "proactive"
            and self._round(job)["count"] == 0
            and not self._allows_proactive_start()
        ):
            raise Conflict("Proactive start no longer allowed")
        with self.db:
            self._save_job(job, "publishing")
        return job

    def sending(self, job_id, bot, payload):
        job = self.get_job(job_id, bot)
        if (
            job["kind"] == "decision"
            or job["status"] != "publishing"
            or self.clock() > job["expires"]
        ):
            raise Conflict("Publication not authorized")
        job.setdefault("intents", []).append(payload)
        with self.db:
            self._save_job(job, "publishing")

    def _decision(self, job, decision):
        if (
            not isinstance(decision, dict)
            or type(decision.get("participate")) is not bool
            or decision.get("reason_code") not in DECISION_REASONS
        ):
            raise ValueError("Invalid participation decision")
        if job["kind"] != "decision" or job["status"] != "generating":
            raise Conflict("Not an active decision")
        if (
            self.clock() > job["expires"]
            or job["revision"] != self._state()["revision"]
            or not all(self._available(b) for b in self.bots)
            or self.date_owner()
            or self._round(job)["ended"] is not None
            or self._round(job)["count"] >= self.policy.max_interventions
        ):
            self._save_job(job, "cancelled")
            self._end_round(job)
            return
        log.info(
            "participation bot=%s round=%s participate=%s reason=%s",
            job["bot"],
            job["round"],
            decision["participate"],
            decision["reason_code"],
        )
        if not decision["participate"]:
            self._save_job(job, "silent")
            self._end_round(job)
            return
        if job["target_kind"] == "proactive":
            if not self._allows_proactive_start():
                self._save_job(job, "silent")
                self._end_round(job)
                return
        self._save_job(job, "decided")
        generation = {**job, "kind": job["target_kind"]}
        generation.pop("target_kind", None)
        self._enqueue(generation)

    def complete(self, job_id, bot, *, outcome, sent=(), decision=None):
        if outcome not in ("published", "silent", "failed", "uncertain", "reconciled", "decision"):
            raise ValueError("Invalid outcome")
        job = self.get_job(job_id, bot)
        if job["status"] in TERMINAL:
            return
        if not isinstance(sent, (list, tuple)) or any(not isinstance(v, str) for v in sent):
            raise ValueError("Invalid publication receipts")
        if outcome == "decision":
            with self.db:
                self._decision(job, decision)
            return
        if job["kind"] == "decision" and outcome not in ("failed", "silent"):
            raise Conflict("Decision jobs cannot publish")
        if outcome == "reconciled" and job["status"] != "uncertain":
            raise Conflict("Only uncertain jobs can be reconciled")
        if outcome == "published" and job["status"] != "publishing":
            raise Conflict("Job not authorized")
        job["sent"] = list(sent)
        with self.db:
            if outcome in ("published", "reconciled") or outcome == "uncertain" and sent:
                self._record_publication(job)
            self._save_job(job, "published" if outcome == "reconciled" else outcome)
            if outcome == "uncertain":
                return  # keep the round open until delivery is reconciled
            if (
                outcome != "published"
                or not job["allow_reply"]
                or self.date_owner()
                or job["revision"] != self._state()["revision"]
                or self._round(job)["count"] >= self.policy.max_interventions
            ):
                self._end_round(job)
                return
            companion = next(b for b in self.bots if b != bot)
            self._enqueue(
                {**job, "bot": companion, "kind": "peer"}, decision=True, delay=self.reply_delay
            )

    def uncertain(self, bot):
        return [
            json.loads(r[0])
            for r in self.db.execute(
                "SELECT payload FROM jobs WHERE status='uncertain' AND bot=?", (bot,)
            )
        ]
