---
name: muvid-promo
description: Cut a short promo, sizzle reel or brand film from phone footage to a music bed, keeping the people's own sound (talking, breath, the room) under the music and the music removable. A yoga or fitness class, a studio, a venue, a workshop, an event, a retreat. Not a music video. Use on "make a promo/marketing video from these clips", "a 60 s / 150 s short for the class/studio", "an Instagram reel or YouTube Short advertising X", "keep the talking but put music over it", "music I can replace later", "stems", "selects", "an arc", "hook, establish, flow, peak, calm". It covers pulling selects, ordering them into an arc, `propose_promo` (holds on bars and phrases), and `render(sound="song_and_clips")` (ducked music, stems, a no-music version).
---

# muvid-promo: a promo cut from chosen shots, music removable

A promo is edited the other way round from a music video. In a music video the planner picks and reuses footage and cuts on the beat (`muvid-montage`). In a promo **you** choose the shots and their order, and the music only decides *where* the changes land: on bar lines and phrases, each shot held 2–6 s, the room's sound kept. The research behind every default (33 rules, 70 references) is [promo_video_editing_and_music.md](https://github.com/reeleehq/muvid/blob/main/misc/docs/research/general/promo_video_editing_and_music.md). Read its section 6 before changing a number.

## The four steps

1. **Music.** It needs a real ending (a final hit or a sustained chord, not a fade), clear 4- and 8-bar phrases and, for a voice to sit on, no vocals. For a class: a little above the class's own tempo (yin 60–80 BPM, hatha 70–90, vinyasa 85–110, power or hot 100–122). Generated with `arioso` (Suno), ask for an explicit BPM, "clear 8-bar phrases", "ends on a sustained final chord, no fade out", instrumental, `duration=` a little longer than the cut. Check the last 3 s decay from a hit rather than ramp down linearly. **The tempo detector often doubles a slow song** (84 BPM reads as 169): a muvid bar is then half a real bar, so pass `phrase_bars=8` for real 4-bar phrases.
2. **Selects.** Survey every clip: speech (a transcript per clip, with `scribed` or mlx-whisper), sharpness and a contact strip of 3–4 frames. Then choose: one striking moving shot for the hook, a wide of the room, the instructor cueing, flow shots, 2+ details (hands, feet, breath, props), the peak pose, faces at rest or smiling, a group shot. Drop blurred, shaky, dark and "thumb on the button" clips. A soundbite must be a complete sentence (read the transcript) and its shot needs `source_in` at the sentence and `min_s` its length.
3. **Order and cut.** Order the selects into the arc, from the research's section 2.2:
   - **60 s:** hook → establish → instructor → flow → peak → calm.
   - **150 s:** hook → arrival → instructor → warm-up → flow → peak → cool-down → community.

   Within a section go wide → medium → close. Tag each shot's `role`: calm, cooldown, savasana, community and close come in with a dissolve when they start on a phrase, and everything else is a hard cut. Then:
   ```python
   out = service.propose_promo(
       fp,
       shots=[{"clip_id": "IMG_1", "role": "hook", "hold_s": 2.5}, ...],
       length_s=60,
       phrase_bars=8,
       name="Promo 60 s",
   )
   out[
       "promo"
   ]  # per shot: role, place on the song, hold, transition; the average shot length
   ```
   `length_s` makes the video end where the song ends and start on the nearest phrase. `span=[a, b]` sets the window exactly. Aim at about 3.5 s a shot (60 s: 16–22 shots; 150 s: 35–50). A refusal says why (too many shots for the window, or clips too short); add or drop shots, or relax `hold_s`/`min_s`/`max_s`.
4. **Render with the sound.**
   ```python
   r = service.render(fp, edit_id=out["edit_id"], sound="song_and_clips")
   r[
       "stems"
   ]  # music, dialogue, nat, clips (= dialogue as mixed + nat), mix (wav); no_music.mp4
   r[
       "mix"
   ]  # how it was mixed: dialogue gain, duck depth, speech and music levels, limiter
   ```
   Each cut's own sound follows the picture cut for cut (40 ms edge fades), at its `sound_db`. A `soundbite` or `nat` shot is at 0 dB and goes in the **dialogue** stem. Every other shot is at −8 dB and goes in the **nat** stem: the room as a bed, which never ducks anything. The dialogue is raised toward −20 dBFS speech level, and the music is ducked under the dialogue alone, by as much as puts the speech 12 dB over it (8–30 dB; env `MUVID_SOUND_*`). A photo, a gap, a retimed cut, a silent clip and a clip that recorded the song itself are all silence. **To replace the music**, keep `no_music.mp4` (or the `dialogue` + `nat` stems) and lay the new track under it. Re-cutting to the new track's bars is a new `propose_promo` with the same shots.

   **Phone clips are often HDR (HLG).** Without an ffmpeg that has `zscale` + `tonemap`, every one renders washed out, and the render says so in `warnings`. Homebrew's ffmpeg lacks `zscale`; imageio-ffmpeg's bundled binary has both. Until muvid#380 gives a setting, put a directory holding an `ffmpeg` symlink to it (and `ffprobe`) first on `PATH`.

## Why it lives here

Weighed against the fleet: `braidio` weaves narration-led productions (speech is the spine and music the bed), `reelee` is the thin app layer, `nw` ships no genres, and `artful` holds storyboards (the arc could become one, later). muvid's footage service already owns free cuts to a song's bars, named editable edits, the renderer and `explain_edit`, so a promo is a new way to fill an edit there, not a new kind of project. The ducker is `mixing.audio.duck_audio`. Text on screen (a title on the hook, an end card with the offer) is `tituli`, composited onto the finished video. Publishing is `yb`.

## Known gaps

- Choosing and ordering selects is done by reading contact strips and transcripts: no content scorer tags shot size, subject or "smiling" yet (muvid#132's visual channels).
- The duck is sized on RMS levels, not LUFS, and lives in muvid until `mixing`'s ducker can target a loudness difference itself (mixing#224).
- No end card or title: that needs the studio's name, offer and schedule (`tituli`).
- No match-on-action pairing, J/L-cuts or speed ramps yet (research rules 12, 15, 21). The follow-ups are in muvid#381.
