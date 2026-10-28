"""Cálculos puros para la percepción temporal de Airi.

Todos los cálculos reciben el instante de referencia explícitamente. La zona
``None`` representa la zona local del proceso y permite que el sistema aplique
sus reglas de horario de verano sin depender de una zona hardcodeada.
"""

from __future__ import annotations

import math
import warnings
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_WEEKDAYS = (
    "lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"
)
_MONTHS = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
    "agosto", "septiembre", "octubre", "noviembre", "diciembre",
)
_WARNED_TIMEZONES: set[str] = set()


@dataclass(frozen=True)
class TimeConfig:
    """Activación y zona para un servicio de conversación."""

    enabled: bool = True
    timezone: str = ""


@dataclass(frozen=True)
class LocalMoment:
    """Partes locales de un instante, listas para el prompt."""

    epoch: float
    year: int
    month: int
    day: int
    hour: int
    minute: int
    weekday: str
    month_name: str
    bucket: str
    zone_label: str

    @property
    def local_iso(self) -> str:
        return (
            f"{self.year:04d}-{self.month:02d}-{self.day:02d}"
            f"T{self.hour:02d}:{self.minute:02d}"
        )


@dataclass(frozen=True)
class TemporalContext:
    """Contexto temporal calculado para un turno."""

    moment: LocalMoment
    user_gap_seconds: float | None
    channel_gap_seconds: float | None
    first_time: bool
    in_date: bool
    user_name: str | None = None
    zone: ZoneInfo | None = None
    user_last_at: float | None = None
    channel_last_at: float | None = None


def resolve_zone(name: str | None) -> tuple[ZoneInfo | None, str, str]:
    """Devuelve (tzinfo, etiqueta, origen); ``None`` significa zona del sistema."""
    value = str(name or "").strip()
    if not value:
        return None, "hora local del sistema", "system"
    try:
        zone = ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        if value not in _WARNED_TIMEZONES:
            warnings.warn(
                f"AIRI_TIMEZONE={value!r} no es una zona IANA válida; "
                "se usa la zona local del sistema.",
                RuntimeWarning,
                stacklevel=2,
            )
            _WARNED_TIMEZONES.add(value)
        return None, "hora local del sistema", "system"
    return zone, value, "override"


def _valid_epoch(value) -> float | None:
    try:
        epoch = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return epoch if math.isfinite(epoch) else None


def _datetime_at(epoch: float, zone: ZoneInfo | None) -> datetime:
    if zone is None:
        return datetime.fromtimestamp(epoch).astimezone()
    return datetime.fromtimestamp(epoch, tz=zone)


def day_part(hour: int) -> str:
    """Clasifica la hora local con fronteras [00,06), [06,12), [12,20), [20,24)."""
    hour = max(0, min(23, int(hour)))
    if hour < 6:
        return "madrugada"
    if hour < 12:
        return "mañana"
    if hour < 20:
        return "tarde"
    return "noche"


def local_moment(now: float, zone: ZoneInfo | None = None) -> LocalMoment:
    """Descompone un epoch en calendario local sin depender del locale."""
    epoch = _valid_epoch(now)
    if epoch is None:
        raise ValueError("now debe ser un epoch finito")
    dt = _datetime_at(epoch, zone)
    label = getattr(zone, "key", None) or "hora local del sistema"
    return LocalMoment(
        epoch=epoch,
        year=dt.year,
        month=dt.month,
        day=dt.day,
        hour=dt.hour,
        minute=dt.minute,
        weekday=_WEEKDAYS[dt.weekday()],
        month_name=_MONTHS[dt.month - 1],
        bucket=day_part(dt.hour),
        zone_label=label,
    )


