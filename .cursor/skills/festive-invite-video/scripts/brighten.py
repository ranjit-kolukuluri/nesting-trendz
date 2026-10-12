"""Brighten a dark invite image without changing its content (gamma lift + brightness + saturation)."""
import argparse

from PIL import Image, ImageEnhance, ImageStat


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("input")
    ap.add_argument("output")
    ap.add_argument("--gamma", type=float, default=0.75, help="<1 lifts shadows")
    ap.add_argument("--brightness", type=float, default=1.08)
    ap.add_argument("--saturation", type=float, default=1.10)
    args = ap.parse_args()

    im = Image.open(args.input).convert("RGB")
    before = [round(x) for x in ImageStat.Stat(im).mean]
    lut = [min(255, int(255 * ((i / 255) ** args.gamma))) for i in range(256)]
    im = im.point(lut * 3)
    im = ImageEnhance.Brightness(im).enhance(args.brightness)
    im = ImageEnhance.Color(im).enhance(args.saturation)
    im.save(args.output, quality=95)
    print("mean RGB", before, "->", [round(x) for x in ImageStat.Stat(im).mean], "->", args.output)


if __name__ == "__main__":
    main()
