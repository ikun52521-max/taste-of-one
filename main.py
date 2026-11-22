#!/usr/bin/env python3
"""One Perfect Strawberry.

A single ripe strawberry, huge in frame, glossy with water droplets and
bright highlights, drawn procedurally with the Python standard library only.
Writes one 1024x1024 PNG to $MAKEFUN_OUTPUT_DIR/entry.png (default /output).

Deterministic: fixed seed, no time, no network, no external assets.
"""

import math
import os
import random
import struct
import zlib

W = H = 1024
RNG = random.Random(20261122)

# ---------------------------------------------------------------- utilities

def clamp255(v):
    if v < 0:
        return 0
    if v > 255:
        return 255
    return int(v)


def lerp(a, b, t):
    return a + (b - a) * t


def smoothstep(a, b, x):
    t = (x - a) / (b - a)
    if t < 0.0:
        t = 0.0
    elif t > 1.0:
        t = 1.0
    return t * t * (3.0 - 2.0 * t)


def hash_noise(x, y):
    """Cheap deterministic per-pixel grain in [-1, 1]."""
    n = (x * 374761393 + y * 668265263) & 0xFFFFFFFF
    n = (n ^ (n >> 13)) * 1274126177 & 0xFFFFFFFF
    n = (n ^ (n >> 16)) & 0xFFFFFFFF
    return n / 2147483648.0 - 1.0


# ------------------------------------------------------------- pixel buffer

# rows[y] is a bytearray of 3*W RGB bytes.
rows = [bytearray(3 * W) for _ in range(H)]


def set_px(x, y, r, g, b):
    if 0 <= x < W and 0 <= y < H:
        i = 3 * x
        row = rows[y]
        row[i] = clamp255(r)
        row[i + 1] = clamp255(g)
        row[i + 2] = clamp255(b)


def get_px(x, y):
    i = 3 * x
    row = rows[y]
    return row[i], row[i + 1], row[i + 2]


def fill_ellipse(cx, cy, rx, ry, color):
    """Flat filled ellipse."""
    r, g, b = color
    for dy in range(-ry, ry + 1):
        y = cy + dy
        if y < 0 or y >= H:
            continue
        t = 1.0 - (dy / float(ry)) ** 2
        if t <= 0:
            continue
        dx = int(rx * math.sqrt(t))
        x0 = max(0, cx - dx)
        x1 = min(W - 1, cx + dx)
        row = rows[y]
        for x in range(x0, x1 + 1):
            i = 3 * x
            row[i] = r
            row[i + 1] = g
            row[i + 2] = b


def fill_polygon(points, top_color, bottom_color):
    """Scanline fill of a simple polygon with a vertical gradient."""
    ys = [p[1] for p in points]
    y0, y1 = int(min(ys)), int(max(ys))
    n = len(points)
    for y in range(max(0, y0), min(H - 1, y1) + 1):
        xs = []
        for k in range(n):
            x1, y1p = points[k]
            x2, y2p = points[(k + 1) % n]
            if (y1p <= y < y2p) or (y2p <= y < y1p):
                t = (y - y1p) / float(y2p - y1p)
                xs.append(x1 + t * (x2 - x1))
        if len(xs) < 2:
            continue
        xs.sort()
        xa, xb = int(xs[0]), int(xs[-1])
        f = (y - y0) / float(max(1, y1 - y0))
        r = int(lerp(top_color[0], bottom_color[0], f))
        g = int(lerp(top_color[1], bottom_color[1], f))
        b = int(lerp(top_color[2], bottom_color[2], f))
        row = rows[y]
        for x in range(max(0, xa), min(W - 1, xb) + 1):
            i = 3 * x
            row[i] = r
            row[i + 1] = g
            row[i + 2] = b


# ---------------------------------------------------------------- background

def paint_background():
    cx, cy = 512.0, 470.0
    for y in range(H):
        dy = y - cy
        row = rows[y]
        for x in range(W):
            dx = x - cx
            d = math.sqrt(dx * dx + dy * dy) / 760.0
            if d > 1.0:
                d = 1.0
            # warm dark glow behind the berry, fading to near black
            r = lerp(72, 12, d * d)
            g = lerp(52, 9, d * d)
            b = lerp(40, 11, d * d)
            # vignette corners
            vig = 1.0 - 0.25 * smoothstep(0.55, 1.0, d)
            i = 3 * x
            row[i] = int(r * vig)
            row[i + 1] = int(g * vig)
            row[i + 2] = int(b * vig)