def elapsed_text(seconds: float, *, short: bool = False) -> str:
    """Formatea una duración; para "ayer" usar :func:`format_elapsed`."""
    value = _valid_epoch(seconds)
    if value is None or value < 60:
        return "ahora" if short else "ahora mismo"
    if value < 3600:
        return f"hace {max(1, int(value // 60))} min"
    if value < 86400:
        return f"hace {max(1, int(value // 3600))} h"
    days = max(1, int(value // 86400))
    return "hace 1 día" if days == 1 else f"hace {days} días"


def calendar_gap_days(now: float, ts: float, zone: ZoneInfo | None = None) -> int:
    """Diferencia de fechas locales, robusta ante días DST de 23 o 25 horas."""
    current = _valid_epoch(now)
    previous = _valid_epoch(ts)
    if current is None or previous is None or previous > current:
        return 0
    return max(0, (_datetime_at(current, zone).date() - _datetime_at(previous, zone).date()).days)


def format_elapsed(
    now: float, ts: float, zone: ZoneInfo | None = None, *, short: bool = False
) -> str:
    """Formatea el tiempo entre dos epochs usando fechas locales para "ayer"."""
    current = _valid_epoch(now)
    previous = _valid_epoch(ts)
    if current is None or previous is None or previous >= current:
        return "ahora" if short else "ahora mismo"
    seconds = current - previous
    if seconds < 60:
        return "ahora" if short else "ahora mismo"
    if seconds < 3600:
        return f"hace {max(1, int(seconds // 60))} min"
    days = calendar_gap_days(current, previous, zone)
    if days == 1 and seconds < 48 * 3600:
        return "ayer"
    if seconds < 86400:
        return f"hace {max(1, int(seconds // 3600))} h"
    if days == 0:
        return f"hace {int(seconds // 3600)} h"
    if days == 1:
        return "ayer"
    return f"hace {days} días"


def _timestamp(value) -> float | None:
    result = _valid_epoch(value)
    return result if result is not None and result >= 0 else None


def build_temporal_context(
    now: float,
    config: TimeConfig,
    *,
    users,
    history,
    snapshot=(),
    user_id,
    in_date: bool,
) -> TemporalContext | None:
    """Construye el contexto con datos previos, sin mutar estado ni leer el reloj."""
    if not config.enabled:
        return None
    epoch = _valid_epoch(now)
    if epoch is None:
        return None
    zone, _label, _source = resolve_zone(config.timezone)
    moment = local_moment(epoch, zone)
    user_entry = (users or {}).get(str(user_id)) if hasattr(users, "get") else None
    last_seen = (
        _timestamp(user_entry.get("last_seen"))
        if isinstance(user_entry, Mapping)
        else None
    )
    user_gap = max(0.0, epoch - last_seen) if last_seen is not None else None

    channel_last = None
    if not in_date:
        for entry in (users or {}).values() if hasattr(users, "values") else ():
            stamp = _timestamp(entry.get("last_seen")) if isinstance(entry, Mapping) else None
            if stamp is not None and stamp <= epoch:
                channel_last = stamp if channel_last is None else max(channel_last, stamp)
        for entries in (history or (), snapshot or ()):
            for entry in entries if isinstance(entries, (list, tuple)) else ():
                if isinstance(entry, Mapping):
                    raw_stamp = entry.get("ts", entry.get("created_at"))
                else:
                    raw_stamp = getattr(entry, "ts", None)
                stamp = _timestamp(raw_stamp)
                if stamp is not None and stamp <= epoch:
                    channel_last = stamp if channel_last is None else max(channel_last, stamp)
    channel_gap = max(0.0, epoch - channel_last) if channel_last is not None else None
    return TemporalContext(
        moment=moment,
        user_gap_seconds=user_gap,
        channel_gap_seconds=channel_gap,
        first_time=last_seen is None,
        in_date=bool(in_date),
        user_name=(
            str(user_entry.get("name"))
            if isinstance(user_entry, Mapping) and user_entry.get("name")
            else None
        ),
        zone=zone,
        user_last_at=last_seen,
        channel_last_at=channel_last,
    )
