"""Extract still frames from an inspiration video so they can be viewed or used as image references."""
import argparse
import subprocess
from pathlib import Path

import imageio_ffmpeg


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("video")
    ap.add_argument("out_dir")
    ap.add_argument("--fps", type=float, default=1.0, help="frames per second to extract")
    args = ap.parse_args()

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-y", "-i", args.video,
                    "-vf", f"fps={args.fps}", str(out / "frame_%03d.png")], check=True)
    for p in sorted(out.glob("frame_*.png")):
        print(p)


if __name__ == "__main__":
    main()
