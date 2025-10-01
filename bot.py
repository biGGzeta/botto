import asyncio
import time
from datetime import datetime, UTC
from websocket_listener import WebSocketManager
from binance_client import BinanceClient
from orders import OrderManager
from state_manager import StateManager
import strategy

from config import (
    ORDER_USDT_SIZE, SYMBOL, MIN_GRID_SPACING, MAX_GRID_SPACING,
    GRID_RANGE_MIN, GRID_RANGE_MAX, REBALANCE_SECONDS,
    MIN_PROFIT_THRESHOLD, TP_OFFSET_LOW, TP_OFFSET_MID, TP_OFFSET_HIGH,
    STOP_LOSS_PERCENTAGE, PAPER_MODE, MAKER_FEE_RATE,
    ORDER_USDT_SIZE, LEVERAGE, SAFE_SPREAD,
    SAFE_SPREAD_INCREMENT, SAFE_SPREAD_INCREMENT_START,
    TREND_GUARD_WINDOW, TREND_GUARD_UMBRAL_PAUSA,
    TREND_GUARD_UMBRAL_REACTIVA, TREND_GUARD_LOG_INTERVAL
)

from logger import guardar_estado_vivo, guardar_historico
from collections import deque

BOT_VERSION = "v1"

class GridTrendGuard:
    def __init__(self):
        self.price_history = deque()
        self.grid_paused = False
        self.last_log_ts = 0

    def actualizar_precio(self, price):
        now = time.time()
        self.price_history.append((now, price))
        while self.price_history and now - self.price_history[0][0] > TREND_GUARD_WINDOW:
            self.price_history.popleft()

    def promedio(self):
        now = time.time()
        prices = [p for t, p in self.price_history if now - t <= TREND_GUARD_WINDOW]
        if not prices:
            return None
        return sum(prices) / len(prices)

    def check_grid_status(self, price):
        avg = self.promedio()
        now = time.time()
        if avg is not None and price is not None:
            if now - self.last_log_ts > TREND_GUARD_LOG_INTERVAL:
                print(f"[TREND_GUARD] Promedio últimos {TREND_GUARD_WINDOW}s: {avg:.2f} - Precio actual: {price:.2f}")
                self.last_log_ts = now
        else:
            if now - self.last_log_ts > TREND_GUARD_LOG_INTERVAL:
                print(f"[TREND_GUARD] Promedio o precio es None (avg={avg}, price={price})")
                self.last_log_ts = now

        if avg is not None and price is not None:
            if not self.grid_paused and price > avg * (1 + TREND_GUARD_UMBRAL_PAUSA):
                self.grid_paused = True
                print(f"[TREND_GUARD] Grid PAUSADO: precio {price:.2f} > promedio {avg:.2f} +{TREND_GUARD_UMBRAL_PAUSA*100:.2f}%")
            elif self.grid_paused and price <= avg * (1 + TREND_GUARD_UMBRAL_REACTIVA):
                self.grid_paused = False
                print(f"[TREND_GUARD] Grid REACTIVADO: precio {price:.2f} <= promedio {avg:.2f} +{TREND_GUARD_UMBRAL_REACTIVA*100:.2f}%")
        return not self.grid_paused

