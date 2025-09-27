ORDER_TYPE_STOP_MARKET = "STOP_MARKET"

import time
from binance.client import Client
from binance.enums import *
from binance.exceptions import BinanceAPIException
from config import API_KEY, API_SECRET, SYMBOL, LEVERAGE, PAPER_MODE, USE_TESTNET

import os

class BinanceClient:
    def __init__(self):
        self.client = Client(API_KEY, API_SECRET, testnet=USE_TESTNET)
        if USE_TESTNET:
            try:
                self.client.FUTURES_URL = 'https://testnet.binancefuture.com/fapi'
            except Exception:
                pass
        self.filters = self._load_symbol_filters(SYMBOL)

        if not PAPER_MODE:
            try:
                self.client.futures_change_leverage(symbol=SYMBOL, leverage=LEVERAGE)
            except Exception as e:
                print(f"[WARN] set leverage: {e}")

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
        return float(f"{round(round(price / tick) * tick, 8)}")

    def round_qty(self, qty):
        step = self.filters['stepSize']
        min_qty = self.filters['minQty']
        steps = int(qty / step)
        q = steps * step
        if q < min_qty:
            q = min_qty
        return float(f"{q:.6f}")

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

    def place_limit(self, side, price, qty, reduce_only=False, newClientOrderId=None):
        price = self.round_price(price)
        qty = self.round_qty(qty)
        if price is None or price == 0 or qty is None or qty == 0:
            print("[ERROR] place_limit: precio o qty cero/None")
            return {'status': 'ERROR', 'error': 'price or qty zero'}
        params = {
            'symbol': SYMBOL,
            'side': side,
            'type': ORDER_TYPE_LIMIT,
            'price': float(price),
            'quantity': float(qty),
            'reduceOnly': reduce_only,
            'timeInForce': TIME_IN_FORCE_GTC,
        }
        if newClientOrderId:
            params['newClientOrderId'] = newClientOrderId
        try:
            return self.futures_create_order(**params)
        except BinanceAPIException as e:
            print(f"[ERROR] API Binance place_limit: {e}")
            return {'status': 'ERROR', 'error': str(e)}
        except Exception as e:
            print(f"[ERROR] place_limit: {e}")
            return {'status': 'ERROR', 'error': str(e)}

    def place_stop_market_close_position(self, stop_price):
        stop_price = self.round_price(stop_price)
        if stop_price is None or stop_price == 0:
            print("[ERROR] place_stop_market_close_position: stop_price cero/None")
            return {'status': 'ERROR', 'error': 'stop_price zero'}
        params = {
            'symbol': SYMBOL,
            'side': SIDE_SELL,
            'type': ORDER_TYPE_STOP_MARKET,
            'stopPrice': float(stop_price),
            'closePosition': True,
        }
        try:
            return self.futures_create_order(**params)
        except BinanceAPIException as e:
            print(f"[ERROR] API Binance stop_market_close_position: {e}")
            return {'status': 'ERROR', 'error': str(e)}
        except Exception as e:
            print(f"[ERROR] stop_market_close_position: {e}")
            return {'status': 'ERROR', 'error': str(e)}

    def get_open_orders(self):
        return self.futures_get_open_orders()

    def cancel_order(self, orderId):
        if PAPER_MODE:
            print(f"[PAPER] cancelar orden {orderId}")
            return {'status': 'CANCELLED', 'orderId': orderId}
        try:
            return self.client.futures_cancel_order(symbol=SYMBOL, orderId=orderId)
        except BinanceAPIException as e:
            print(f"[ERROR] cancelar orden {orderId}: {e}")
            return {'status': 'ERROR', 'error': str(e)}
        except Exception as e:
            print(f"[ERROR] cancelar orden {orderId}: {e}")
            return {'status': 'ERROR', 'error': str(e)}

    def cancel_all(self):
        return self.futures_cancel_all_open_orders()

    def futures_stream_get_listen_key(self):
        try:
            res = self.client.futures_stream_get_listen_key()
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

    # Otros métodos de user stream y public price igual que antes...
