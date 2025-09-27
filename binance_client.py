import time
from binance.client import Client
from binance.enums import *
from binance.exceptions import BinanceAPIException
from config import API_KEY, API_SECRET, SYMBOL, LEVERAGE, PAPER_MODE, USE_TESTNET

class BinanceClient:
    def __init__(self):
        self.client = Client(API_KEY, API_SECRET, testnet=USE_TESTNET)
        # Ajuste de URL para algunas versiones en testnet
        if USE_TESTNET:
            try:
                self.client.FUTURES_URL = 'https://testnet.binancefuture.com/fapi'
            except Exception:
                pass
        # Filtros del símbolo
        self.filters = self._load_symbol_filters(SYMBOL)

        if not PAPER_MODE:
            # Attempt set leverage, ignore if invalid keys
            try:
                self.client.futures_change_leverage(symbol=SYMBOL, leverage=LEVERAGE)
            except Exception as e:
                print(f"[WARN] set leverage: {e}")

    # ---------- Exchange filters ----------
    def _load_symbol_filters(self, symbol):
        try:
            info = self.client.futures_exchange_info()
            for s in info.get('symbols', []):
                if s['symbol'] == symbol:
                    filters = {f['filterType']: f for f in s['filters']}
                    tick = float(filters['PRICE_FILTER']['tickSize'])
                    step = float(filters['LOT_SIZE']['stepSize'])
                    min_qty = float(filters['LOT_SIZE']['minQty'])
                    return {'tickSize': tick, 'stepSize': step, 'minQty': min_qty}
        except Exception as e:
            print(f"[WARN] exchange_info: {e}")
        return {'tickSize': 0.01, 'stepSize': 0.001, 'minQty': 0.001}

    def round_price(self, price):
        tick = self.filters['tickSize']
        return round((round(price / tick)) * tick, 2)

    def round_qty(self, qty):
        step = self.filters['stepSize']
        min_qty = self.filters['minQty']
        # ceil to step
        steps = int(qty / step)
        q = steps * step
        if q < min_qty:
            q = min_qty
        return float(f"{q:.6f}")

    # ---------- Helpers ----------
    def futures_account(self):
        if PAPER_MODE:
            return {'assets': [{'asset':'USDT','availableBalance':'0'}]}
        return self.client.futures_account()

    def get_available_balance(self, asset='USDT'):
        try:
            acc = self.futures_account()
            for a in acc.get('assets', []):
                if a['asset'] == asset:
                    return float(a['availableBalance'])
        except Exception as e:
            print(f"[WARN] get_available_balance: {e}")
        return 0.0

    def futures_position_information(self):
        if PAPER_MODE:
            return []
        return self.client.futures_position_information(symbol=SYMBOL)

    # ---------- Orders ----------
    def futures_create_order(self, **kwargs):
        if PAPER_MODE:
            print(f"[PAPER][CREATE_ORDER] {kwargs}")
            return {'status': 'SIMULATED', 'orderId': -1}
        return self.client.futures_create_order(**kwargs)

    def futures_cancel_all_open_orders(self):
        if PAPER_MODE:
            print("[PAPER] cancelar todas las órdenes")
            return []
        return self.client.futures_cancel_all_open_orders(symbol=SYMBOL)

    def futures_get_open_orders(self):
        if PAPER_MODE:
            return []
        return self.client.futures_get_open_orders(symbol=SYMBOL)

    # ---------- User stream ----------
    def futures_stream_get_listen_key(self):
        if PAPER_MODE:
            return None
        try:
            res = self.client.futures_stream_get_listen_key()
            # Puede ser dict o str según versión
            if isinstance(res, dict):
                return res.get('listenKey')
            return res
        except Exception as e:
            print(f"[WARN] listenKey get: {e}")
            return None

    def futures_stream_keepalive(self, listenKey):
        if PAPER_MODE or not listenKey:
            return None
        try:
            return self.client.futures_stream_keepalive(listenKey=listenKey)
        except Exception as e:
            print(f"[WARN] listenKey keepalive: {e}")

    def futures_stream_close(self, listenKey):
        if PAPER_MODE or not listenKey:
            return None
        try:
            return self.client.futures_stream_close(listenKey=listenKey)
        except Exception as e:
            print(f"[WARN] listenKey close: {e}")

    # ---------- Public price ----------
    def futures_symbol_price_ticker(self):
        try:
            return self.client.futures_symbol_ticker(symbol=SYMBOL)
        except Exception as e:
            print(f"[WARN] ticker: {e}")
            return {'price': None}