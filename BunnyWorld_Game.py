"""Bunny World — сервер и игра в одном файле (Python 3.12 + Ursina).
Запуск: python bunny_world.py
  1 — создать мир и играть (сервер запустится сам)
  2 — подключиться к другу
Только сервер без окна: python bunny_world.py --server [порт]
Управление: WASD — бег, пробел — прыжок, мышь — камера, Esc — отпустить мышь.
"""
import asyncio
import json
import math
import queue
import random
import socket
import sys
import threading

from ursina import *

# ---------- настройки мира ----------
CHUNK = 16 # размер чанка (клеток)
RADIUS = 4 # сколько чанков вокруг видно
WATER = -2.0 # уровень воды
SEED = 1


# ---------- генерация мира (одинаковая у всех по seed) ----------
def _hash(ix, iz):
    n = (ix * 374761393 + iz * 668265263 + SEED * 1442695041) & 0xFFFFFFFF
    n = ((n ^ (n >> 13)) * 1274126177) & 0xFFFFFFFF
    n ^= n >> 16
    return n / 0xFFFFFFFF


def _vnoise(x, z):
    ix, iz = math.floor(x), math.floor(z)
    fx, fz = x - ix, z - iz
    sx, sz = fx * fx * (3 - 2 * fx), fz * fz * (3 - 2 * fz)
    a, b = _hash(ix, iz), _hash(ix + 1, iz)
    c, d = _hash(ix, iz + 1), _hash(ix + 1, iz + 1)
    return (a + (b - a) * sx) * (1 - sz) + (c + (d - c) * sx) * sz


def height(x, z):
    amp, freq, total, norm = 1.0, 1 / 55, 0.0, 0.0
    for _ in range(4):
        total += _vnoise(x * freq, z * freq) * amp
        norm += amp
        amp *= 0.5
        freq *= 2
    return (total / norm - 0.5) * 40


def terrain_color(x, z, y):
    if y < WATER + 1.0:
        base = (0.93, 0.85, 0.55) # песок
    elif y < 5:
        t = random.Random(int(x) * 7919 + int(z)).random() * 0.08
        base = (0.42 + t, 0.78 - t, 0.36) # трава
    elif y < 9:
        base = (0.60, 0.60, 0.64) # камень
    else:
        base = (0.96, 0.97, 1.0) # снег
    # мягкое «освещение» по наклону
    nx = height(x - 1, z) - height(x + 1, z)
    nz = height(x, z - 1) - height(x, z + 1)
    shade = max(0.65, min(1.1, 0.95 + (nx + nz) * 0.05))
    return Color(min(1, base[0] * shade), min(1, base[1] * shade), min(1, base[2] * shade), 1)


class World:
    def __init__(self):
        self.chunks = {}

    def build(self, cx, cz):
        n = CHUNK
        verts, cols, tris = [], [], []
        for i in range(n + 1):
            for j in range(n + 1):
                x, z = cx * n + i, cz * n + j
                y = height(x, z)
                verts.append(Vec3(x, y, z))
                cols.append(terrain_color(x, z, y))
        for i in range(n):
            for j in range(n):
                a = i * (n + 1) + j
                b, c = a + 1, a + n + 1
                d = c + 1
                tris += [(a, b, c), (b, d, c)]
        root = Entity(model=Mesh(vertices=verts, triangles=tris, colors=cols, static=True),
                      double_sided=True)
        # круглые деревья
        rng = random.Random(_hash(cx, cz) * 1e9)
        for _ in range(3):
            x = cx * n + rng.random() * n
            z = cz * n + rng.random() * n
            y = height(x, z)
            if WATER + 1.5 < y < 6:
                Entity(parent=root, model='cube', color=Color(.5, .33, .2, 1),
                       position=(x, y + .8, z), scale=(.4, 1.6, .4))
                Entity(parent=root, model='sphere', color=Color(.25, .65, .3, 1),
                       position=(x, y + 2.5, z), scale=2.4)
        self.chunks[(cx, cz)] = root

    def update(self, px, pz):
        pcx, pcz = math.floor(px / CHUNK), math.floor(pz / CHUNK)
        need = [(pcx + dx, pcz + dz)
                for dx in range(-RADIUS, RADIUS + 1) for dz in range(-RADIUS, RADIUS + 1)]
        need.sort(key=lambda c: (c[0] - pcx) ** 2 + (c[1] - pcz) ** 2)
        built = 0
        for c in need:
            if c not in self.chunks:
                self.build(*c)
                built += 1
                if built >= 2: # не больше 2 чанков за кадр
                    break
        for c in list(self.chunks):
            if abs(c[0] - pcx) > RADIUS + 1 or abs(c[1] - pcz) > RADIUS + 1:
                destroy(self.chunks.pop(c))


