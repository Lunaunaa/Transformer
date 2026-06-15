import json
import time
import heapq
from collections import deque, defaultdict
import paho.mqtt.client as mqtt

# ─── MQTT Config ──────────────────────────────────────────────────────────
BROKER   = "localhost"
PORT     = 1883
SUB_TOPIC = "smartguard/sensors"
PUB_TOPIC = "smartguard/processed"

# ─── Thresholds (mirror of ESP32, Pi does the deeper logic) ───────────────
MQ2_SMOKE   = 1500
MQ4_GAS     = 2000
MQ7_CO      = 1000
TEMP_WARN   = 55.0
TEMP_CRIT   = 70.0
HUMIDITY_HIGH = 70.0   # moisture ingress risk

# ─── Transformer Component Graph ──────────────────────────────────────────
# Nodes: components of the dry transformer
# Edges: (from, to, weight)  weight = fault spread cost (lower = faster spread)
#
#   winding1 ── core ── winding2
#       |                  |
#   insulation1        insulation2
#       |                  |
#    casing  ──────────  casing
#
COMPONENTS = [
    "winding1", "winding2", "core",
    "insulation1", "insulation2", "casing"
]

GRAPH = {
    "winding1":    [("core", 1), ("insulation1", 2)],
    "winding2":    [("core", 1), ("insulation2", 2)],
    "core":        [("winding1", 1), ("winding2", 1), ("casing", 3)],
    "insulation1": [("winding1", 2), ("casing", 2)],
    "insulation2": [("winding2", 2), ("casing", 2)],
    "casing":      [("insulation1", 2), ("insulation2", 2), ("core", 3)],
}

# ─── Known Fault Patterns for KMP ─────────────────────────────────────────
# Each pattern is a sequence of event codes.
# The event stream is built from sensor flags each reading.
# Event codes:
#   H = heat warning    C = heat critical
#   S = smoke           G = gas
#   O = CO warning      N = normal (no flags)

FAULT_PATTERNS = {
    "thermal_buildup":    list("HHC"),       # heat warning × 2 then critical
    "smolder_early":      list("OOH"),        # CO rises then heat
    "gas_then_smoke":     list("GGS"),        # gas leak escalating to smoke
    "thermal_runaway":    list("HCHC"),       # oscillating critical heat
    "compound_fault":     list("OHSC"),       # CO → heat → smoke → critical
}

# ─── Isolation Sets for Greedy Set Cover ──────────────────────────────────
# Maps fault type → which components need isolation
FAULT_ISOLATION = {
    "smoke":    {"winding1", "winding2", "insulation1", "insulation2"},
    "gas":      {"winding1", "winding2", "core"},
    "co":       {"insulation1", "insulation2", "core"},
    "heat":     {"winding1", "winding2"},
    "normal":   set(),
}

# ─── Event Stream (rolling window for KMP) ────────────────────────────────
EVENT_STREAM = deque(maxlen=20)   # last 20 readings

# ─── Fault Origin Heuristic ───────────────────────────────────────────────
# Given active flags, which component is most likely the fault origin?
def infer_fault_origin(flags):
    if flags["smoke"] or flags["gas"]:
        return "winding1"       # most common thermal fault origin
    if flags["co"]:
        return "insulation1"    # CO = insulation degradation
    if flags["heat_critical"] or flags["heat_warning"]:
        return "core"
    return None


# ══════════════════════════════════════════════════════════════════════════
# ALGORITHM 1: BFS — Fault Propagation
# Starting from the fault origin, find all components reachable within
# max_hops. These are the components at risk if the fault spreads.
# ══════════════════════════════════════════════════════════════════════════
def bfs_fault_propagation(origin, max_hops=2):
    if origin is None:
        return []
    visited = {origin}
    queue = deque([(origin, 0)])
    at_risk = []
    while queue:
        node, hops = queue.popleft()
        if hops > 0:
            at_risk.append(node)
        if hops < max_hops:
            for neighbor, _ in GRAPH.get(node, []):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, hops + 1))
    return at_risk


