"""Draws the tool's icons (no image library needed): .ico for Windows shortcuts, .png for Linux
menu entries and the window. Run with the tool's Python after changing a design:
    app\\venv\\Scripts\\python.exe app\\icons\\make_icons.py
"""
import os
import struct
import zlib

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SIZES = [16, 24, 32, 48, 64, 128, 256]
SUPERSAMPLE = 4


def hex_colour(value: str) -> np.ndarray:
    return np.array([int(value[i:i + 2], 16) for i in (1, 3, 5)] + [255], np.float32) / 255


def grid(size: int):
    n = size * SUPERSAMPLE
    coords = (np.arange(n) + 0.5) / n
    return np.meshgrid(coords, coords)  # x, y in 0..1, y down


def rounded_rect(x, y, left, top, right, bottom, radius):
    cx, cy = (left + right) / 2, (top + bottom) / 2
    hx, hy = (right - left) / 2 - radius, (bottom - top) / 2 - radius
    dx, dy = np.maximum(np.abs(x - cx) - hx, 0), np.maximum(np.abs(y - cy) - hy, 0)
    return np.hypot(dx, dy) <= radius


def circle(x, y, cx, cy, r):
    return np.hypot(x - cx, y - cy) <= r


def capsule(x, y, x1, y1, x2, y2, r):
    px, py, vx, vy = x - x1, y - y1, x2 - x1, y2 - y1
    t = np.clip((px * vx + py * vy) / (vx * vx + vy * vy), 0, 1)
    return np.hypot(px - t * vx, py - t * vy) <= r


def draw(size: int, layers) -> np.ndarray:
    """layers: (mask function of x, y, colour) painted in order; returns RGBA uint8 size x size."""
    x, y = grid(size)
    image = np.zeros(x.shape + (4,), np.float32)
    for mask, colour in layers:
        m = mask(x, y)[..., None].astype(np.float32)
        image = image * (1 - m) + colour * m
    n = size
    image = image.reshape(n, SUPERSAMPLE, n, SUPERSAMPLE, 4).mean(axis=(1, 3))
    # Straight alpha: colour of covered samples only.
    alpha = image[..., 3:4]
    rgb = np.where(alpha > 0, image[..., :3] / np.maximum(alpha, 1e-6), 0)
    return (np.concatenate([rgb, alpha], -1) * 255 + 0.5).clip(0, 255).astype(np.uint8)


def background(colour):
    return (lambda x, y: rounded_rect(x, y, 0.04, 0.04, 0.96, 0.96, 0.2), hex_colour(colour))


WHITE, LIGHT = hex_colour("#ffffff"), hex_colour("#cfd8dc")


def transcript_icon():
    blue = "#1565c0"
    layers = [background(blue),
              (lambda x, y: rounded_rect(x, y, 0.26, 0.17, 0.74, 0.83, 0.05), WHITE)]
    for row in (0.31, 0.42, 0.53):
        layers.append((lambda x, y, r=row: rounded_rect(x, y, 0.34, r - 0.025, 0.66, r + 0.025, 0.025), LIGHT))
    for i, h in enumerate([0.04, 0.09, 0.06, 0.11, 0.05, 0.08, 0.03]):
        cx = 0.36 + i * 0.047
        layers.append((lambda x, y, cx=cx, h=h: capsule(x, y, cx, 0.70 - h, cx, 0.70 + h, 0.016),
                       hex_colour(blue)))
    return layers


def live_icon():
    return [background("#c62828"),
            (lambda x, y: capsule(x, y, 0.5, 0.27, 0.5, 0.48, 0.11), WHITE),
            (lambda x, y: (np.abs(np.hypot(x - 0.5, y - 0.47) - 0.19) <= 0.03) & (y >= 0.47), WHITE),
            (lambda x, y: rounded_rect(x, y, 0.475, 0.64, 0.525, 0.77, 0.01), WHITE),
            (lambda x, y: rounded_rect(x, y, 0.36, 0.75, 0.64, 0.80, 0.025), WHITE)]


def setup_icon():
    def gear(x, y):
        r, angle = np.hypot(x - 0.5, y - 0.5), np.arctan2(y - 0.5, x - 0.5)
        tooth = (np.mod(angle, np.pi / 4) < np.pi / 9) | (np.mod(angle, np.pi / 4) > np.pi / 4 - np.pi / 18)
        outer = np.where(tooth, 0.31, 0.24)
        return (r <= outer) & (r >= 0.1)
    return [background("#455a64"), (gear, WHITE)]


def png(image: np.ndarray) -> bytes:
    height, width = image.shape[:2]
    raw = b"".join(b"\x00" + image[row].tobytes() for row in range(height))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def ico(images: list[np.ndarray]) -> bytes:
    pngs = [png(image) for image in images]
    header = struct.pack("<HHH", 0, 1, len(pngs))
    offset = 6 + 16 * len(pngs)
    entries = b""
    for image, data in zip(images, pngs):
        size = image.shape[0]
        entries += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    return header + entries + b"".join(pngs)


if __name__ == "__main__":
    for name, layers in (("transcribe", transcript_icon()), ("live", live_icon()), ("setup", setup_icon())):
        images = [draw(size, layers) for size in SIZES]
        with open(os.path.join(HERE, name + ".ico"), "wb") as out:
            out.write(ico(images))
        with open(os.path.join(HERE, name + ".png"), "wb") as out:
            out.write(png(images[-1]))
        print("written", name)
