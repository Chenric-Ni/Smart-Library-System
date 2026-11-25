"""Calibrate and monitor multiple sensor-backed seats from SQLite."""

from __future__ import annotations

import argparse
import json
import math
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_DATABASE = Path(__file__).with_name("seat_detection.db")
SEAT_STATUS_DATABASE = Path(__file__).with_name("seat_status.db")
DEFAULT_DEVICES = tuple(d.strip() for d in os.environ.get(
    "SML_SEAT_IDS", "seat_01,seat_02,seat_03,seat_04"
).split(",") if d.strip())
# Seats 1, 2 and 4 use absolute RAW thresholds. Seat 3 reports a negative
# empty reading, so its threshold is a positive change from its startup baseline.
DEFAULT_THRESHOLDS = {"seat_01": 1_000_000, "seat_02": 1_080_000,
                      "seat_03": 500_000, "seat_04": 1_370_000}
BASELINE_DEVICES = {"seat_03"}


def _publish_seat_event(event: Dict[str, Any]) -> None:
    """Persist events in the schema consumed by seat_reservation.py."""
    connection = sqlite3.connect(SEAT_STATUS_DATABASE, timeout=5)
    try:
        connection.execute("""CREATE TABLE IF NOT EXISTS seats (
            seat_id TEXT PRIMARY KEY, status TEXT NOT NULL DEFAULT 'available',
            user_email TEXT, expires_at TEXT, sensor_status TEXT DEFAULT 'empty',
            sensor_updated_at TEXT, sensor_payload TEXT)""")
        connection.execute("""CREATE TABLE IF NOT EXISTS calibration_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, device_id TEXT NOT NULL,
            event TEXT NOT NULL, seat_status TEXT, payload TEXT NOT NULL,
            created_at TEXT NOT NULL)""")
        payload = json.dumps(event, ensure_ascii=False)
        connection.execute("""INSERT INTO calibration_events
            (device_id, event, seat_status, payload, created_at) VALUES (?, ?, ?, ?, ?)""",
            (str(event.get("device_id", "unknown")), str(event.get("event", "unknown")),
             event.get("seat_status"), payload, datetime.now(timezone.utc).isoformat()))
        if event.get("event") in ("initialized", "seat_status_changed"):
            device_id = str(event.get("device_id", "unknown"))
            status = event.get("seat_status", "empty")
            connection.execute("""INSERT INTO seats
                (seat_id, sensor_status, sensor_updated_at, sensor_payload) VALUES (?, ?, ?, ?)
                ON CONFLICT(seat_id) DO UPDATE SET sensor_status=excluded.sensor_status,
                sensor_updated_at=excluded.sensor_updated_at, sensor_payload=excluded.sensor_payload""",
                (device_id, status, datetime.now(timezone.utc).isoformat(), payload))
            if status == "occupied":
                connection.execute("""UPDATE seats SET status='occupied' WHERE seat_id=?
                    AND status='available' AND user_email IS NULL""", (device_id,))
            elif status == "empty":
                connection.execute("""UPDATE seats SET status='available' WHERE seat_id=?
                    AND status='occupied' AND user_email IS NULL""", (device_id,))
        connection.commit()
    finally:
        connection.close()


def _emit(payload: Dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False), flush=True)
    _publish_seat_event(payload)


def _connect_readonly(db_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)


def analyze_calibration(db_path: Path = DEFAULT_DATABASE, device_id: str = "seat_01",
                        max_stddev: float = 50.0, limit: Optional[int] = None) -> Dict[str, Any]:
    """Calculate statistics for existing rows without changing the database."""
    if max_stddev < 0 or not math.isfinite(max_stddev):
        raise ValueError("max_stddev must be a finite, non-negative number")
    if limit is not None and limit < 1:
        raise ValueError("limit must be a positive integer")
    query = "SELECT raw_value FROM sensor_data WHERE device_id = ? ORDER BY id DESC"
    params: Tuple[Any, ...] = (device_id,)
    if limit is not None:
        query += " LIMIT ?"
        params += (limit,)
    with _connect_readonly(db_path) as connection:
        values = [row[0] for row in connection.execute(query, params).fetchall()]
    count = len(values)
    mean = sum(values) / count if count else None
    stddev = math.sqrt(sum((v - mean) ** 2 for v in values) / count) if count else None
    stable = count >= 2 and stddev <= max_stddev
    return {"device_id": device_id, "sample_count": count, "mean": mean,
            "stddev": stddev, "min": min(values) if values else None,
            "max": max(values) if values else None, "max_stddev_threshold": max_stddev,
            "stable": stable,
            "status": "stable" if stable else ("insufficient_data" if count < 2 else "unstable")}


