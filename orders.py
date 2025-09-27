ORDER_TYPE_STOP_MARKET = "STOP_MARKET"

from binance_client import BinanceClient
from config import SYMBOL

class OrderManager:
    def __init__(self, client: BinanceClient):
        self.client = client

    def calcular_cantidad(self, precio, usdt_size, leverage):
        if precio is None or precio == 0:
            print("[ERROR] calcular_cantidad: precio es cero o None")
            return 0
        qty = (usdt_size * leverage) / precio
        return self.client.round_qty(qty)

    def place_grid_buy(self, price, qty, index):
        price = self.client.round_price(price)
        qty = self.client.round_qty(qty)
        cId = f"GRID_BUY_{index}"
        return self.client.place_limit('BUY', price, qty, reduce_only=False, newClientOrderId=cId)

    def place_tp_sell(self, price, qty, tag):
        price = self.client.round_price(price)
        qty = self.client.round_qty(qty)
        cId = f"TP_{tag}"
        return self.client.place_limit('SELL', price, qty, reduce_only=True, newClientOrderId=cId)

    def place_sl_close_position(self, stop_price):
        stop_price = self.client.round_price(stop_price)
        return self.client.place_stop_market_close_position(stop_price)

    def colocar_stop_loss_close_position(self, stop_price):
        stop_price = self.client.round_price(stop_price)
        return self.client.place_stop_market_close_position(stop_price)

    def get_open_orders(self):
        return self.client.get_open_orders() or []

    def cancel_order(self, orderId):
        return self.client.cancel_order(orderId)

    def cancel_all(self):
        return self.client.cancel_all()

    def colocar_orden_limit(self, side, price, qty, reduce_only=False, newClientOrderId=None):
        price = self.client.round_price(price)
        qty = self.client.round_qty(qty)
        return self.client.place_limit(
            side,
            price,
            qty,
            reduce_only=reduce_only,
            newClientOrderId=newClientOrderId
        )

    def reconcile_grid(self, desired_levels: list, qty, price_tolerance=0.5):
        open_orders = self.get_open_orders()
        buy_orders = [o for o in open_orders if o.get('side') == 'BUY']
        to_create = []
        matched_ids = set()

        for i, level in enumerate(desired_levels):
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

        to_cancel = [o for o in buy_orders if o.get('orderId') not in matched_ids]
        for o in to_cancel:
            try:
                self.cancel_order(o['orderId'])
            except Exception:
                pass

        for i, price in to_create:
            try:
                self.place_grid_buy(price, qty, i)
            except Exception:
                pass

        return {'created': len(to_create), 'canceled': len(to_cancel), 'kept': len(matched_ids)}

    def ensure_take_profits(self, avg_entry, qty, open_orders, offset=0.0002):
        """
        Establece TP a +0.3% sobre el precio promedio de entrada.
        Solo crea TP si no existe en rango y mejora el promedio.
        """
        tp_price = self.client.round_price(avg_entry * 1.003)  # 0.3% sobre entrada
        qty = self.client.round_qty(qty)
        tp_orders = [o for o in open_orders if o.get('side') == 'SELL' and o.get('reduceOnly')]
        def is_tp_near(price, target):
            return abs(price - target) / target <= offset
        tp_exists = any(is_tp_near(float(o.get('price')), tp_price) for o in tp_orders if o.get('price'))
        if not tp_exists and tp_price > avg_entry:
            self.place_tp_sell(tp_price, qty, "AUTO_TP")

    def ensure_stop_loss(self, stop_price):
        stop_price = self.client.round_price(stop_price)
        open_orders = self.get_open_orders()
        sls = [o for o in open_orders if o.get('type') in (ORDER_TYPE_STOP_MARKET,'STOP') and o.get('closePosition') in (True,'true','True')]
        tolerance = 0.002
        for o in sls:
            try:
                sp = float(o.get('stopPrice') or 0)
            except Exception:
                sp = 0
            if abs(sp - stop_price)/stop_price <= tolerance:
                return {'kept': True}
            else:
                self.cancel_order(o['orderId'])
        self.place_sl_close_position(stop_price)
        return {'created': True}
