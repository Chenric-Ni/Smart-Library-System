# -*- coding: utf-8 -*-
"""Local library seat reservation UI. Run with: python seat_reservation.py"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
ACCOUNT_DB = ROOT / "user_accounts.db"
SEAT_DB = ROOT / "seat_status.db"
HOST, PORT = "0.0.0.0", 8000
# Keep these IDs identical to seat_monitor.py --devices. Override when hardware
# uses different device IDs, for example SML_SEAT_IDS=chair_a,chair_b,chair_c,chair_d.
SEAT_IDS = [seat.strip() for seat in os.environ.get(
    "SML_SEAT_IDS", "seat_01,seat_02,seat_03,seat_04"
).split(",") if seat.strip()]
SESSIONS: dict[str, str] = {}

PAGE = r'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>SeatSpace · Library Seats</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#f4f5f0;color:#202921;font:16px/1.5 system-ui,"Microsoft YaHei",sans-serif}header{height:72px;background:#fff;border-bottom:1px solid #e6e9e2;display:flex;align-items:center;justify-content:space-between;padding:0 max(calc((100vw - 1120px)/2),24px)}.brand{font-weight:800;font-size:21px;letter-spacing:1px}.brand span{color:#528268}button{border:0;border-radius:9px;padding:11px 17px;background:#315c44;color:#fff;font-weight:700;cursor:pointer}button:disabled{opacity:.45;cursor:not-allowed}.quiet{background:#eef2ed;color:#35513d}.wrap{max-width:1120px;margin:44px auto;padding:0 24px}.hero{display:flex;justify-content:space-between;align-items:center;gap:20px;margin-bottom:26px}.eyebrow{color:#62826a;font-size:13px;font-weight:700;letter-spacing:1px}h1{font-size:36px;line-height:1.2;margin:8px 0}p{color:#6b756d;margin:8px 0}.count{background:#fff;border:1px solid #e7eae4;padding:15px 21px;border-radius:14px;min-width:160px}.count strong{font-size:30px;color:#315c44}.panel{background:#fff;border:1px solid #e6e9e2;border-radius:16px;padding:24px}.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-top:20px}.seat{border:1px solid #e5e9e2;border-radius:12px;padding:16px;min-height:130px}.seat h3{margin:0 0 6px}.badge{font-size:12px;padding:4px 9px;border-radius:30px;background:#edf3ed;color:#41684b}.occupied{background:#faefec;color:#a45542}.reserved{background:#fff4dc;color:#936914}.away{background:#eaf1fa;color:#456a92}.seat button{width:100%;margin-top:13px;padding:9px}.hidden{display:none!important}.auth{max-width:420px;margin:90px auto}.tabs{display:flex;gap:8px;margin:20px 0}.tabs button{flex:1}input{display:block;width:100%;padding:12px;border:1px solid #dce2da;border-radius:8px;margin:12px 0;font:inherit}.notice{padding:13px 16px;border-radius:10px;background:#f3f6f1;margin:15px 0}.notice strong{color:#315c44}.actions{display:flex;gap:10px;flex-wrap:wrap;margin-top:18px}.small{font-size:13px;color:#788078}@media(max-width:760px){.grid{grid-template-columns:repeat(2,1fr)}.hero{align-items:flex-start;flex-direction:column}.wrap{margin-top:28px}}@media(max-width:420px){.grid{grid-template-columns:1fr}}
</style></head><body><header><div class="brand">SeatSpace <span>LIBRARY</span></div><div id="userbar"></div></header><main class="wrap" id="main"></main>
<script>
const main=document.querySelector('#main'),userbar=document.querySelector('#userbar');let me=null,seats=[];
async function api(path,body){let r=await fetch(path,{method:body?'POST':'GET',headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined});let d=await r.json();if(!r.ok)throw Error(d.error||'Request failed');return d}
function auth(){main.innerHTML=`<section class="panel auth"><div class="eyebrow">Welcome to SeatSpace</div><h1 id="authTitle">Email Sign In</h1><p>Sign in to view available seats and reserve your reading spot.</p><div class="tabs"><button class="quiet" onclick="setMode('login')">Sign In</button><button class="quiet" onclick="setMode('register')">Sign Up</button></div><form id="form"><input name="email" type="email" placeholder="Email address" required><input name="password" type="password" placeholder="Password (at least 8 characters)" required minlength="8"><button id="submit" style="width:100%">Sign In</button></form><p id="err" class="small"></p></section>`;setMode('login')}
let mode='login';function setMode(m){mode=m;document.querySelector('#authTitle').textContent=m==='login'?'Email Sign In':'Create Account';document.querySelector('#submit').textContent=m==='login'?'Sign In':'Sign Up';document.querySelector('#form').onsubmit=async e=>{e.preventDefault();let f=new FormData(e.target);try{await api('/api/'+mode,{email:f.get('email'),password:f.get('password')});await refresh()}catch(x){document.querySelector('#err').textContent=x.message}}}
function render(){if(!me){if(!document.querySelector('#form'))auth();userbar.innerHTML='';return}userbar.innerHTML=`<span class="small">${me.email}</span> <button class="quiet" onclick="logout()">Sign Out</button>`;let mine=seats.find(s=>s.user_email===me.email&&['reserved','occupied','away'].includes(s.status));if(mine){main.innerHTML=`<div class="eyebrow">My Seat</div><h1>${mine.seat_id}</h1><p>Your Seat · ${mine.status==='reserved'?'Please arrive within 10 minutes':mine.status==='away'?'Temporarily away':'Seat in use'}</p><section class="panel"><div class="notice"><strong>${statusText(mine.status)}</strong><br>${mine.status==='reserved'?'Arrival deadline: '+fmt(mine.expires_at):mine.status==='away'?'Hold expires: '+fmt(mine.expires_at):'This seat is held for you.'}</div><p class="small">Seat sensor: ${mine.sensor_status==='occupied'?'Occupied':'No occupancy detected'}</p><div class="actions">${mine.status==='reserved'?`<button onclick="act('arrive','${mine.seat_id}')">I have arrived</button>`:''}${mine.status==='occupied'?`<button class="quiet" onclick="act('away','${mine.seat_id}')">Take a break (hold for 15 minutes)</button>`:''}${mine.status==='away'?`<button onclick="act('return','${mine.seat_id}')">I am back</button>`:''}<button class="quiet" onclick="act('release','${mine.seat_id}')">Release seat</button></div></section><p class="small">Seat status refreshes every second.</p>`;return}
let free=seats.filter(s=>s.status==='available').length;main.innerHTML=`<section class="hero"><div><div class="eyebrow">QUIET SPACE, CLEAR MIND</div><h1>Find Your Reading Spot</h1><p>Choose an available seat and arrive within 10 minutes. Seat availability updates in real time.</p></div><div class="count"><strong>${free}</strong><span> / ${seats.length}  seats available</span></div></section><section class="panel"><div class="eyebrow">All Seats</div><div class="grid">${seats.map(s=>`<article class="seat"><h3>${s.seat_id}</h3><span class="badge ${s.status==='occupied'?'occupied':s.status==='reserved'?'reserved':s.status==='away'?'away':''}">${statusText(s.status)}</span><p class="small">${s.sensor_status==='occupied'?'Sensor: occupied':'Sensor: clear'}</p>${s.status==='available'?`<button onclick="act('reserve','${s.seat_id}')">Reserve This Seat</button>`:''}</article>`).join('')}</div></section><p class="small">Updated every second · ${new Date().toLocaleTimeString()}</p>`}
function statusText(s){return {available:'Available',reserved:'Reserved',occupied:'In use',away:'Temporarily away'}[s]||s}function fmt(s){return s?new Date(s).toLocaleTimeString():'—'}async function act(action,seat_id){try{await api('/api/'+action,{seat_id});await refresh()}catch(e){alert(e.message)}}async function logout(){await api('/api/logout',{});me=null;render()}async function refresh(){try{let x=await api('/api/me');me=x.user;seats=x.seats;render()}catch(e){me=null;seats=[];render()}}refresh();setInterval(refresh,1000);
</script></main></body></html>'''


def connect(path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(path, timeout=5)
    db.row_factory = sqlite3.Row
    return db


def init_databases() -> None:
    with connect(ACCOUNT_DB) as db:
        db.execute("CREATE TABLE IF NOT EXISTS users (email TEXT PRIMARY KEY, password_hash TEXT NOT NULL, created_at TEXT NOT NULL)")
    with connect(SEAT_DB) as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS seats (
                seat_id TEXT PRIMARY KEY, status TEXT NOT NULL DEFAULT 'available',
                user_email TEXT, expires_at TEXT, sensor_status TEXT DEFAULT 'empty',
                sensor_updated_at TEXT, sensor_payload TEXT
            );
            CREATE TABLE IF NOT EXISTS calibration_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, device_id TEXT NOT NULL,
                event TEXT NOT NULL, seat_status TEXT, payload TEXT NOT NULL, created_at TEXT NOT NULL
            );
        """)
        # Remove seats no longer configured, including their reservation/current
        # sensor state. Calibration event history is retained separately.
        if SEAT_IDS:
            placeholders = ",".join("?" for _ in SEAT_IDS)
            db.execute(
                f"DELETE FROM seats WHERE seat_id NOT IN ({placeholders})",
                SEAT_IDS,
            )
        else:
            db.execute("DELETE FROM seats")
        for seat in SEAT_IDS:
            db.execute("INSERT OR IGNORE INTO seats(seat_id) VALUES (?)", (seat,))


