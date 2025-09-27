API_KEY = 'TU_API_KEY'
API_SECRET = 'TU_API_SECRET'

SYMBOL = 'ETHUSDT'
LEVERAGE = 10

# Entorno
PAPER_MODE = True   # Simulación: no llama endpoints privados ni coloca órdenes reales
USE_TESTNET = False # Para operar en testnet cuando PAPER_MODE=False y tengas claves de testnet

# Grid settings
GRID_RANGE_MIN = 0.06   # 6%
GRID_RANGE_MAX = 0.15   # 15%
MIN_GRID_SPACING = 0.003   # 0.3%
MAX_GRID_SPACING = 0.0075  # 0.75%
ORDER_USDT_SIZE = 10    # Capital por orden (se multiplica por leverage implícitamente)
REBALANCE_SECONDS = 10

# Take profit
MIN_PROFIT_THRESHOLD = 0.003  # 0.30% target base
TP_OFFSET_LOW = (0.0003, 0.0003)   # 0.03% y 0.03%
TP_OFFSET_MID = (0.0005, 0.0005)   # 0.05% y 0.05%
TP_OFFSET_HIGH = (0.0005, 0.0007)  # 0.05% y 0.07%

# Fees (ajusta según tu cuenta / VIP / BNB)
MAKER_FEE_RATE = 0.0002
TAKER_FEE_RATE = 0.0004

# SL Global
STOP_LOSS_PERCENTAGE = 0.15  # 15%

# Archivo estado
STATE_FILE = 'data/bot_state.json'