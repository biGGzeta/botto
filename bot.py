import asyncio
import time
from datetime import datetime, UTC
from websocket_listener import WebSocketManager
from binance_client import BinanceClient
from orders import OrderManager
from state_manager import StateManager
import strategy

from config import (
    SYMBOL, MIN_GRID_SPACING, MAX_GRID_SPACING,
    GRID_RANGE_MIN, GRID_RANGE_MAX, REBALANCE_SECONDS,
    MIN_PROFIT_THRESHOLD, TP_OFFSET_LOW, TP_OFFSET_MID, TP_OFFSET_HIGH,
    STOP_LOSS_PERCENTAGE, PAPER_MODE, MAKER_FEE_RATE,
    ORDER_USDT_SIZE, LEVERAGE, SAFE_SPREAD
)
from logger import guardar_estado_vivo, guardar_historico

BOT_VERSION = "v1"

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
            # Verifica si hay TP/SL activos
            for o in open_orders:
                if o.get('side') == 'SELL' and o.get('reduceOnly'):
                    tp_target = entry_price * 1.003
                    if abs(float(o.get('price')) - tp_target)/tp_target <= 0.0002:
                        tp_ok = True
                if o.get('type') in ("STOP_MARKET", "STOP") and o.get('closePosition') in (True, 'true', 'True'):
                    sl_ok = True
            # Si no existen, crear TP/SL
            if not tp_ok:
                self.orders.place_tp_sell(entry_price*1.003, abs(qty), "AUTO_TP")
                print(f"[STARTUP] TP repuesto en {self.client.round_price(entry_price*1.003):.2f}")
            if not sl_ok:
                self.orders.colocar_stop_loss_close_position(entry_price*(1-STOP_LOSS_PERCENTAGE))
                print(f"[STARTUP] SL repuesto en {self.client.round_price(entry_price*(1-STOP_LOSS_PERCENTAGE)):.2f}")
        else:
            print("[STARTUP] No hay posición abierta al iniciar el bot.")

    async def procesar_trade(self, msg):
        sig = strategy.analizar_trade(msg)
        if sig == 'DUMP':
            self.last_signal = sig
            print("[ESTRATEGIA] Caída rápida detectada → spacing MAX")
        try:
            self.last_price = float(msg.get('p') or self.last_price or 0)
        except Exception:
            pass
        await self._rebalance_si_corresponde()

    async def procesar_depth(self, msg):
        soporte = strategy.analizar_depth(msg)
        if soporte:
            self.last_signal = soporte
            print(f"[ESTRATEGIA] Soporte detectado en {soporte['precio']} (vol {round(soporte['volumen'],3)}) → spacing MIN")
        await self._rebalance_si_corresponde()

    async def procesar_ticker(self, msg):
        try:
            price = float(msg.get('c'))
            self.last_price = price
        except Exception:
            pass
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
                await self.colocar_tp_y_sl_si_corresponde()
        except Exception as e:
            print(f"[USER] error parse: {e}")

    async def _rebalance_si_corresponde(self):
        now = time.time()
        if self.last_price is None or self.last_price == 0:
            print("[GRID] Precio no válido para rebalanceo, omitiendo...")
            return
        if now - self._last_rebalance < REBALANCE_SECONDS:
            return

        self.current_spacing = strategy.recomendar_spacing(self.last_signal, MIN_GRID_SPACING, MAX_GRID_SPACING)
        self.current_range = strategy.recomendar_rango(self.last_signal, GRID_RANGE_MIN, GRID_RANGE_MAX)
        niveles = strategy.construir_grid(self.last_price, self.current_spacing, self.current_range)
        niveles = await self._cap_por_margen(niveles)

        self._last_rebalance = now
        if not niveles:
            print("[GRID] No hay niveles para grid.")
            return

        # --- LOGGING ---
        contexto = self._get_contexto_log()
        guardar_estado_vivo(contexto)
        guardar_historico(contexto)
        # --- END LOGGING ---

        print(f"[GRID] Rebalance spacing={round(self.current_spacing*100,2)}% range={round(self.current_range*100,2)}% niveles={len(niveles)}")

        try:
            self.orders.cancel_all()
            await asyncio.sleep(0.5)
        except Exception as e:
            print(f"[ERROR] Cancelar todas: {e}")

        open_orders = self.orders.get_open_orders()
        if open_orders:
            print(f"[WARN] Quedaron {len(open_orders)} órdenes abiertas antes de crear grid nuevo")

        avg_entry = self.state.calcular_costo_promedio()
        for p in niveles:
            if p is None or p == 0:
                continue
            # SAFE: Solo colocar la orden si está por debajo del promedio y mejora el promedio lo suficiente
            if avg_entry and p >= avg_entry:
                print(f"[SAFE GRID] No se coloca orden en {p} porque está por encima del promedio de entrada ({avg_entry})")
                continue
            if avg_entry and ((avg_entry - p)/avg_entry < SAFE_SPREAD):
                print(f"[SAFE GRID] No se coloca orden en {p} porque no mejora el promedio suficiente (SAFE_SPREAD={SAFE_SPREAD})")
                continue
            qty = self.orders.calcular_cantidad(p, ORDER_USDT_SIZE, LEVERAGE)
            if qty is None or qty == 0:
                continue
            try:
                self.orders.colocar_orden_limit('BUY', p, qty, reduce_only=False)
            except Exception as e:
                print(f"[ERROR] crear orden grid: {e}")

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
            return
        avg = self.state.calcular_costo_promedio()
        open_orders = self.orders.get_open_orders()
        self.orders.ensure_take_profits(avg, pos, open_orders, offset=0.0002)
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

    async def run(self):
        await self.proteger_posicion_existente()
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