# ------------------------------------------------------------------- shadow

def paint_shadow():
    cx, cy, rx, ry = 512.0, 912.0, 340.0, 52.0
    for y in range(int(cy - ry), int(cy + ry) + 1):
        if y < 0 or y >= H:
            continue
        dy = (y - cy) / ry
        half = rx * math.sqrt(max(0.0, 1.0 - dy * dy))
        row = rows[y]
        for x in range(int(cx - half), int(cx + half) + 1):
            if x < 0 or x >= W:
                continue
            dx = (x - cx) / rx
            d2 = dx * dx + dy * dy
            if d2 >= 1.0:
                continue
            dark = 0.55 * (1.0 - d2)
            i = 3 * x
            row[i] = int(row[i] * (1.0 - dark))
            row[i + 1] = int(row[i + 1] * (1.0 - dark))
            row[i + 2] = int(row[i + 2] * (1.0 - dark))


# ------------------------------------------------------------------ strawberry

# Berry outline: half-width profile as a fraction of max half-width,
# keyed by t (0 = top of berry, 1 = tip).
PROFILE = [
    (0.00, 0.60),
    (0.08, 0.88),
    (0.20, 1.00),
    (0.45, 0.93),
    (0.70, 0.70),
    (0.88, 0.40),
    (1.00, 0.00),
]

Y_TOP = 305
Y_BOT = 895
MAX_HW = 335
CX = 512.0


def half_width(t):
    for k in range(len(PROFILE) - 1):
        t0, w0 = PROFILE[k]
        t1, w1 = PROFILE[k + 1]
        if t0 <= t <= t1:
            f = (t - t0) / (t1 - t0)
            f = (1.0 - math.cos(f * math.pi)) / 2.0
            return MAX_HW * lerp(w0, w1, f)
    return 0.0


def paint_berry():
    for y in range(Y_TOP, Y_BOT + 1):
        t = (y - Y_TOP) / float(Y_BOT - Y_TOP)
        hw = half_width(t)
        # round the shoulders near the very top
        hw *= 0.62 + 0.38 * smoothstep(0.0, 0.14, t)
        if hw < 1:
            continue
        x0 = int(CX - hw)
        x1 = int(CX + hw)
        row = rows[y]
        # vertical colour ramp: bright candy red up top, deep wine red low
        base_r = lerp(240, 142, t ** 1.15)
        base_g = lerp(54, 12, t ** 1.15)
        base_b = lerp(48, 20, t ** 1.15)
        for x in range(x0, x1 + 1):
            nx = (x - CX) / hw  # -1 .. 1 across the berry
            # cylindrical shading: bright centre-left, dark edges
            shade = 1.0 - 0.42 * nx * nx - 0.18 * abs(nx)
            # light comes from upper left: warm rim on the right edge
            rim = 0.16 * smoothstep(0.55, 1.0, abs(nx)) * (1.0 if nx > 0 else 0.4)
            # big soft gloss upper left
            gx, gy = x - 415.0, y - 430.0
            gloss = 105.0 * math.exp(-(gx * gx + gy * gy) / (2.0 * 175.0 * 175.0))
            # tight specular sparkle
            sx, sy = x - 442.0, y - 392.0
            spec = 140.0 * math.exp(-(sx * sx + sy * sy) / (2.0 * 52.0 * 52.0))
            # faint vertical streaks for flesh texture
            streak = 5.0 * math.sin(x * 0.11 + 2.0 * math.sin(y * 0.02))
            grain = 4.0 * hash_noise(x, y)
            r = base_r * shade + gloss + spec + rim * 60 + streak + grain
            g = base_g * shade + gloss * 0.82 + spec * 0.9 + streak * 0.4 + grain
            b = base_b * shade + gloss * 0.75 + spec * 0.85 + grain
            i = 3 * x
            row[i] = clamp255(r)
            row[i + 1] = clamp255(g)
            row[i + 2] = clamp255(b)


# ---------------------------------------------------------------------- seeds

def paint_seeds():
    for r in range(12):
        y = 372 + r * 44
        t = (y - Y_TOP) / float(Y_BOT - Y_TOP)
        if t < 0.05 or t > 0.98:
            continue
        hw = half_width(t) * (0.62 + 0.38 * smoothstep(0.0, 0.14, t))
        span = hw - 46
        if span < 30:
            continue
        n = int(span * 2 / 66)
        offset = 33 if (r % 2 == 0) else 0
        for k in range(-n, n + 1):
            x = int(CX + k * 66 + offset + RNG.uniform(-7, 7))
            yy = y + int(RNG.uniform(-5, 5))
            if abs(x - CX) > span:
                continue
            # dark pit, then pale seed, then a pinprick highlight
            fill_ellipse(x, yy, 13, 19, (128, 22, 28))
            fill_ellipse(x, yy - 1, 8, 13, (246, 216, 132))
            fill_ellipse(x - 2, yy - 6, 3, 4, (255, 244, 200))


