import json
import os
from config import STATE_FILE

DEFAULT_STATE = {
    "grids_activados": [],
    "posicion_total": 0.0,
    "costo_total": 0.0,
    "fees_total": 0.0,
    "fills": [],
    "tp_orders": [],
    "sl_order_id": None
}

class StateManager:
    def __init__(self):
        self.state = DEFAULT_STATE.copy()
        self.load_state()

    def ensure_defaults(self):
        # Completar claves faltantes (migración desde versiones anteriores)
        for k, v in DEFAULT_STATE.items():
            if k not in self.state:
                self.state[k] = v

    def load_state(self):
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE, 'r') as f:
                    self.state = json.load(f)
            except Exception as e:
                print(f"[ERROR] Cargar estado: {e}")
        self.ensure_defaults()

    def save_state(self):
        try:
            os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
            with open(STATE_FILE, 'w') as f:
                json.dump(self.state, f, indent=2)
        except Exception as e:
            print(f"[ERROR] Guardar estado: {e}")

    def agregar_compra(self, precio, cantidad, fee=0.0):
        # Agregar compra y actualizar posición neta
        self.state['grids_activados'].append({"precio": precio, "cantidad": cantidad})
        self.state['posicion_total'] += float(cantidad)
        self.state['costo_total'] += float(cantidad) * float(precio)
        self.state['fees_total'] += float(fee)
        self.state['fills'].append({"side": "BUY", "precio": precio, "cantidad": cantidad, "fee": fee})
        self.save_state()

    def agregar_venta(self, precio, cantidad, fee=0.0):
        cantidad = float(cantidad)
        precio = float(precio)
        # Descontar costo proporcional según avg_cost actual
        avg = self.calcular_costo_promedio()
        costo_reducir = avg * cantidad
        self.state['costo_total'] = max(0.0, float(self.state['costo_total']) - costo_reducir)
        self.state['posicion_total'] = max(0.0, float(self.state['posicion_total']) - cantidad)
        self.state['fees_total'] += float(fee)
        self.state['fills'].append({"side": "SELL", "precio": precio, "cantidad": cantidad, "fee": fee})
        if self.state['posicion_total'] < 1e-8:
            self.resetear_posicion()
        else:
            self.save_state()

    def calcular_costo_promedio(self):
        total_qty = float(self.state.get('posicion_total', 0.0))
        if total_qty <= 0:
            return 0.0
        return float(self.state.get('costo_total', 0.0)) / total_qty

    def resetear_posicion(self):
        self.state = DEFAULT_STATE.copy()
        self.save_state()