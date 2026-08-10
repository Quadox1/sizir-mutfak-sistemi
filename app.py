import os
import json
import sqlite3
import urllib.request
import threading
from datetime import datetime
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.config['SECRET_KEY'] = 'sizir_alabalik_secret_key_2026'
socketio = SocketIO(app, cors_allowed_origins="*")

DB_FILE = 'sizir_alabalik.db'

# VERİTABANI KURULUMU
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            password TEXT NOT NULL
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS orders (
            order_id TEXT PRIMARY KEY,
            garson TEXT NOT NULL,
            time_str TEXT NOT NULL,
            items_json TEXT NOT NULL,
            status TEXT NOT NULL
        )
    ''')
    # Varsayılan garsonları ekle
    default_users = [
        ('ahmet', 'Ahmet', '1234'),
        ('mehmet', 'Mehmet', '1234'),
        ('can', 'Can', '1234'),
        ('unal', 'Ünal', '1234')
    ]
    for u, n, p in default_users:
        cursor.execute("INSERT OR IGNORE INTO users (username, name, password) VALUES (?, ?, ?)", (u, n, p))
    conn.commit()
    conn.close()

init_db()

MENU_ITEMS = [
    "Izgara Balık",
    "Sivas Köfte",
    "Tavuk Kanat",
    "Kiremitte Balık",
    "Kaşarlı Balık",
    "Köz Tabağı"
]

def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

@app.route('/')
def index():
    return render_template('garson.html', menu=MENU_ITEMS)

@app.route('/mutfak')
def mutfak():
    return render_template('mutfak.html')

@app.route('/admin')
def admin():
    if not session.get('admin_logged_in'):
        return render_template('admin_login.html')
    return render_template('admin.html')

@app.route('/api/admin-login', methods=['POST'])
def admin_login():
    data = request.get_json(silent=True) or {}
    username = data.get('username')
    password = data.get('password')
    if username == 'admin' and password == 'admin123':
        session['admin_logged_in'] = True
        return jsonify({"status": "success"})
    return jsonify({"status": "error", "message": "Yönetici şifresi hatalı!"}), 400

@app.route('/api/admin-logout', methods=['POST'])
def admin_logout():
    session.pop('admin_logged_in', None)
    return jsonify({"status": "success"})

@app.route('/api/login', methods=['POST'])
def garson_login():
    data = request.get_json(silent=True) or {}
    username = str(data.get('username', '')).strip().lower()
    password = str(data.get('password', '')).strip()

    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE username = ? AND password = ?", (username, password)).fetchone()
    conn.close()

    if user:
        return jsonify({"status": "success", "garson_name": user['name']})
    return jsonify({"status": "error", "message": "Kullanıcı adı veya şifre hatalı!"}), 400

@app.route('/api/siparis-ver', methods=['POST'])
def siparis_ver():
    data = request.get_json(silent=True) or {}
    garson = data.get('garson')
    items = data.get('items', [])

    if not garson or not items:
        return jsonify({"status": "error"}), 400

    conn = get_db()
    last_order = conn.execute("SELECT order_id FROM orders ORDER BY ROWID DESC LIMIT 1").fetchone()
    order_id = str(int(last_order['order_id']) + 1) if last_order else "101"
    now_str = datetime.now().strftime("%H:%M")

    order_items = []
    for item in items:
        order_items.append({
            "id": f"{order_id}_{len(order_items)}",
            "name": item['name'],
            "qty": item['qty'],
            "status": "hazirlaniyor"
        })

    order_data = {
        "order_id": order_id,
        "garson": garson,
        "time": now_str,
        "items": order_items,
        "status": "aktif"
    }

    conn.execute("INSERT INTO orders (order_id, garson, time_str, items_json, status) VALUES (?, ?, ?, ?, ?)",
                 (order_id, garson, now_str, json.dumps(order_items), "aktif"))
    conn.commit()
    conn.close()

    socketio.emit('yeni_siparis', order_data)
    return jsonify({"status": "success", "order_id": order_id})

@app.route('/api/item-durum-degistir', methods=['POST'])
def item_durum_degistir():
    data = request.get_json(silent=True) or {}
    order_id = str(data.get('order_id'))
    item_id = data.get('item_id')

    conn = get_db()
    row = conn.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
    if row:
        items = json.loads(row['items_json'])
        all_ready = True
        for item in items:
            if item['id'] == item_id:
                item['status'] = "hazir" if item['status'] == "hazirlaniyor" else "hazirlaniyor"
            if item['status'] != "hazir":
                all_ready = False

        status = "tamamlandi" if all_ready else "aktif"
        conn.execute("UPDATE orders SET items_json = ?, status = ? WHERE order_id = ?",
                     (json.dumps(items), status, order_id))
        conn.commit()

        updated_order = {
            "order_id": order_id,
            "garson": row['garson'],
            "time": row['time_str'],
            "items": items,
            "status": status
        }
        conn.close()
        socketio.emit('siparis_guncellendi', updated_order)
        return jsonify({"status": "success"})

    conn.close()
    return jsonify({"status": "error"}), 404

@app.route('/api/siparis-sil', methods=['POST'])
def siparis_sil():
    data = request.get_json(silent=True) or {}
    order_id = str(data.get('order_id'))
    conn = get_db()
    conn.execute("DELETE FROM orders WHERE order_id = ?", (order_id,))
    conn.commit()
    conn.close()

    socketio.emit('siparis_silindi', {"order_id": order_id})
    return jsonify({"status": "success"})

# YÖNETİCİ PANELİ API'LERİ
@app.route('/api/admin/users', methods=['GET', 'POST', 'DELETE'])
def admin_users():
    if not session.get('admin_logged_in'):
        return jsonify({"status": "unauthorized"}), 401
    conn = get_db()

    if request.method == 'GET':
        users = conn.execute("SELECT id, username, name, password FROM users").fetchall()
        conn.close()
        return jsonify([dict(u) for u in users])

    if request.method == 'POST':
        data = request.json
        u, n, p = data.get('username'), data.get('name'), data.get('password')
        conn.execute("INSERT OR REPLACE INTO users (username, name, password) VALUES (?, ?, ?)", (u, n, p))
        conn.commit()
        conn.close()
        return jsonify({"status": "success"})

    if request.method == 'DELETE':
        user_id = request.json.get('id')
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
        conn.close()
        return jsonify({"status": "success"})

@socketio.on('connect')
def handle_connect():
    conn = get_db()
    rows = conn.execute("SELECT * FROM orders WHERE status = 'aktif'").fetchall()
    conn.close()

    orders = []
    for r in rows:
        orders.append({
            "order_id": r['order_id'],
            "garson": r['garson'],
            "time": r['time_str'],
            "items": json.loads(r['items_json']),
            "status": r['status']
        })
    emit('tum_siparisler', orders)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host='0.0.0.0', port=port, allow_unsafe_werkzeug=True, debug=False)
