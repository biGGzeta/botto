import asyncio
import json
import websockets
from config import SYMBOL, USE_TESTNET, PAPER_MODE
from binance_client import BinanceClient

WS_FAPI_MAIN = 'wss://fstream.binance.com/ws'
WS_FAPI_TEST = 'wss://stream.binancefuture.com/ws'

class WebSocketManager:
    def __init__(self):
        self.symbol = SYMBOL.lower()
        self.base_ws = WS_FAPI_TEST if USE_TESTNET else WS_FAPI_MAIN
        self.trade_url = f"{self.base_ws}/{self.symbol}@trade"
        self.depth_url = f"{self.base_ws}/{self.symbol}@depth@100ms"
        self.ticker_url = f"{self.base_ws}/{self.symbol}@miniTicker"
        self.user_url = None
        self.listen_key = None
        self._stop = False
        self._client = BinanceClient()

    async def _connect_and_listen(self, url, name, handler):
        backoff = 1
        while not self._stop:
            try:
                async with websockets.connect(url, ping_interval=20, ping_timeout=20) as ws:
                    print(f"[WS] Conectado a {name}")
                    backoff = 1
                    async for msg in ws:
                        try:
                            data = json.loads(msg)
                            await handler(data, name)
                        except Exception as e:
                            print(f"[ERROR] Handler {name}: {e}")
            except Exception as e:
                print(f"[WS] {name} desconectado: {e}. Reintentando en {backoff}s")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)

    async def _user_stream_task(self, handler):
        if PAPER_MODE:
            return
        # Obtener listenKey de forma robusta
        lk = self._client.futures_stream_get_listen_key()
        if not lk:
            print("[WARN] No listenKey disponible: deshabilitando USER stream")
            return
        self.listen_key = lk
        self.user_url = f"{self.base_ws}/{self.listen_key}"

        async def keepalive():
            while not self._stop:
                await asyncio.sleep(30 * 60)  # 30 minutos
                self._client.futures_stream_keepalive(self.listen_key)

        ka_task = asyncio.create_task(keepalive())
        try:
            await self._connect_and_listen(self.user_url, 'USER', handler)
        finally:
            ka_task.cancel()
            try:
                self._client.futures_stream_close(self.listen_key)
            except Exception as e:
                print(f"[USER] close error: {e}")

    async def start_all(self, handler):
        tasks = [
            self._connect_and_listen(self.trade_url, 'TRADE', handler),
            self._connect_and_listen(self.depth_url, 'DEPTH', handler),
            self._connect_and_listen(self.ticker_url, 'TICKER', handler),
        ]
        if not PAPER_MODE:
            tasks.append(self._user_stream_task(handler))
        await asyncio.gather(*tasks)

    def stop(self):
        self._stop = True