def monitor_seats(db_path: Path = DEFAULT_DATABASE, device_ids: Tuple[str, ...] = DEFAULT_DEVICES,
                  warmup_seconds: float = 30.0, occupied_multiplier: float = 8.0,
                  max_stddev: float = 50.0, consecutive_samples: int = 3,
                  poll_interval: float = 0.2, empty_multiplier: float = 0.5,
                  recalibration_seconds: float = 5.0) -> None:
    """Monitor seats with fixed thresholds, using a baseline delta for seat 3."""
    device_ids = tuple(dict.fromkeys(d.strip() for d in device_ids if d.strip()))
    if not device_ids:
        raise ValueError("at least one device ID is required")
    if warmup_seconds <= 0 or poll_interval <= 0 or recalibration_seconds <= 0:
        raise ValueError("warmup_seconds, poll_interval, and recalibration_seconds must be positive")
    if occupied_multiplier <= 0 or empty_multiplier < 0 or max_stddev < 0:
        raise ValueError("multipliers must be non-negative and occupied_multiplier must be positive")
    if empty_multiplier >= occupied_multiplier:
        raise ValueError("empty_multiplier must be lower than occupied_multiplier")
    if consecutive_samples < 1:
        raise ValueError("consecutive_samples must be at least 1")

    with _connect_readonly(db_path) as connection:
        last_id = connection.execute("SELECT COALESCE(MAX(id), 0) FROM sensor_data").fetchone()[0]
    now = time.monotonic()
    states: Dict[str, Dict[str, Any]] = {}
    for device_id in device_ids:
        states[device_id] = {"state": "empty", "pending_state": None, "pending_count": 0,
            "baseline": None, "baseline_values": [], "warmup_started": now}
        _emit({"event": "initialized", "device_id": device_id, "seat_status": "empty"})
    placeholders = ",".join("?" for _ in device_ids)
    last_status_print = now

    while True:
        with _connect_readonly(db_path) as connection:
            rows = connection.execute("SELECT id, device_id, raw_value, received_at FROM sensor_data "
                "WHERE device_id IN (" + placeholders + ") AND id > ? ORDER BY id ASC",
                device_ids + (last_id,)).fetchall()
        for row_id, device_id, raw_value, received_at in rows:
            last_id = row_id
            current = states[device_id]
            state = current["state"]
            threshold = DEFAULT_THRESHOLDS.get(device_id)
            if threshold is None:
                raise ValueError("no fixed threshold configured for device: " + device_id)
            if device_id in BASELINE_DEVICES:
                if current["baseline"] is None:
                    current["baseline_values"].append(raw_value)
                    continue
                measured_value = raw_value - current["baseline"]
            else:
                measured_value = raw_value
            detected = "occupied" if measured_value >= threshold else "empty"
            if detected == state:
                current["pending_state"], current["pending_count"] = None, 0
            elif detected == current["pending_state"]:
                current["pending_count"] += 1
            else:
                current["pending_state"], current["pending_count"] = detected, 1
            if current["pending_count"] >= consecutive_samples:
                state = current["state"] = detected
                current["pending_state"], current["pending_count"] = None, 0
                _emit({"event": "seat_status_changed", "device_id": device_id,
                    "seat_status": state, "raw_value": raw_value,
                    "measured_value": measured_value, "threshold": threshold,
                    "baseline": current["baseline"], "received_at": received_at})

        now = time.monotonic()
        for device_id in BASELINE_DEVICES.intersection(device_ids):
            current = states[device_id]
            values = current["baseline_values"]
            if (current["baseline"] is None and values
                    and now - current["warmup_started"] >= warmup_seconds):
                current["baseline"] = sum(values) / len(values)
                _emit({"event": "baseline_ready", "device_id": device_id,
                    "baseline": current["baseline"], "sample_count": len(values),
                    "threshold": DEFAULT_THRESHOLDS[device_id], "seat_status": "empty"})
        if now - last_status_print >= 1:
            print("Seat statuses: " + ", ".join("{}={}".format(d, s["state"]) for d, s in states.items()), flush=True)
            last_status_print = now
        time.sleep(poll_interval)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--devices", default=",".join(DEFAULT_DEVICES),
                        help="Comma-separated device IDs (defaults to SML_SEAT_IDS or four seat IDs)")
    parser.add_argument("--device", help="Legacy single-device option; overrides --devices")
    parser.add_argument("--warmup-seconds", type=float, default=15.0,
                        help="Seconds used to collect seat 3's empty-seat baseline at startup")
    parser.add_argument("--occupied-multiplier", type=float, default=8.0,
                        help="Legacy compatibility option; fixed thresholds are used")
    parser.add_argument("--empty-multiplier", type=float, default=0.5,
                        help="Legacy compatibility option; fixed thresholds are used")
    parser.add_argument("--recalibration-seconds", type=float, default=5.0)
    parser.add_argument("--max-stddev", type=float, default=50.0)
    parser.add_argument("--consecutive", type=int, default=3)
    parser.add_argument("--poll-interval", type=float, default=0.2)
    parser.add_argument("--analyze-once", action="store_true")
    args = parser.parse_args()
    device_ids = (args.device,) if args.device else tuple(d.strip() for d in args.devices.split(",") if d.strip())
    if args.analyze_once:
        results = [analyze_calibration(args.db, d, args.max_stddev) for d in device_ids]
        print(json.dumps(results[0] if len(results) == 1 else results, indent=2))
        return
    try:
        monitor_seats(args.db, device_ids, args.warmup_seconds, args.occupied_multiplier,
            args.max_stddev, args.consecutive, args.poll_interval, args.empty_multiplier,
            args.recalibration_seconds)
    except KeyboardInterrupt:
        for device_id in device_ids:
            _emit({"event": "stopped", "device_id": device_id,
                "timestamp": datetime.now(timezone.utc).isoformat()})


if __name__ == "__main__":
    main()
