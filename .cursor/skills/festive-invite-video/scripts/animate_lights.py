"""Turn a still invite into a seamless looping MP4 where the hanging lights at the top sway and twinkle.

Only the "hanging region" (top band, deeper at the sides) moves; text and everything below stays still.
Tune --top-limit / --side-limit so the region stops just above the first line of text.
"""
import argparse

import imageio_ffmpeg
import numpy as np
from PIL import Image, ImageFilter


def star(size):
    r = int(size * 1.6)
    g = np.arange(-r, r + 1, dtype=np.float32)
    gx, gy = np.meshgrid(g, g)
    rays = np.exp(-(gy ** 2) / 1.2) * np.exp(-np.abs(gx) / (size * 0.45))
    rays = np.maximum(rays, rays.T)
    core = np.exp(-(gx ** 2 + gy ** 2) / (size * 0.35) ** 2)
    return np.clip(rays + core, 0, 1), r


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("input")
    ap.add_argument("output")
    ap.add_argument("--seconds", type=int, default=6)
    ap.add_argument("--fps", type=int, default=24)
    ap.add_argument("--top-limit", type=float, default=0.223, help="hanging region depth over the centre, as a fraction of height")
    ap.add_argument("--side-limit", type=float, default=0.281, help="hanging region depth at the left/right edges, fraction of height")
    ap.add_argument("--sway", type=float, default=4.0, help="max horizontal sway in pixels at 720px width")
    ap.add_argument("--glints", type=int, default=28)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    rng = np.random.default_rng(args.seed)
    base = np.asarray(Image.open(args.input).convert("RGB")).astype(np.float32)
    H, W = base.shape[:2]
    H -= H % 2
    W -= W % 2
    base = base[:H, :W]
    scale = W / 720
    n_frames = args.fps * args.seconds

    xs = np.arange(W, dtype=np.float32)
    Y, X = np.mgrid[0:H, 0:W].astype(np.float32)
    side = np.clip((np.abs(xs - W / 2) - 230 * scale) / (40 * scale), 0, 1)
    limit = (args.top_limit + (args.side_limit - args.top_limit) * side) * H
    region = np.clip((limit[None, :] + 15 * scale - Y) / (30 * scale), 0, 1)

    lum = base @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
    bright = np.clip((lum - 190) / 60, 0, 1) * region

    cell = max(4, int(14 * scale))
    gh, gw = H // cell + 1, W // cell + 1
    phase = np.kron(rng.uniform(0, 2 * np.pi, (gh, gw)), np.ones((cell, cell)))[:H, :W]
    freq = np.kron(rng.integers(4, 11, (gh, gw)), np.ones((cell, cell)))[:H, :W]

    bmax = np.asarray(Image.fromarray((bright * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(21))) / 255
    cand = np.argwhere((bright >= bmax - 1e-3) & (bright > 0.85))
    rng.shuffle(cand)
    glints = []
    min_d2 = (45 * scale) ** 2
    for y, x in cand:
        if all((y - gy) ** 2 + (x - gx) ** 2 > min_d2 for gy, gx, *_ in glints):
            glints.append((y, x, rng.uniform(0, 2 * np.pi), int(rng.integers(2, 6)), rng.uniform(9, 18) * scale))
        if len(glints) >= args.glints:
            break
    sprites = [star(s) for *_, s in glints]
    warm = np.array([255, 214, 150], dtype=np.float32)
    glint_col = np.array([255, 240, 205], dtype=np.float32)

    writer = imageio_ffmpeg.write_frames(
        args.output, (W, H), fps=args.fps, codec="libx264", pix_fmt_out="yuv420p",
        output_params=["-crf", "18", "-preset", "slow", "-movflags", "+faststart"],
    )
    writer.send(None)
    sway_phase = X / W * 2 * np.pi * 0.8
    depth = np.clip(Y / limit[None, :], 0, 1)
    rows = np.arange(H)[:, None]

    for i in range(n_frames):
        t = i / n_frames
        s = np.sin(2 * np.pi * freq * t + phase)
        frame = base * (1 + 0.35 * bright * s)[..., None]
        glow_src = (bright * np.clip(s, 0, 1) * 255).astype(np.uint8)
        glow = np.asarray(Image.fromarray(glow_src).filter(ImageFilter.GaussianBlur(6 * scale))) / 255
        frame += glow[..., None] * warm * 0.55

        for (gy, gx, ph, k, _), (spr, r) in zip(glints, sprites):
            a = max(0.0, np.sin(2 * np.pi * k * t + ph)) ** 6
            if a < 0.01:
                continue
            y0, y1 = max(gy - r, 0), min(gy + r + 1, H)
            x0, x1 = max(gx - r, 0), min(gx + r + 1, W)
            sub = spr[y0 - (gy - r):y1 - (gy - r), x0 - (gx - r):x1 - (gx - r)]
            frame[y0:y1, x0:x1] += sub[..., None] * glint_col * a
        frame = np.clip(frame, 0, 255)

        dx = args.sway * scale * depth * np.sin(2 * np.pi * 2 * t + sway_phase) * region
        sx = np.clip(X - dx, 0, W - 1)
        x0 = np.floor(sx).astype(np.int32)
        x1 = np.minimum(x0 + 1, W - 1)
        fx = (sx - x0)[..., None]
        warped = frame[rows, x0] * (1 - fx) + frame[rows, x1] * fx
        writer.send(np.ascontiguousarray(warped.astype(np.uint8)))

    writer.close()
    print(f"{n_frames} frames, {len(glints)} glints -> {args.output}")


if __name__ == "__main__":
    main()
