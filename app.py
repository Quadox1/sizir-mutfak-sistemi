import os
import json
import time
import threading
from datetime import datetime
from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit
import urllib.request

app = Flask(__name__)
app.config['SECRET_KEY'] = 'sizir_alabalik_secret_key_2026'
socketio = SocketIO(app, cors_allowed_origins="*")

# --- TELEGRAM BOT BİLGİLERİ ---
# Kendi Telegram Bot Token ve Chat ID bilgilerini buraya yazabilirsin.
TELEGRAM_BOT_TOKEN = "" 
TELEGRAM_CHAT_ID = ""

# --- CANLI SİPARİŞ DEPOSU (BELLEK) ---
order_counter = 100  # Sipariş Numaratörü (101'den başlayacak)
active_orders = {}   # Active siparişler
GARSONLAR = ["Ahmet", "Mehmet", "Can", "Ünal", "Tuğçe"]
MENÜ_KATEGORİLERİ = {
    "🐟 Balıklar": ["Fırın Alabalık", "Izgara Alabalık", "Kiremitte Alabalık", "Somon"],
    "🥗 Mezeler & Salata": ["Çoban Salata", "Mevsim Salata", "Haydari", "Şakşuka"],
    "🥤 İçecekler": ["Kola", "Fanta", "Ayran", "Şalgam", "Su"],
    "☕ İkram & Tatlı": ["Semaver Çay", "Fırın Helva", "Kiremitte Künefe"]
}


def send_telegram_notification(message):
    """Mutfak ürün çıkardığında Telegram grubuna anlık bildirim gönderir"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print(f"[TELEGRAM BİLDİRİMİ]: {message}")
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
    return render_template('garson.html', garsonlar=GARSONLAR, menu=MENÜ_KATEGORİLERİ)


@app.route('/mutfak')
def mutfak():
    return render_template('mutfak.html')


@app.route('/api/siparis-ver', methods=['POST'])
def siparis_ver():
    global order_counter
    data = request.json

    garson = data.get('garson')
    items = data.get('items', [])  # [{'name': 'Fırın Alabalık', 'qty': 2}, ...]

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
            "status": "hazirlaniyor"  # hazirlaniyor -> hazir
        })

    order_data = {
        "order_id": order_id,
        "garson": garson,
        "time": now_str,
        "items": order_items,
        "status": "aktif"  # aktif -> tamamlandi
    }

    active_orders[order_id] = order_data

    # Mutfak Ekranına Canlı Sipariş Düşür (Socket.IO)
    socketio.emit('yeni_siparis', order_data)

    return jsonify({"status": "success", "order_id": order_id})


@app.route('/api/item-durum-degistir', methods=['POST'])
def item_durum_degistir():
    data = request.json
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

        # Mutfak ekranını güncelle
        socketio.emit('siparis_guncellendi', active_orders[order_id])

        # Telegram Bildirimi Gönder
        msg = f"🔔 <b>SİPARİŞ HAZIR!</b>\n\n<b>Sipariş No:</b> #{order_id}\n<b>Garson:</b> {order['garson']}\n<b>Hazır Olan:</b> {updated_item_name}"
        if all_ready:
            msg += "\n\n✅ <i>Tüm sipariş ürünleri tamamlandı!</i>"
            
        send_telegram_notification(msg)

        return jsonify({"status": "success"})

    return jsonify({"status": "error", "message": "Sipariş bulunamadı"}), 404


@app.route('/api/siparis-sil', methods=['POST'])
def siparis_sil():
    data = request.json
    order_id = str(data.get('order_id'))
    if order_id in active_orders:
        del active_orders[order_id]
        socketio.emit('siparis_silindi', {"order_id": order_id})
        return jsonify({"status": "success"})
    return jsonify({"status": "error"}), 404


@socketio.on('connect')
def handle_connect():
    # Mutfak bağlandığında mevcut tüm aktif siparişleri gönder
    emit('tum_siparisler', list(active_orders.values()))


if __name__ == '__main__':
    # Wi-Fi ağındaki tüm cihazlardan erişilebilmesi için host='0.0.0.0'
    print("\n🚀 Sızır Mutfak Sunucusu Başlatılıyor...")
    print("📲 Garson Giriş Arayüzü : http://localhost:5000")
    print("📺 Mutfak KDS Ekranı     : http://localhost:5000/mutfak\n")
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)