# ---------- зайчик ----------
class Bunny(Entity):
    def __init__(self, name, hex_color, **kw):
        super().__init__(**kw)
        col = color.hex(hex_color)
        self.body = Entity(parent=self)
        b = self.body
        Entity(parent=b, model='sphere', color=col, scale=(1.1, 1.0, 1.2), y=.6) # тело
        Entity(parent=b, model='sphere', color=col, scale=.85, position=(0, 1.3, .45)) # голова
        for s in (-1, 1):
            Entity(parent=b, model='sphere', color=col, scale=(.22, .85, .16),
                   position=(s * .2, 2.0, .4), rotation_z=-s * 12) # уши
            Entity(parent=b, model='sphere', color=Color(1, .7, .8, 1), scale=(.1, .55, .05),
                   position=(s * .2, 2.0, .48), rotation_z=-s * 12) # розовое внутри
            Entity(parent=b, model='sphere', color=Color(.1, .1, .1, 1), scale=.13,
                   position=(s * .2, 1.4, .82)) # глаза
        Entity(parent=b, model='sphere', color=Color(1, .6, .7, 1), scale=.14,
               position=(0, 1.25, .88)) # носик
        Entity(parent=b, model='sphere', color=Color(1, 1, 1, 1), scale=.38,
               position=(0, .6, -.7)) # хвостик
        Text(name, parent=self, y=2.8, scale=12, billboard=True, origin=(0, 0),
             color=Color(1, 1, 1, 1))

    def hop(self, moving):
        self.body.y = abs(math.sin(time.time() * 11)) * .35 if moving else 0


# ---------- сервер (запускается внутри игры у хоста) ----------
WORLD_SEED = random.randint(1, 999999) # один мир для всех игроков
COLORS = ["#ffffff", "#ffd1dc", "#ffe4a8", "#cfe8ff", "#d9c2ff", "#c8f0c8", "#e0b894"]

players = {} # id -> данные игрока
writers = {} # id -> writer
next_id = 1


async def handle(reader, writer):
    global next_id
    pid = next_id
    next_id += 1
    players[pid] = {"name": f"Зайка{pid}", "x": 0.0, "y": 10.0, "z": 0.0,
                    "ry": 0.0, "c": random.choice(COLORS)}
    writers[pid] = writer
    writer.write((json.dumps({"t": "welcome", "id": pid, "seed": WORLD_SEED}) + "\n").encode())
    print(f"+ игрок {pid} подключился ({len(players)} онлайн)")
    try:
        while True:
            line = await reader.readline()
            if not line:
                break
            m = json.loads(line)
            p = players[pid]
            if m.get("t") == "hello":
                p["name"] = str(m.get("name", ""))[:16] or p["name"]
            elif m.get("t") == "move":
                for k in ("x", "y", "z", "ry"):
                    p[k] = float(m[k])
    except (ConnectionError, ValueError):
        pass
    finally:
        players.pop(pid, None)
        writers.pop(pid, None)
        writer.close()
        print(f"- игрок {pid} вышел ({len(players)} онлайн)")


async def broadcaster():
    while True:
        await asyncio.sleep(1 / 15)
        if not writers:
            continue
        data = (json.dumps({"t": "state", "p": players}) + "\n").encode()
        for w in list(writers.values()):
            try:
                w.write(data)
            except Exception:
                pass


async def server_main(port, ready):
    server = await asyncio.start_server(handle, "0.0.0.0", port)
    print(f"Сервер запущен на порту {port}, seed мира: {WORLD_SEED}")
    ready.set()
    asyncio.create_task(broadcaster())
    async with server:
        await server.serve_forever()



def run_server(port, ready):
    asyncio.run(server_main(port, ready))


def local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


# ---------- сеть ----------
class Net:
    def __init__(self, host, port, name):
        try:
            self.sock = socket.create_connection((host, port), timeout=8)
        except OSError as e:
            print(f"Не удалось подключиться к {host}:{port} — {e}")
            sys.exit(1)
        self.sock.settimeout(None)
        self.file = self.sock.makefile("r", encoding="utf-8")
        welcome = json.loads(self.file.readline())
        self.id, self.seed = welcome["id"], welcome["seed"]
        self.inbox = queue.Queue()
        self.send({"t": "hello", "name": name})
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self):
        try:
            for line in self.file:
                self.inbox.put(json.loads(line))
        except Exception:
            pass
        self.inbox.put({"t": "closed"})

    def send(self, msg):
        try:
            self.sock.sendall((json.dumps(msg) + "\n").encode())
        except OSError:
            pass


