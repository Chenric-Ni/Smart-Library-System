# SeatSpace Library Seat System

Library seat occupancy monitoring and reservation prototype using ESP32, an HX711 load-cell amplifier, a Flask sensor API, SQLite, and a browser-based reservation interface.

## Features

- Receives sensor readings from ESP32 devices and stores them in SQLite.
- Monitors seat occupancy and calibration from recorded sensor readings.
- Provides a local web interface for account registration and seat reservations.
- Keeps runtime databases out of version control because they may contain account and sensor data.

## Project files

| File | Purpose |
| --- | --- |
| `sensor_api.py` | Flask API that receives sensor readings on port 5000. |
| `seat_monitor.py` | Analyzes calibration readings and monitors seat status. |
| `seat_reservation.py` | Local reservation UI and account/seat database service on port 8000. |
| `inspect_sensor_db.py` | Prints tables and recent readings from the sensor database. |
| `esp32_seat_sensor.ino` | ESP32 firmware for an HX711 load-cell sensor. |
| `requirements.txt` | Python runtime dependency list. |

## Requirements

- Python 3.10 or newer
- Flask (install with `pip install -r requirements.txt`)
- Arduino IDE or Arduino CLI, ESP32 board support, and the `HX711` library to build the firmware

The monitoring and reservation services use only Python's standard library. The Flask API requires Flask.

## Run locally

Open a terminal in the project directory. Create and activate a virtual environment, then install dependencies:

```bash
python -m venv .venv
```

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

macOS/Linux:

```bash
source .venv/bin/activate
pip install -r requirements.txt
```

Start the sensor API:

```bash
python sensor_api.py
```

The API accepts `POST /api/sensor` JSON with `device_id`, `sequence`, and integer `raw_value`. `GET /health` reports whether the API is running. The default database is created locally as `seat_detection.db`.

In a second terminal, start the reservation service:

```bash
python seat_reservation.py
```

Open <http://127.0.0.1:8000>. Local account and seat databases are created automatically and are ignored by Git.

Run the occupancy monitor after sensor readings have been recorded:

```bash
python seat_monitor.py --db seat_detection.db
```

To inspect the latest readings:

```bash
python inspect_sensor_db.py
```

## Configure the ESP32

In `esp32_seat_sensor.ino`, set `YOUR_WIFI_SSID`, `YOUR_WIFI_PASSWORD`, and `YOUR_SERVER_IP` on your local copy. Keep real credentials out of commits. Configure the API server URL to point to the computer running `sensor_api.py`, then flash the firmware to the ESP32.

Set `SML_SEAT_IDS` to a comma-separated list if your hardware uses different seat IDs. The default is `seat_01,seat_02,seat_03,seat_04`.

## Data and security notes

- Database files (`*.db`, `*.sqlite*`) are intentionally excluded from Git. Do not publish real user records or sensor logs.
- The services bind to all network interfaces for local network device access. Run them only on a trusted network and add appropriate authentication and deployment security before exposing them to the internet.
- This repository does not yet declare an open-source license. Choose a license before inviting outside contributions if you want to grant reuse rights.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the proposed contribution workflow.