# ------------------------------------------------------------------ droplets

def paint_droplets():
    drops = []
    for _ in range(18):
        # deterministic spots on the berry, biased to the lit upper half
        x = int(RNG.uniform(300, 724))
        y = int(RNG.uniform(360, 800))
        t = (y - Y_TOP) / float(Y_BOT - Y_TOP)
        hw = half_width(t)
        if abs(x - CX) > hw - 30:
            continue
        drops.append((x, y, int(RNG.uniform(10, 24))))
    for (x, y, rad) in drops:
        for dy in range(-rad, rad + 1):
            yy = y + dy
            if yy < 0 or yy >= H:
                continue
            half = int(rad * math.sqrt(max(0.0, 1.0 - (dy / float(rad)) ** 2)))
            row = rows[yy]
            for xx in range(x - half, x + half + 1):
                if xx < 0 or xx >= W:
                    continue
                i = 3 * xx
                # glassy bead: lighten toward cool white, stronger at rim
                d = math.sqrt((xx - x) ** 2 + dy * dy) / rad
                lift = 0.52 * (1.0 - d * 0.55)
                row[i] = clamp255(row[i] + (255 - row[i]) * lift * 0.55)
                row[i + 1] = clamp255(row[i + 1] + (245 - row[i + 1]) * lift * 0.5)
                row[i + 2] = clamp255(row[i + 2] + (235 - row[i + 2]) * lift * 0.5)
        # specular dot on each bead
        fill_ellipse(x - rad // 3, y - rad // 3, max(2, rad // 4), max(2, rad // 4),
                     (255, 255, 255))


# ---------------------------------------------------------------- calyx / stem

def paint_calyx():
    # five broad sepals fanning over the top of the berry, each a plump
    # leaf with a bulged midrib so the crown reads as foliage, not spikes
    tips = [(292, 288), (396, 244), (512, 226), (628, 244), (732, 288)]
    for (tx, ty) in tips:
        bx = 512 + (tx - 512) * 0.28
        by = 332
        # bulge direction: perpendicular-ish outward from the berry centre
        mx = int(bx + (tx - bx) * 0.62)
        my = int(by + (ty - by) * 0.55)
        pts = [(int(bx - 34), by), (mx - 26, my), (tx, ty), (mx + 26, my),
               (int(bx + 34), by), (int(bx + 12), by + 18),
               (int(bx - 12), by + 18)]
        fill_polygon(pts, (110, 176, 78), (50, 104, 44))
    # centre star where the sepals meet
    fill_ellipse(512, 324, 48, 20, (64, 122, 52))
    # stem
    fill_polygon([(504, 302), (508, 240), (520, 240), (524, 302)],
                 (126, 92, 46), (96, 66, 32))


# ------------------------------------------------------------------ PNG writer

def write_png(path):
    raw = bytearray()
    prev = bytes(3 * W)
    for row in rows:
        raw.append(2)  # Up filter
        up = bytes((a - b) & 0xFF for a, b in zip(row, prev))
        raw += up
        prev = bytes(row)
    comp = zlib.compress(bytes(raw), 9)

    def chunk(ctype, data):
        c = struct.pack(">I", len(data)) + ctype + data
        c += struct.pack(">I", zlib.crc32(ctype + data) & 0xFFFFFFFF)
        return c

    ihdr = struct.pack(">IIBBBBB", W, H, 8, 2, 0, 0, 0)
    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", ihdr)
    png += chunk(b"IDAT", comp)
    png += chunk(b"IEND", b"")
    with open(path, "wb") as f:
        f.write(png)
    return len(png)


def main():
    out_dir = os.environ.get("MAKEFUN_OUTPUT_DIR", "/output")
    os.makedirs(out_dir, exist_ok=True)
    paint_background()
    paint_shadow()
    paint_berry()
    paint_seeds()
    paint_droplets()
    paint_calyx()
    size = write_png(os.path.join(out_dir, "entry.png"))
    print("wrote entry.png: %d bytes, %dx%d" % (size, W, H))


if __name__ == "__main__":
    main()