PORT = 5555
if len(sys.argv) > 1 and sys.argv[1] == "--server":
    p = int(sys.argv[2]) if len(sys.argv) > 2 else PORT
    ev = threading.Event()
    threading.Thread(target=run_server, args=(p, ev), daemon=True).start()
    ev.wait()
    threading.Event().wait() # просто держим сервер включённым

mode = input("1 — создать мир и играть\n2 — подключиться к другу\n> ").strip()
name = input("Твоё имя: ").strip() or "Зайка"
if mode == "2":
    host = input("Адрес сервера друга: ").strip() or "127.0.0.1"
    port = PORT
else:
    host, port = "127.0.0.1", PORT
    ready = threading.Event()
    threading.Thread(target=run_server, args=(port, ready), daemon=True).start()
    ready.wait()
    print(f"\nМир создан! Друзья в локальной сети подключаются к: {local_ip()}")
    print("(через интернет — нужен проброс порта 5555 или туннель)\n")

net = Net(host, port, name)
SEED = net.seed

app = Ursina(title="Bunny World", borderless=False)
Sky()
scene.fog_color = Color(.75, .88, 1, 1)
scene.fog_density = (40, 120)
window.color = Color(.75, .88, 1, 1)

world = World()
water = Entity(model='plane', scale=600, y=WATER, color=Color(.25, .55, .9, .65), double_sided=True)

me = Bunny(name, "#ffffff", position=(0, height(0, 0) + 2, 0))
pivot = Entity()
camera.parent = pivot
camera.position = (0, 0, -9)
camera.rotation = (0, 0, 0)
camera.fov = 80
mouse.locked = True

state = {"yaw": 0.0, "pitch": 25.0, "vy": 0.0, "send_t": 0.0}
others = {} # id -> (Bunny, target)


def input(key):
    if key == 'escape':
        mouse.locked = not mouse.locked


def update():
    dt = time.dt

    # --- камера ---
    if mouse.locked:
        state["yaw"] += mouse.velocity[0] * 90
        state["pitch"] = max(-10, min(70, state["pitch"] - mouse.velocity[1] * 90))
    pivot.position = me.position + Vec3(0, 1.8, 0)
    pivot.rotation = (state["pitch"], state["yaw"], 0)

    # --- движение ---
    f = held_keys['w'] - held_keys['s']
    s = held_keys['d'] - held_keys['a']
    yaw = math.radians(state["yaw"])
    fwd = Vec3(math.sin(yaw), 0, math.cos(yaw))
    right = Vec3(math.cos(yaw), 0, -math.sin(yaw))
    move = fwd * f + right * s
    moving = move.length() > 0
    if moving:
        move = move.normalized()
        me.position += move * 7 * dt
        me.rotation_y = math.degrees(math.atan2(move.x, move.z))
    ground = max(height(me.x, me.z), WATER - 0.4)
    state["vy"] -= 28 * dt
    me.y += state["vy"] * dt
    on_ground = me.y <= ground
    if on_ground:
        me.y = ground
        state["vy"] = 0
        if held_keys['space']:
            state["vy"] = 11
    me.hop(moving and on_ground)

    world.update(me.x, me.z)
    water.position = (me.x, WATER, me.z)

    # --- сеть ---
    state["send_t"] += dt
    if state["send_t"] > 1 / 15:
        state["send_t"] = 0
        net.send({"t": "move", "x": me.x, "y": me.y, "z": me.z, "ry": me.rotation_y})

    while not net.inbox.empty():
        m = net.inbox.get()
        if m["t"] == "closed":
            print("Соединение с сервером потеряно")
            application.quit()
        elif m["t"] == "state":
            seen = set()
            for k, p in m["p"].items():
                pid = int(k)
                if pid == net.id:
                    continue
                seen.add(pid)
                if pid not in others:
                    others[pid] = [Bunny(p["name"], p["c"], position=(p["x"], p["y"], p["z"])), p]
                others[pid][1] = p
            for pid in list(others):
                if pid not in seen:
                    destroy(others.pop(pid)[0])

    for b, p in others.values():
        b.position = lerp(b.position, Vec3(p["x"], p["y"], p["z"]), min(1, dt * 12))
        b.rotation_y = p["ry"]
        b.hop(abs(b.x - p["x"]) + abs(b.z - p["z"]) > .15)


app.run()