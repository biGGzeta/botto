API_KEY = ''
API_SECRET = ''


SYMBOL = 'ETHUSDT'
LEVERAGE = 10

# Entorno
PAPER_MODE = False   # Simulación: no llama endpoints privados ni coloca órdenes reales
USE_TESTNET = False # Para operar en testnet cuando PAPER_MODE=False y tengas claves de testnet

# Grid settings
GRID_RANGE_MIN = 0.0015   # 6%
GRID_RANGE_MAX = 0.0086   # 15%
MIN_GRID_SPACING = 0.00075   # 0.3%
MAX_GRID_SPACING = 0.0035  # 0.75%
ORDER_USDT_SIZE = 13    # Capital por orden (se multiplica por leverage implícitamente)
REBALANCE_SECONDS = 26

# Take profit
MIN_PROFIT_THRESHOLD = 0.0020  # 0.30% target p
TP_OFFSET_LOW = 0.002   # 0.3%
TP_OFFSET_MID = 0.0021   # 0.6%
TP_OFFSET_HIGH = 0.0023   # 1%

STOP_LOSS_PERCENTAGE = 0.01


MAKER_FEE_RATE = 0.0002

SAFE_SPREAD = 0.00075  # 0.1%: spread mínimo para que la orden de compra realmente mejore el promedio de entrada

# ... tus otras variables de config ...

# Trend Guard Grid Control
TREND_GUARD_WINDOW = 540      # segundos - promedio móvil para trend guard
TREND_GUARD_UMBRAL_PAUSA = 0.0015   # +0.15% pausar grid si el precio supera este margen sobre el promedio
TREND_GUARD_UMBRAL_REACTIVA = 0.0005  # +0.05% reactivar grid si el precio baja a este margen sobre el promedio
TREND_GUARD_LOG_INTERVAL = 540   # segundos - cada cuánto enviar log del promedio y estado de grid

STATE_FILE = "state.json"
