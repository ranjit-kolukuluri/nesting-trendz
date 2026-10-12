---
name: festive-invite-video
description: Designs festive party invites (Diwali and similar) from an inspiration video, image, or saved webpage, iterates on the design with image edits, then animates the hanging lights and adds original Carnatic-style music (veena or violin, tabla, tambura). Use when the user wants to create or edit an invitation card, animate an invite, or add Indian classical music to an invite video.
disable-model-invocation: true
---

# Festive Invite Video

End-to-end flow: inspiration → still invite (GenerateImage) → edits → brighten → animated lights → music → final MP4.
All scripts live in `scripts/` next to this file; install deps once with
`python -m pip install -r scripts/requirements.txt` (ffmpeg comes from `imageio-ffmpeg`, no system install needed).

Work in a temp folder for intermediates; copy each finished version to the user's Downloads as
`<name>_vN.jpg` so earlier versions are never overwritten.

## 1. Read the inspiration

- **Video**: `python scripts/extract_frames.py <video> <tmp_dir> --fps 1`, then view the frames.
- **Saved webpage** (e.g. Instagram `.html` + `_files/`): the design is the `og:image`. Grep the HTML for
  `og:image` / `og:title`; the image's filename (e.g. `765050938_..._n.jpg`) is in the `_files` folder.
  Other jpgs there are unrelated feed thumbnails. `.download` files are scripts, not video.

Note the layout, palette, decorative elements, typography, and every line of text.

## 2. Generate the invite

Call GenerateImage with the inspiration frame in `reference_image_paths` and the matching `aspect_ratio`
(9:16 for phone/WhatsApp-status layouts). In the prompt:

- Describe the layout region by region (background, top decorations, sides, centre text block, bottom).
- List every text line in order, in quotes, with its font style, and say "spelled exactly, no extra text".
- Check the weekday for the date before writing it.

## 3. Edit iteratively

For each change, pass the **latest** version as the only reference and say:
"Keep EVERYTHING identical (…list key elements and current colours…) EXCEPT …". Always restate the full
final text list so text doesn't drift. After every generation, read the image and check each text line
character by character; regenerate if anything is wrong.

When the user's target is ambiguous (e.g. "change one woman's dress"), pick a sensible one, say which
in the reply, and offer to swap.

## 4. Brighten (if dark)

Image models only brighten slightly. Finish with:
`python scripts/brighten.py <in.jpg> <out.jpg>` (defaults: gamma 0.75, brightness 1.08, saturation 1.10).

## 5. Animate the hanging lights

```
python scripts/animate_lights.py <invite.jpg> <animated.mp4> --seconds 6
```

Sways the top band (pendulum-style, more at the bottom of each string) and twinkles bright bulbs with
star glints; the loop is seamless. `--top-limit` / `--side-limit` (fractions of height, defaults 0.223 /
0.281) must stop just above the first text line — extract a frame and confirm the text is undistorted.

## 6. Music

```
python scripts/compose_music.py <music.wav> --raga hindolam --instrument veena --cycle 2.4 --seconds 24
python scripts/add_music.py <animated.mp4> <music.wav> <final.mp4> --loops 4 --seconds 24
```

- `--raga`: `hindolam` (devotional), `hamsadhwani` (bright, auspicious opener), `mohanam` (joyful).
- `--instrument`: `veena` sounds more natural than `violin` (plucked synthesis hides artefacts better).
- `--cycle`: seconds per 8-beat Adi tala cycle. 3.0 felt too slow, 2.0 fast, 2.4 was preferred.
- Keep `seconds = loops × video length`.

The music is an original synthesis (no copyright issues). The agent cannot listen to audio, so always tell
the user to play it, and report the `mean_volume` / `max_volume` that `add_music.py` prints (aim ≈ −17 dB
mean, peak below −1 dB). If they want real-instrument realism, offer to fit a royalty-free recording they
supply with `add_music.py`.