# ══════════════════════════════════════════════════════════════════════════
# ALGORITHM 2: Dijkstra — Maintenance Priority Routing
# Given a set of at-risk components, find the minimum-cost inspection
# order starting from "casing" (the accessible external entry point).
# Edge weight = fault severity × component proximity.
# ══════════════════════════════════════════════════════════════════════════
def dijkstra_maintenance_route(at_risk_components, start="casing"):
    if not at_risk_components:
        return [], {}

    dist = {node: float("inf") for node in COMPONENTS}
    dist[start] = 0
    prev = {}
    pq = [(0, start)]

    while pq:
        cost, node = heapq.heappop(pq)
        if cost > dist[node]:
            continue
        for neighbor, weight in GRAPH.get(node, []):
            new_cost = dist[node] + weight
            if new_cost < dist[neighbor]:
                dist[neighbor] = new_cost
                prev[neighbor] = node
                heapq.heappush(pq, (new_cost, neighbor))

    # Return at-risk components sorted by inspection cost (closest first)
    priority_queue = sorted(
        at_risk_components,
        key=lambda c: dist.get(c, float("inf"))
    )
    return priority_queue, dist


# ══════════════════════════════════════════════════════════════════════════
# ALGORITHM 3: KMP — Fault Pattern Matching
# Searches the rolling event stream for known fault patterns.
# Returns list of matched pattern names.
# ══════════════════════════════════════════════════════════════════════════
def kmp_build_failure_table(pattern):
    table = [0] * len(pattern)
    j = 0
    for i in range(1, len(pattern)):
        while j > 0 and pattern[i] != pattern[j]:
            j = table[j - 1]
        if pattern[i] == pattern[j]:
            j += 1
        table[i] = j
    return table

def kmp_search(text, pattern):
    if not pattern or not text:
        return False
    table = kmp_build_failure_table(pattern)
    j = 0
    for i in range(len(text)):
        while j > 0 and text[i] != pattern[j]:
            j = table[j - 1]
        if text[i] == pattern[j]:
            j += 1
        if j == len(pattern):
            return True   # match found
    return False

def kmp_detect_patterns(event_stream):
    stream = list(event_stream)
    matched = []
    for name, pattern in FAULT_PATTERNS.items():
        if kmp_search(stream, pattern):
            matched.append(name)
    return matched


# ══════════════════════════════════════════════════════════════════════════
# ALGORITHM 4: Greedy Set Cover — Minimum Isolation
# Find the smallest set of component groups to isolate that covers all
# active fault types. Classic greedy ln(n) approximation.
# ══════════════════════════════════════════════════════════════════════════
def greedy_set_cover(active_faults):
    # Build universe: all components that need to be covered
    universe = set()
    available = {}
    for fault in active_faults:
        comps = FAULT_ISOLATION.get(fault, set())
        universe |= comps
        if comps:
            available[fault] = comps

    if not universe:
        return []

    covered = set()
    chosen = []

    while covered != universe:
        # Pick the fault group that covers the most uncovered components
        best = max(available.items(), key=lambda x: len(x[1] - covered), default=None)
        if best is None or len(best[1] - covered) == 0:
            break
        chosen.append(best[0])
        covered |= best[1]
        del available[best[0]]

    return chosen


# ══════════════════════════════════════════════════════════════════════════
# Severity Classifier
# ══════════════════════════════════════════════════════════════════════════
def classify_severity(flags):
    if flags["smoke"] or flags["heat_critical"]:
        return "CRITICAL"
    if flags["gas"] or flags["heat_warning"] or flags["co"]:
        return "WARNING"
    return "SAFE"

def flags_to_event_code(flags):
    if flags["heat_critical"]:  return "C"
    if flags["smoke"]:          return "S"
    if flags["gas"]:            return "G"
    if flags["co"]:             return "O"
    if flags["heat_warning"]:   return "H"
    return "N"

