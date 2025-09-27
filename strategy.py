import time
from collections import deque

trade_history = deque(maxlen=300)
_last_dump_ts = 0
_last_support_ts = 0
COOLDOWN_MS = 5000

def analizar_trade(trade_msg):
    try:
        price = float(trade_msg.get('p') or 0)
        qty = float(trade_msg.get('q') or 0)
        ts = int(trade_msg.get('T') or 0)
        is_sell = bool(trade_msg.get('m'))
    except Exception:
        return None

    trade_history.append({'price': price, 'qty': qty, 'timestamp': ts, 'sell': is_sell})
    return evaluar_senales()

def evaluar_senales():
    global _last_dump_ts
    if not trade_history:
        return None
    now = trade_history[-1]['timestamp']
    ultimos = [t for t in trade_history if now - t['timestamp'] <= 2000]
    if not ultimos:
        return None
    ventas = [t for t in ultimos if t['sell']]
    vol_ventas = sum(t['qty'] for t in ventas)
    freq = len(ultimos) / 2.0  # trades/s
    if freq > 15 and vol_ventas > 10:
        if now - _last_dump_ts > COOLDOWN_MS:
            _last_dump_ts = now
            return 'DUMP'
    return None

def analizar_depth(depth_msg):
    global _last_support_ts
    bids = depth_msg.get('b') or []
    if not bids:
        return None
    top5_vol = 0.0
    top_bid_price = 0.0
    for i, b in enumerate(bids[:5]):
        try:
            p = float(b[0]); q = float(b[1])
            top5_vol += q
            if i == 0:
                top_bid_price = p
        except Exception:
            continue
    now = int(time.time() * 1000)
    if top5_vol > 100 and now - _last_support_ts > COOLDOWN_MS:
        _last_support_ts = now
        return {'tipo': 'SOPORTE', 'precio': top_bid_price, 'volumen': top5_vol}
    return None

def recomendar_spacing(signal, min_spacing, max_spacing):
    if signal == 'DUMP':
        return max_spacing
    if isinstance(signal, dict) and signal.get('tipo') == 'SOPORTE':
        return min_spacing
    return (min_spacing + max_spacing) / 2.0

def recomendar_rango(signal, min_range, max_range):
    if signal == 'DUMP':
        return max_range
    if isinstance(signal, dict) and signal.get('tipo') == 'SOPORTE':
        return min_range
    return (min_range + max_range) / 2.0

def construir_grid(precio_actual, spacing, range_down):
    niveles = []
    n = int(range_down / spacing)
    for i in range(n):
        price = precio_actual * (1 - spacing * (i+1))
        niveles.append(round(price, 2))
    return niveles
