
from binance.enums import *
from binance_client import BinanceClient
from config import SYMBOL
from utils import get_logger
logger = get_logger('orders')

class OrderManager:
    def __init__(self, client: BinanceClient):
        self.client = client

    def calcular_cantidad(self, precio, usdt_size, leverage):
        qty = (usdt_size * leverage) / precio
        return self.client.round_qty(qty)

    def place_grid_buy(self, price, qty, index):
        cId = f"GRID_BUY_{index}"
        return self.client.place_limit('BUY', price, qty, reduce_only=False, newClientOrderId=cId)

    def place_tp_sell(self, price, qty, tag):
        cId = f"TP_{tag}"
        return self.client.place_limit('SELL', price, qty, reduce_only=True, newClientOrderId=cId)

    def place_sl_close_position(self, stop_price):
        return self.client.place_stop_market_close_position(stop_price)

    def get_open_orders(self):
        return self.client.get_open_orders() or []

    def cancel_order(self, orderId):
        return self.client.cancel_order(orderId)

    def cancel_all(self):
        return self.client.cancel_all()

    # ---------- Reconcile grid (diff) ----------
    def reconcile_grid(self, desired_levels: list, qty, price_tolerance=0.5):
        # desired_levels: list of desired BUY prices (floats)
        # qty: quantity per order
        # price_tolerance: absolute USD tolerance to match existing orders (e.g., $0.5)
        open_orders = self.get_open_orders()
        buy_orders = [o for o in open_orders if o.get('side') == 'BUY']
        # Map desired -> matched?
        to_create = []
        matched_ids = set()

        for i, level in enumerate(desired_levels):
            # find match near level
            found = None
            for o in buy_orders:
                try:
                    op = float(o.get('price') or o.get('origPrice') or 0)
                except Exception:
                    op = 0
                if abs(op - level) <= price_tolerance and o.get('status','NEW') in ('NEW','PARTIALLY_FILLED'):
                    found = o
                    matched_ids.add(o['orderId'])
                    break
            if not found:
                to_create.append((i, level))

        # cancel extra buy orders not in matched
        to_cancel = [o for o in buy_orders if o.get('orderId') not in matched_ids]
        canceled = 0
        for o in to_cancel:
            try:
                self.cancel_order(o['orderId'])
                canceled += 1
            except Exception as e:
                logger.error(f"cancel {o.get('orderId')} fail: {e}")

        created = 0
        for i, price in to_create:
            try:
                self.place_grid_buy(price, qty, i)
                created += 1
            except Exception as e:
                logger.error(f"place grid buy fail: {e}")

        return {'created': created, 'canceled': canceled, 'kept': len(matched_ids)}

    # ---------- TP/SL dedupe & ensure ----------
    def ensure_take_profits(self, base_price, total_qty, offsets):
        # base_price: avg_cost * (1 + threshold_neto)
        # total_qty: current position qty
        # offsets: list fractions e.g. [0.0003, 0.0005]
        open_orders = self.get_open_orders()
        sell_orders = [o for o in open_orders if o.get('side') == 'SELL' and o.get('reduceOnly') in (True, 'true', 'True')]
        # target prices
        p1 = self.client.round_price(base_price * (1 + offsets[0]))
        p2 = self.client.round_price(base_price * (1 + offsets[1]))
        half = self.client.round_qty(total_qty / 2.0)

        # Try match existing TP1/TP2 by clientOrderId
        existing = {o.get('clientOrderId',''): o for o in sell_orders}
        changes = {'created':0, 'updated':0, 'kept':0}

        def upsert(tag, price_target):
            cid = f"TP_{tag}"
            o = existing.get(cid)
            if o:
                try:
                    current_price = float(o.get('price') or o.get('origPrice') or 0)
                except Exception:
                    current_price = 0
                # if price differs by more than 1 tick, replace
                if abs(current_price - price_target) > 1e-9:
                    # no modify endpoint in futures; cancel+create
                    self.cancel_order(o['orderId'])
                    self.place_tp_sell(price_target, half, tag)
                    changes['updated'] += 1
                else:
                    changes['kept'] += 1
            else:
                self.place_tp_sell(price_target, half, tag)
                changes['created'] += 1

        upsert('A', p1)
        upsert('B', p2)
        return changes

    def ensure_stop_loss(self, stop_price):
        # Ensure single SL closePosition exists near stop_price (+/- 0.2%%)
        open_orders = self.get_open_orders()
        sls = [o for o in open_orders if o.get('type') in ('STOP_MARKET','STOP') and o.get('closePosition') in (True,'true','True')]
        tolerance = 0.002  # 0.2%
        for o in sls:
            try:
                sp = float(o.get('stopPrice') or 0)
            except Exception:
                sp = 0
            if abs(sp - stop_price)/stop_price <= tolerance:
                return {'kept': True}
            else:
                # replace
                self.cancel_order(o['orderId'])
        self.place_sl_close_position(stop_price)
        return {'created': True}