def get_active_faults(flags):
    faults = []
    if flags["smoke"]:        faults.append("smoke")
    if flags["gas"]:          faults.append("gas")
    if flags["co"]:           faults.append("co")
    if flags["heat_warning"] or flags["heat_critical"]: faults.append("heat")
    return faults if faults else ["normal"]


# ══════════════════════════════════════════════════════════════════════════
# Main Processing Pipeline
# Called on every MQTT message from ESP32
# ══════════════════════════════════════════════════════════════════════════
def process(payload: dict) -> dict:
    flags    = payload.get("flags", {})
    temp     = payload.get("temp", {})
    humidity = payload.get("humidity", {})
    gas      = payload.get("gas", {})

    # ── Event stream update ───────────────────────────────────────────────
    event_code = flags_to_event_code(flags)
    EVENT_STREAM.append(event_code)

    # ── Severity ──────────────────────────────────────────────────────────
    severity = classify_severity(flags)

    # ── Active faults ─────────────────────────────────────────────────────
    active_faults = get_active_faults(flags)

    # ── BFS: which components are at risk? ────────────────────────────────
    origin   = infer_fault_origin(flags)
    at_risk  = bfs_fault_propagation(origin, max_hops=2)

    # ── Dijkstra: inspection priority order ───────────────────────────────
    priority_order, distances = dijkstra_maintenance_route(at_risk)

    # ── KMP: pattern matches ──────────────────────────────────────────────
    patterns_matched = kmp_detect_patterns(EVENT_STREAM)

    # ── Greedy: minimum isolation set ────────────────────────────────────
    isolate = greedy_set_cover(active_faults)

    # ── Health Score (0–100, lower = worse) ──────────────────────────────
    score = 100
    if flags.get("heat_warning"):   score -= 20
    if flags.get("heat_critical"):  score -= 40
    if flags.get("co"):             score -= 15
    if flags.get("gas"):            score -= 25
    if flags.get("smoke"):          score -= 40
    # humidity penalty
    max_hum = max(
        humidity.get("h1", 0),
        humidity.get("h2", 0),
        humidity.get("h3", 0)
    )
    if max_hum > HUMIDITY_HIGH:     score -= 10
    score = max(0, score)

    result = {
        "ts":              payload.get("ts"),
        "severity":        severity,
        "health_score":    score,
        "active_faults":   active_faults,
        "event_code":      event_code,
        "event_stream":    list(EVENT_STREAM),

        "algorithms": {
            "bfs": {
                "fault_origin": origin,
                "at_risk":      at_risk,
            },
            "dijkstra": {
                "inspection_order": priority_order,
            },
            "kmp": {
                "patterns_matched": patterns_matched,
            },
            "greedy": {
                "isolate_groups": isolate,
            },
        },

        "raw": {
            "temp":     temp,
            "humidity": humidity,
            "gas":      gas,
        }
    }

    return result


# ══════════════════════════════════════════════════════════════════════════
# MQTT Callbacks
# ══════════════════════════════════════════════════════════════════════════
def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print(f"[MQTT] Connected to broker")
        client.subscribe(SUB_TOPIC)
        print(f"[MQTT] Subscribed to {SUB_TOPIC}")
    else:
        print(f"[MQTT] Connection failed rc={rc}")

def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode())
        result  = process(payload)
        output  = json.dumps(result)
        client.publish(PUB_TOPIC, output)

        # Console summary
        alg = result["algorithms"]
        print(
            f"[{result['severity']:<8}] score={result['health_score']:3d}  "
            f"event={result['event_code']}  "
            f"origin={alg['bfs']['fault_origin'] or '-':<12}  "
            f"at_risk={alg['bfs']['at_risk']}  "
            f"patterns={alg['kmp']['patterns_matched']}"
        )

    except Exception as e:
        print(f"[ERROR] {e}")


# ══════════════════════════════════════════════════════════════════════════
# Entry Point
# ══════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message

    print(f"[SmartGuard] Connecting to broker at {BROKER}:{PORT}")
    client.connect(BROKER, PORT, keepalive=60)
    client.loop_forever()