"""Loop a short animated invite and lay a music track under it (loudness-normalised AAC)."""
import argparse
import subprocess

import imageio_ffmpeg


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("video")
    ap.add_argument("audio")
    ap.add_argument("output")
    ap.add_argument("--loops", type=int, default=4, help="total number of times the video plays")
    ap.add_argument("--seconds", type=float, default=24, help="final length")
    args = ap.parse_args()

    ff = imageio_ffmpeg.get_ffmpeg_exe()
    subprocess.run([
        ff, "-hide_banner", "-loglevel", "error", "-y",
        "-stream_loop", str(args.loops - 1), "-i", args.video, "-i", args.audio,
        "-map", "0:v", "-map", "1:a", "-c:v", "copy",
        "-af", "loudnorm=I=-15:TP=-1.5:LRA=9", "-c:a", "aac", "-b:a", "192k", "-ar", "44100",
        "-t", str(args.seconds), "-movflags", "+faststart", args.output,
    ], check=True)
    r = subprocess.run([ff, "-hide_banner", "-i", args.output, "-af", "volumedetect", "-f", "null", "-"],
                       capture_output=True, text=True)
    for line in r.stderr.splitlines():
        if "Duration" in line or "mean_volume" in line or "max_volume" in line:
            print(line.strip())


if __name__ == "__main__":
    main()