def now() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def clean_expired(db: sqlite3.Connection) -> None:
    current = iso(now())
    db.execute("UPDATE seats SET status='available', user_email=NULL, expires_at=NULL WHERE status IN ('reserved','away') AND expires_at <= ?", (current,))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_: object) -> None:
        pass

    def send_json(self, data: dict, code: int = 200) -> None:
        raw = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code); self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(raw))); self.send_header('Cache-Control', 'no-store')
        if getattr(self, 'session_cookie', None): self.send_header('Set-Cookie', 'session='+self.session_cookie+'; HttpOnly; SameSite=Lax; Path=/')
        if getattr(self, 'clear_cookie', False): self.send_header('Set-Cookie', 'session=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0')
        self.end_headers(); self.wfile.write(raw)

    def read_body(self) -> dict:
        length = int(self.headers.get('Content-Length', '0'))
        if length > 10000:
            raise ValueError('Request is too large')
        data = json.loads(self.rfile.read(length) or b'{}')
        if not isinstance(data, dict):
            raise ValueError('Invalid request format')
        return data

    def user(self) -> str | None:
        token = self.headers.get('Cookie', '').replace('session=', '').split(';')[0]
        return SESSIONS.get(token)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == '/':
            body = PAGE.encode(); self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body); return
        if path == '/api/me':
            email = self.user()
            with connect(SEAT_DB) as db:
                clean_expired(db)
                seats = [dict(row) for row in db.execute('SELECT seat_id,status,user_email,expires_at,sensor_status,sensor_updated_at FROM seats ORDER BY seat_id')]
            self.send_json({'user': {'email': email} if email else None, 'seats': seats}); return
        self.send_json({'error':'Not found'}, 404)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            body = self.read_body()
            if path in ('/api/register','/api/login'):
                email = str(body.get('email','')).strip().lower(); password = body.get('password','')
                if len(email) > 254 or '@' not in email or not isinstance(password,str): raise ValueError('Enter a valid email address and password')
                with connect(ACCOUNT_DB) as db:
                    row = db.execute('SELECT password_hash FROM users WHERE email=?',(email,)).fetchone()
                    if path.endswith('register'):
                        if len(password)<8: raise ValueError('Password must be at least 8 characters')
                        if row: raise ValueError('This email is already registered')
                        salt=secrets.token_hex(16); hashed=salt+':'+hashlib.pbkdf2_hmac('sha256',password.encode(),salt.encode(),200000).hex()
                        db.execute('INSERT INTO users VALUES (?,?,?)',(email,hashed,iso(now())))
                    elif not row or not self.verify(password,row['password_hash']): raise ValueError('Incorrect email or password')
                token=secrets.token_urlsafe(32); SESSIONS[token]=email; self.session_cookie=token
                self.send_json({'ok':True})
                return
            if path == '/api/logout':
                token=self.headers.get('Cookie','').replace('session=','').split(';')[0]; SESSIONS.pop(token,None); self.clear_cookie=True; self.send_json({'ok':True}); return
            email=self.user()
            if not email: self.send_json({'error':'Please sign in first'},401); return
            seat_id=str(body.get('seat_id',''))
            with connect(SEAT_DB) as db:
                clean_expired(db)
                seat=db.execute('SELECT * FROM seats WHERE seat_id=?',(seat_id,)).fetchone()
                if not seat: self.send_json({'error':'Seat not found'},404); return
                current=seat['status']; action=path.rsplit('/',1)[-1]
                if action=='reserve' and current=='available': status,expiry='reserved',iso(now()+timedelta(minutes=10))
                elif action=='arrive' and current=='reserved' and seat['user_email']==email: status,expiry='occupied',None
                elif action=='away' and current=='occupied' and seat['user_email']==email: status,expiry='away',iso(now()+timedelta(minutes=15))
                elif action=='return' and current=='away' and seat['user_email']==email: status,expiry='occupied',None
                elif action=='release' and seat['user_email']==email: status,expiry='available',None
                else: self.send_json({'error':'This action is not available in the current state'},409); return
                changed=db.execute("UPDATE seats SET status=?,user_email=?,expires_at=? WHERE seat_id=? AND status=?",(status,None if status=='available' else email,expiry,seat_id,current)).rowcount
                if changed!=1: self.send_json({'error':'This seat was just updated by another user. Please refresh and try again.'},409); return
            self.send_json({'ok':True})
        except (ValueError, json.JSONDecodeError) as exc: self.send_json({'error':str(exc)},400)
        except sqlite3.IntegrityError: self.send_json({'error':'This email is already registered'},409)

    @staticmethod
    def verify(password: str, stored: str) -> bool:
        try:
            salt, expected=stored.split(':',1)
            actual=hashlib.pbkdf2_hmac('sha256',password.encode(),salt.encode(),200000).hex()
            return hmac.compare_digest(actual,expected)
        except ValueError: return False


if __name__ == '__main__':
    init_databases()
    print(f'Library seat UI started on port {PORT}. Local: http://127.0.0.1:{PORT}')
    print('For LAN access, use this computer IPv4 address, for example http://192.168.1.25:8000')
    print(f'Account DB: {ACCOUNT_DB.name} | Seat status DB: {SEAT_DB.name}')
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
