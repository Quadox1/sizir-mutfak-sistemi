import os
import json
import urllib.request
import threading
from datetime import datetime
from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.config['SECRET_KEY'] = 'sizir_alabalik_secret_key_2026'

# Render arkasındaki WebSockets ve API istekleri için async_mode='gevent'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='gevent')

TELEGRAM_BOT_TOKEN = ""
TELEGRAM_CHAT_ID = ""

order_counter = 100
active_orders = {}

MENU_ITEMS = [
    "Izgara Balık",
    "Sivas Köfte",
    "Tavuk Kanat",
    "Kiremitte Balık",
    "Kaşarlı Balık",
    "Köz Tabağı"
]

GARSON_HESAPLARI = {
    "ahmet": {"name": "Ahmet", "pass": "1234"},
    "mehmet": {"name": "Mehmet", "pass": "1234"},
    "can": {"name": "Can", "pass": "1234"},
    "unal": {"name": "Ünal", "pass": "1234"},
    "tugce": {"name": "Tuğçe", "pass": "1234"}
}

def send_telegram_notification(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    def run():
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            payload = json.dumps({"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}).encode('utf-8')
            req = urllib.request.Request(url, data=payload, headers={'Content-Type': 'application/json'})
            urllib.request.urlopen(req, timeout=5)
        except Exception as e:
            print(f"[TELEGRAM HATA]: {e}")
    threading.Thread(target=run, daemon=True).start()

@app.route('/')
def index():
    return render_template('garson.html', menu=MENU_ITEMS)

@app.route('/mutfak')
def mutfak():
    return render_template('mutfak.html')

@app.route('/api/login', methods=['POST'])
def garson_login():
    data = request.get_json(silent=True) or {}
    username = str(data.get('username', '')).strip().lower()
    password = str(data.get('password', '')).strip()

    username = username.replace('ı', 'i').replace('ğ', 'g').replace('ü', 'u').replace('ş', 's').replace('ö', 'o').replace('ç', 'c')

    if username in GARSON_HESAPLARI and GARSON_HESAPLARI[username]['pass'] == password:
        return jsonify({"status": "success", "garson_name": GARSON_HESAPLARI[username]['name']})
    
    return jsonify({"status": "error", "message": "Kullanıcı adı veya şifre hatalı!"}), 400

@app.route('/api/siparis-ver', methods=['POST'])
def siparis_ver():
    global order_counter
    data = request.get_json(silent=True) or {}

    garson = data.get('garson')
    items = data.get('items', [])

    if not garson or not items:
        return jsonify({"status": "error", "message": "Eksik veri"}), 400

    order_counter += 1
    order_id = str(order_counter)
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

    active_orders[order_id] = order_data
    socketio.emit('yeni_siparis', order_data)

    return jsonify({"status": "success", "order_id": order_id, "order": order_data})

@app.route('/api/item-durum-degistir', methods=['POST'])
def item_durum_degistir():
    data = request.get_json(silent=True) or {}
    order_id = str(data.get('order_id'))
    item_id = data.get('item_id')

    if order_id in active_orders:
        order = active_orders[order_id]
        updated_item_name = ""
        all_ready = True

        for item in order['items']:
            if item['id'] == item_id:
                item['status'] = "hazir" if item['status'] == "hazirlaniyor" else "hazirlaniyor"
                updated_item_name = f"{item['qty']}x {item['name']}"
            if item['status'] != "hazir":
                all_ready = False

        if all_ready:
            order['status'] = "tamamlandi"

        socketio.emit('siparis_guncellendi', active_orders[order_id])

        msg = f"🔔 <b>SİPARİŞ HAZIR!</b>\n\n<b>Sipariş No:</b> #{order_id}\n<b>Garson:</b> {order['garson']}\n<b>Hazır Olan:</b> {updated_item_name}"
        if all_ready:
            msg += "\n\n✅ <i>Tüm ürünler tamamlandı!</i>"
        send_telegram_notification(msg)

        return jsonify({"status": "success"})

    return jsonify({"status": "error", "message": "Sipariş bulunamadı"}), 404

@app.route('/api/siparis-sil', methods=['POST'])
def siparis_sil():
    data = request.get_json(silent=True) or {}
    order_id = str(data.get('order_id'))
    if order_id in active_orders:
        del active_orders[order_id]
        socketio.emit('siparis_silindi', {"order_id": order_id})
        return jsonify({"status": "success"})
    return jsonify({"status": "error"}), 404

@socketio.on('connect')
def handle_connect():
    emit('tum_siparisler', list(active_orders.values()))

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host='0.0.0.0', port=port, debug=False)
