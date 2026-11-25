
from flask import Flask, request, jsonify
import sqlite3
from datetime import datetime
from pathlib import Path

app = Flask(__name__)

# 数据库文件名称
DB_NAME = Path(__file__).resolve().with_name("seat_detection.db")


# 初始化数据库
def init_db():
    conn = sqlite3.connect(DB_NAME)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS sensor_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            raw_value INTEGER NOT NULL,
            received_at TEXT NOT NULL
        )
    """)

    conn.commit()
    conn.close()


# 接收 ESP32 发送的数据
@app.route("/api/sensor", methods=["POST"])
def receive_sensor_data():

    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({
            "success": False,
            "message": "Invalid JSON"
        }), 400

    device_id = data.get("device_id")
    raw_value = data.get("raw_value")
    sequence = data.get("sequence")

    # 检查数据
    if not isinstance(device_id, str) or not device_id:
        return jsonify({
            "success": False,
            "message": "Invalid device_id"
        }), 400

    if type(raw_value) is not int or type(sequence) is not int:
        return jsonify({
            "success": False,
            "message": "Invalid raw_value or sequence"
        }), 400

    # 使用电脑服务器接收时间
    received_at = datetime.now().astimezone().isoformat(
        timespec="seconds"
    )

    # 写入数据库
    conn = sqlite3.connect(DB_NAME)

    conn.execute("""
        INSERT INTO sensor_data
        (device_id, sequence, raw_value, received_at)
        VALUES (?, ?, ?, ?)
    """, (device_id, sequence, raw_value, received_at))

    conn.commit()
    conn.close()

    print(
        f"[{received_at}] "
        f"Device: {device_id} | "
        f"Sequence: {sequence} | "
        f"RAW: {raw_value}"
    )

    return jsonify({
        "success": True,
        "message": "Data saved successfully"
    }), 200


# 检查服务器是否运行
@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "server": "running"
    })


if __name__ == "__main__":

    init_db()

    print("Seat Detection Server Starting...")
    print("Database:", DB_NAME)
    print("Listening on port 5000")

    # 允许局域网内其他设备访问
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=False
    )