class GridBot:
    def __init__(self):
        self.client = BinanceClient()
        self.orders = OrderManager(self.client)
        self.state = StateManager()
        self.last_price = None
        self.last_signal = None
        self.current_spacing = (MIN_GRID_SPACING + MAX_GRID_SPACING) / 2
        self.current_range = (GRID_RANGE_MIN + GRID_RANGE_MAX) / 2
        self._last_rebalance = 0
        self._last_price_rest_fetched = 0

        self.last_tp_price = None
        self.last_tp_time = None

        self.last_grid_price = None

        self.trend_guard = GridTrendGuard()

        print(f"[INFO] PAPER_MODE={'ON' if PAPER_MODE else 'OFF'} | ENV={'TEST' if self.client.client.testnet else 'PROD'} | Symbol={SYMBOL}")

    async def proteger_posicion_existente(self):
        pos_info = self.client.futures_position_information()
        qty = 0.0
        entry_price = None
        for pos in pos_info:
            if pos.get('symbol') == SYMBOL:
                qty = float(pos.get('positionAmt', 0))
                entry_price = float(pos.get('entryPrice', 0))
                break
        if abs(qty) > 0.0:
            print(f"[STARTUP] Posición detectada: qty={qty} entry={entry_price}")
            self.state.state['posicion_total'] = abs(qty)
            self.state.state['costo_total'] = abs(qty) * entry_price
            self.state.state['fills'] = []
            open_orders = self.orders.get_open_orders()
            tp_ok = False
            sl_ok = False
            for o in open_orders:
                if o.get('side') == 'SELL' and o.get('reduceOnly'):
                    tp_target = entry_price * (1 + TP_OFFSET_LOW)
                    if abs(float(o.get('price')) - tp_target)/tp_target <= 0.0002:
                        tp_ok = True
                if o.get('type') in ("STOP_MARKET", "STOP") and o.get('closePosition') in (True, 'true', 'True'):
                    sl_ok = True
            if not tp_ok:
                self.orders.place_tp_sell(entry_price * (1 + TP_OFFSET_LOW), abs(qty), "AUTO_TP")
                print(f"[STARTUP] TP repuesto en {self.client.round_price(entry_price * (1 + TP_OFFSET_LOW)):.2f}")
            if not sl_ok:
                self.orders.colocar_stop_loss_close_position(entry_price*(1-STOP_LOSS_PERCENTAGE))
                print(f"[STARTUP] SL repuesto en {self.client.round_price(entry_price*(1-STOP_LOSS_PERCENTAGE)):.2f}")
        else:
            print("[STARTUP] No hay posición abierta al iniciar el bot.")

    async def procesar_trade(self, msg):
        price = msg.get('p') or msg.get('price') or msg.get('c')
        try:
            self.last_price = float(price or self.last_price or 0)
        except Exception:
            print(f"[DEBUG] Trade msg sin precio válido: {msg}")
        self.trend_guard.actualizar_precio(self.last_price)
        sig = strategy.analizar_trade(msg)
        if sig == 'DUMP':
            self.last_signal = sig
            print("[ESTRATEGIA] Caída rápida detectada → spacing MAX")
        await self._rebalance_si_corresponde()

    async def procesar_ticker(self, msg):
        price = msg.get('c') or msg.get('price') or msg.get('p')
        try:
            self.last_price = float(price or self.last_price or 0)
        except Exception:
            print(f"[DEBUG] Ticker msg sin precio válido: {msg}")
        self.trend_guard.actualizar_precio(self.last_price)
        await self._rebalance_si_corresponde()

    async def procesar_depth(self, msg):
        soporte = strategy.analizar_depth(msg, last_price=self.last_price)
        if soporte:
            self.last_signal = soporte
            print(f"[ESTRATEGIA] Soporte detectado en {soporte['precio']} (vol {round(soporte['volumen'],3)}) → spacing MIN")
        await self._rebalance_si_corresponde()

    async def procesar_user(self, msg):
        try:
            if msg.get('e') != 'ORDER_TRADE_UPDATE':
                return
            o = msg.get('o', {})
            s = o.get('S')
            X = o.get('X')
            avg_price = float(o.get('ap') or 0)
            last_filled_qty = float(o.get('l') or 0)
            commission = float(o.get('n') or 0)
            if last_filled_qty > 0 and X in ('PARTIALLY_FILLED','FILLED'):
                if s == 'BUY':
                    self.state.agregar_compra(avg_price, last_filled_qty, fee=commission)
                elif s == 'SELL':
                    self.state.agregar_venta(avg_price, last_filled_qty, fee=commission)
                # Lógica robusta: solo colocar TP/SL si hay posición abierta
                if self.state.state.get('posicion_total', 0.0) > 1e-3:
                    await self.colocar_tp_y_sl_si_corresponde()
                if s == 'SELL' and self.state.state.get('posicion_total', 0.0) < 1e-3:
                    self.last_tp_price = avg_price
                    self.last_tp_time = time.time()
        except Exception as e:
            print(f"[USER] error parse: {e}")

    async def _rebalance_si_corresponde(self):
        if self.last_price is not None:
            puede_operar = self.trend_guard.check_grid_status(self.last_price)
            if not puede_operar:
                return

        now = time.time()
        if self.last_price is None or self.last_price == 0:
            print("[GRID] Precio no válido para rebalanceo, omitiendo... Intentando refrescar desde Binance REST.")
            if now - getattr(self, '_last_price_rest_fetched', 0) > 30:
                try:
                    ticker = self.client.client.futures_symbol_ticker(symbol=SYMBOL)
                    self.last_price = float(ticker['price'])
                    self._last_price_rest_fetched = now
                    print(f"[GRID] Precio refrescado vía REST: {self.last_price}")
                except Exception as e:
                    print(f"[GRID] Error al refrescar precio vía REST: {e}")
            return
        if now - self._last_rebalance < REBALANCE_SECONDS:
            return

        if self.last_grid_price is not None:
            if self.last_price < 0.95 * self.last_grid_price:
                print(f"[WARN] Precio actual ({self.last_price}) está más de 5% debajo del último grid ({self.last_grid_price}), ignorando rebalance.")
                return

        self.current_spacing = strategy.recomendar_spacing(self.last_signal, MIN_GRID_SPACING, MAX_GRID_SPACING)
        self.current_range = strategy.recomendar_rango(self.last_signal, GRID_RANGE_MIN, GRID_RANGE_MAX)
        niveles = strategy.construir_grid(self.last_price, self.current_spacing, self.current_range)
        niveles = await self._cap_por_margen(niveles)

        self._last_rebalance = now
        if not niveles:
            print("[GRID] No hay niveles para grid.")
            return

        contexto = self._get_contexto_log()
        guardar_estado_vivo(contexto)
        guardar_historico(contexto)

        print(f"[GRID] Rebalance spacing={round(self.current_spacing*100,2)}% range={round(self.current_range*100,2)}% niveles={len(niveles)}")
        self.last_grid_price = self.last_price

        try:
            self.orders.cancel_all()
            await asyncio.sleep(0.5)
        except Exception as e:
            print(f"[ERROR] Cancelar todas: {e}")

        open_orders = self.orders.get_open_orders()
        if open_orders:
            print(f"[WARN] Quedaron {len(open_orders)} órdenes abiertas antes de crear grid nuevo")

        avg_entry = self.state.calcular_costo_promedio()
        pos_qty = float(self.state.state.get('posicion_total', 0.0))
        if pos_qty < 1e-3:
            print("[FIX] Posición virtualmente cerrada, reseteando avg_entry a 0 y posición_total a 0.")
            avg_entry = 0.0
            self.state.state['posicion_total'] = 0.0
            self.state.state['costo_total'] = 0.0
            self.state.save_state()

        fills = self.state.state.get('num_fills_grid', 0)
        # Spread dinámico: 0.03% extra por cada fill desde el cuarto en adelante
        if fills > SAFE_SPREAD_INCREMENT_START:
            spread_dinamico = SAFE_SPREAD + (fills - SAFE_SPREAD_INCREMENT_START) * SAFE_SPREAD_INCREMENT
        else:
            spread_dinamico = SAFE_SPREAD

        for p in niveles:
            if p is None or p == 0:
                continue
            if avg_entry and p >= avg_entry:
                print(f"[SAFE GRID] No se coloca orden en {p} porque está por encima del promedio de entrada ({avg_entry})")
                continue
            if avg_entry and ((avg_entry - p)/avg_entry < spread_dinamico):
                print(f"[SAFE GRID] No se coloca orden en {p} porque no mejora el promedio suficiente (spread dinámico={spread_dinamico*100:.4f}% con {fills} fills)")
                continue
            qty = self.orders.calcular_cantidad(p, ORDER_USDT_SIZE, LEVERAGE)
            if qty is None or qty == 0:
                continue
            try:
                self.orders.colocar_orden_limit('BUY', p, qty, reduce_only=False)
            except Exception as e:
                print(f"[ERROR] crear orden grid: {e}")

        # Solo coloca TP/SL si hay posición abierta
        if self.state.state.get('posicion_total', 0.0) > 1e-3:
            await self.colocar_tp_y_sl_si_corresponde()

    async def _cap_por_margen(self, niveles):
        if PAPER_MODE:
            return niveles[:20]
        try:
            avail = self.client.get_available_balance()
            if avail <= 0:
                return niveles[:5]
            max_orders = int(avail // float(ORDER_USDT_SIZE))
            if max_orders <= 0:
                max_orders = 1
            return niveles[:max_orders]
        except Exception:
            return niveles[:10]

    def _tp_threshold_neto(self):
        pos = float(self.state.state.get('posicion_total', 0.0))
        if pos <= 0:
            return None
        avg = self.state.calcular_costo_promedio()
        notional = pos * avg
        fees_compras = float(self.state.state.get('fees_total', 0.0))
        maker_fee_venta = MAKER_FEE_RATE * notional
        threshold = MIN_PROFIT_THRESHOLD + (fees_compras + maker_fee_venta) / notional
        return threshold

    async def colocar_tp_y_sl_si_corresponde(self):
        pos = float(self.state.state.get('posicion_total', 0.0))
        if pos <= 0 or self.last_price is None:
            print("[TP/SL] No hay posición abierta, no se colocan ReduceOnly.")
            return
        avg = self.state.calcular_costo_promedio()
        open_orders = self.orders.get_open_orders()
        tp_offset = TP_OFFSET_LOW
        tp_price = avg * (1 + tp_offset)
        self.orders.ensure_take_profits(avg, pos, open_orders, offset=tp_offset)
        sl_price = avg * (1 - STOP_LOSS_PERCENTAGE)
        self.orders.colocar_stop_loss_close_position(sl_price)

        contexto = self._get_contexto_log()
        guardar_estado_vivo(contexto)
        guardar_historico(contexto)

    def _get_contexto_log(self):
        try:
            position = {
                "qty": float(self.state.state.get('posicion_total', 0.0)),
                "avg": self.state.calcular_costo_promedio(),
                "fees": float(self.state.state.get('fees_total', 0.0)),
            }
            open_orders = self.orders.get_open_orders()
            open_orders_min = [
                {"side": o.get("side"), "price": o.get("price"), "qty": o.get("origQty"), "reduceOnly": o.get("reduceOnly")}
                for o in open_orders
            ]
            take_profits = [o for o in open_orders if o.get("side") == "SELL" and o.get("reduceOnly") in (True, "true", "True")]
            take_profits_min = [
                {"price": o.get("price"), "qty": o.get("origQty"), "clientOrderId": o.get("clientOrderId")} for o in take_profits
            ]
            stop_loss = next((o for o in open_orders if o.get("side") == "SELL" and o.get("type", "") == "STOP_MARKET"), {})
            contexto = {
                "timestamp": datetime.now(UTC).isoformat(),
                "signal": self.last_signal,
                "last_price": self.last_price,
                "position": position,
                "open_orders": open_orders_min,
                "take_profits": take_profits_min,
                "stop_loss": {"price": stop_loss.get("stopPrice")},
                "bot_version": BOT_VERSION,
                "symbol": SYMBOL,
            }
        except Exception as e:
            contexto = {"error": str(e), "timestamp": datetime.now(UTC).isoformat()}
        return contexto

    async def chequeo_post_tp(self):
        while True:
            await asyncio.sleep(300)
            if self.last_tp_price and self.last_tp_time:
                if self.state.state.get('posicion_total', 0.0) < 1e-3:
                    precio_actual = self.last_price
                    if precio_actual and abs(precio_actual - self.last_tp_price)/self.last_tp_price > 0.0015:
                        print("[TP GRID] El precio se alejó >0.15% del TP, reestableciendo el grid.")
                        await self._rebalance_si_corresponde()
                        self.last_tp_price = None
                        self.last_tp_time = None

    async def run(self):
        await self.proteger_posicion_existente()
        asyncio.create_task(self.chequeo_post_tp())
        ws = WebSocketManager()
        async def handler(msg, tipo):
            try:
                if tipo == 'TRADE':
                    await self.procesar_trade(msg)
                elif tipo == 'DEPTH':
                    await self.procesar_depth(msg)
                elif tipo == 'TICKER':
                    await self.procesar_ticker(msg)
                elif tipo == 'USER':
                    await self.procesar_user(msg)
            except Exception as e:
                print(f"[ERROR] Handler {tipo}: {e}")
        await ws.start_all(handler)

if __name__ == "__main__":
    print("[BOT] Iniciando ETH Grid Bot Dinámico...")
    bot = GridBot()
    asyncio.run(bot.run())
