# Editing short promo videos for a yoga studio, with music and the clips' own sound: research

*2026-11-26 · scope: editing style and structure of yoga, wellness and fitness-studio promos; using the clips' own sound under a music bed; music choice, tempo and structure, and how to prompt a song generator; standard terminology; rules an automatic planner can apply · for: the promo planner in muvid's footage service, which already cuts phone footage on a song's beat grid*

## Summary and recommendations

A yoga-studio promo is not a music video. Its job is to make a viewer feel what one class is like and then tell them how to book. That changes four things the beat-grid editor would otherwise get wrong:

1. **Cut on bars and phrases, not on beats.** In official music videos the most common shot lasts about one beat (two thirds of a 548-video sample); only one fifth settle at one bar [1]. Calm editing sits at the bar level. At 70–90 BPM a bar is 2.7–3.4 s, which is close to present-day film editing (Cutting estimates a mean shot of about 2.5 s for recent films) and slower than advertising [2], [3]. Use a ranked subset of cut points (phrase start > downbeat > beat), which is also what the montage research concluded for music-driven cutting generally [4].
2. **Follow a fixed arc and fit it to the song's sections.** Hook (0–3 s), establish, instructor, flow, peak, community and calm, then an end card on the song's last hit. A longer (about 150 s) cut adds instructor soundbites and follows the class from arrival to savasana. Section boundaries go on musical phrase boundaries.
3. **Keep the room's sound as a separate, ducked layer, and give it moments.** The music is foreground except where the instructor speaks. There it drops until speech is at least 10 LU louder than the music; aim for 12–15 LU on phones [5]. Between those moments, short "nat sound pops" (an exhale, a bell, a laugh, a cue such as "inhale") play at full level while the music dips. Everything stays on separate stems so the music can be removed or replaced [6].
4. **The music must end, not fade.** Choose or generate a track with clear 4- and 8-bar phrases and a real ending. Edit it to length by removing whole sections at bar lines [7]. Anchor the ending to the last frame first and fill backwards [8]. The end card sits on the final hit and its decay.

Section 6 turns this into 33 numbered rules. No measured shot-length statistics exist for yoga or wellness promos specifically. The shot-length bands for this genre are editorial judgement anchored to film, commercial and music-video measurements, and are labelled as such. A cheap way to replace them with measured numbers is in *Open questions*.

## What already exists (in-house)

| Asset | What it covers | What it does not cover |
|---|---|---|
| muvid-montage research: methods, libraries, apps [4], [9], [10] | Music-driven cutting as an assignment problem; a ranked cut-candidate score c(t) over beats, downbeats, section boundaries and onsets; AutoMatch's finding that editors cut on a context-chosen subset of beats; BEAT's energy-adaptive cut bonus; snap, slip and speed-ramp to land visual accents on musical ones; a licence-clean beat, downbeat and section stack (Beat This!, librosa, SongFormer/MSAF) | Promo structure, shot-type order, transitions, the clip's own sound, music choice, delivery |
| `mixing.audio.audio_ops.duck_audio` [11] | Sidechain-style ducking: default −12 dB depth, 50 ms attack, 400 ms release, 200 ms hold | Depth defined by a loudness *difference* target (see rule 17) |
| `mixing.loudness` [12] | BS.1770 / EBU R128 integrated loudness and loudness range | Nothing missing for this use |
| `tituli` [13] | Captions, lower thirds, end cards, delivery safe zones (`Frame.with_delivery`) | The vertical-platform zone numbers below should feed its delivery presets |
| `arioso` [14] | Song generation behind one `generate()` (Suno-style and other backends) | A prompt template for promo beds (section 4.5) |

Nothing in the fleet covered promo or marketing editing, or music choice for wellness promos, before this report.

## 1. Terminology

Use these names in code and docs. They are the established terms, so later searches find the literature.

| Term | Meaning | Suggested code name |
|---|---|---|
| Promo (promo video) | Umbrella term for short marketing video: trailers, teasers and sizzle reels [15] | `promo` |
| Sizzle reel | Short, fast-cut highlight piece. Its energy comes from quick cuts, music and on-screen text rather than narration; it aims to excite, not explain. Usually 60 s or less [16] | `genre="sizzle"` |
| Brand film | Longer piece built on a narrative voice and point of view (mission, origin, people), often several minutes [16] | `genre="brand_film"` |
| A-roll / B-roll | A-roll is the primary content (interview, instructor speaking to camera). B-roll is the supporting cutaway footage (class in motion, details, space) | `role="a_roll" \| "b_roll"` |
| Soundbite / SOT | A short clip of a person speaking, used with its own sound ("sound on tape") | `Soundbite` |
| Nat sound (natural sound, ambi, NAT) | The real sound recorded with the picture: room tone, breath, footsteps, a bell. Not a manufactured sound effect [17], [18] | `nat` stem |
| Nat sound pop / nat break | A brief moment where natural sound plays at full level and the music or narration steps back, to punctuate the piece [19], [20] | `NatPop` |
| Music bed | Music running under picture and speech | `music` stem |
| Ducking | Lowering the music automatically while speech is present [21] | `duck` |
| Split edit, J-cut, L-cut | Picture and sound change at different times. J-cut: the next shot's sound starts before its picture. L-cut: the previous shot's sound continues over the next picture [22] | `audio_lead_s`, `audio_tail_s` |
| Match cut / match on action | A cut between two shots joined by matching movement or shape; cutting on action hides the cut [23] | `match_on="action"` |
| Insert / detail shot | A close-up of a detail (hands, feet, breath, light) cut into a wider sequence | `shot_size="detail"` |
| ASL (average shot length) | Mean shot duration of a cut; the standard pacing measure in film statistics [3] | `asl_s` |
| Pacing | Number of camera changes in a message per unit time [24] | `cuts_per_30s` |
| Speed ramp | A change of playback speed inside one shot (for example 100% to 25% to 100%) | `SpeedRamp` |
| Conform | Playing high-frame-rate footage at the timeline rate, so 120 fps becomes 4× slow motion at 30 fps [25] | `conform_fps` |
| Dissolve / cross-dissolve; dip to black/white | Gradual blend between two shots; a fade through a colour [26] | `Transition` kinds |
| End card / CTA | The closing frame with logo, offer and call to action | `EndCard` |
| Safe zone | Region of the frame not covered by platform UI [27] | `delivery` preset |
| Stems; DME; M&E | Separate submixes of dialogue, music and effects that sum to the full mix; M&E is the music-and-effects mix with no dialogue [6], [28] | `stems={"dialogue","nat","music"}` |
| Backtiming | Placing the music's ending against the last frame first, then fitting the rest backwards [8] | `anchor="end"` |
| Phrase | A musical unit, normally 4 or 8 bars in popular music [29] | `phrase` |

## 2. Editing style

### 2.1 Shot length: what is measured, and what follows for yoga

There is no published measurement of shot length in yoga or wellness promos. The neighbouring measurements:

- **Feature films.** Mean shot length fell from about 12 s in 1930 to a few seconds today; Cutting's widely quoted figure is about 2.5 s for recent films [2]. His group's measurements match Bordwell's, and later films also have more motion and are darker [3].
- **TV commercials.** By 1991 the average commercial shot was under 2 s, about half its length in the early 1980s [30]. That figure is old; present-day social ads are probably no slower, but no recent measurement was found.
- **Music videos.** In 548 official music videos, TransNet shot detection gave a mean shot of 4.76 s. The *most common* shot duration matched one beat in two thirds of the videos and one bar in one fifth. A 4-bar pattern almost never set the shot length (2 videos) [1]. A single-video study found an average around 2 s, mostly close shots [31]. The 4.76 s mean is probably inflated, because a 0.5 detection threshold misses dissolves and some fast cuts. The modal figure is the more useful one.
- **Pacing and arousal.** Faster pacing (more camera changes) raises physiological and self-reported arousal [24]. When the edits are *related* (the same scene), more edits raise attention and memory without much extra cognitive load [32]. Cognitive overload appears at about ten or more *unrelated* scene changes in a 30 s message [33]. That figure is reported second-hand; the exact cut counts in the original were not verified.

Conclusions for a yoga promo, as editorial judgement: the arc should move from a fast hook to calm holds. The body of the piece sits at about 2–4 s per shot, which is slower than an ad (<2 s) and roughly the level of present-day film. The calm close holds 4–6 s per shot. A HIIT or gym promo, by contrast, cuts at 0.5–1.5 s on beats (an estimate; no source measures it). Count related cuts (the same pose from two angles) as cheaper than unrelated ones: a flow sequence of one student can cut faster than a montage of different rooms [32].

Expressed in musical units, which is how the planner should store it:

| Tempo | Beat | Bar (4/4) | 2 bars | Suggested use |
|---|---|---|---|---|
| 64 BPM | 0.94 s | 3.75 s | 7.5 s | Yin, restorative, meditation: 1 bar per shot; hook ½ bar; calm close 1–2 bars |
| 76 BPM | 0.79 s | 3.16 s | 6.3 s | Hatha, slow flow: 1 bar per shot; hook ½ bar |
| 90 BPM | 0.67 s | 2.67 s | 5.3 s | Vinyasa: 1 bar; flow section ½ bar; holds 2 bars |
| 120 BPM | 0.50 s | 2.00 s | 4.0 s | Power or hot-yoga promo on organic house: 1–2 bars; build ½ bar; holds 2–4 bars |

### 2.2 Structure for a short (about 60 s) and a long (about 150 s) cut

Practitioner guides for studios recommend the same ingredients: real classes with real students, a teacher adjusting a pose, an opening or closing meditation, the space in natural light, varied angles from wide to close, authenticity over polish, and a specific call to action [34], [35]. The order below is editorial judgement built from those ingredients, from platform hook guidance [36], and from the music-video practice of faster cutting near climaxes and slower cutting in bridges [1].

**60 s template (about 16–22 shots).** Times assume an 80–100 BPM track with 8-bar phrases (about 20–24 s per phrase). Snap each boundary to the nearest phrase or downbeat.

| Section | Time | Shots | Shot length | Content | Sound |
|---|---|---|---|---|---|
| Hook | 0–3 s | 1–3 | 0.5–1 bar | The most striking moving image (a balance, an inversion, a sweep of arms in light) and a title in text | Music starts at once (no slow intro), or a nat pop (a bell, an "inhale" cue) |
| Establish | 3–10 s | 2–3 | 1 bar | Studio exterior or doorway, the room wide, mats and light | Music; room tone under it |
| Instructor | 10–20 s | 2–4 | 1–2 bars | Teacher medium shot, cueing; a hands-on adjustment | One soundbite of 2–5 s, music ducked; J-cut into it |
| Flow | 20–38 s | 5–8 | ½–1 bar | Students moving through a sequence; matches on action; detail inserts (hands, feet, breath, sweat, light) | Music at full level; one or two nat pops |
| Peak | 38–46 s | 1–2 | 2 bars | The peak pose, possibly slow motion or a speed ramp landing on the downbeat | Music swell or drop |
| Community / calm | 46–54 s | 2–3 | 1–2 bars | Savasana, smiles, chatting after class, tea | Music thins out; dissolves allowed |
| End card | 54–60 s | 1 | 3–6 s | Logo, offer, schedule or URL, button | The song's final hit and decay |

**150 s template (about 35–50 shots).** This is closer to a brand film [16]. It follows the class itself, so the editor can use the footage in recorded order:

1. Hook (0–5 s), as above.
2. Arrival (5–20 s): door, shoes off, mats unrolled, greetings. Nat sound carries this section.
3. Instructor introduction (20–45 s): 2–3 soundbites about the class or its philosophy (5–10 s each), covered with B-roll through L-cuts.
4. Warm-up and breath (45–70 s): slow holds and a breath nat pop.
5. Flow and build (70–105 s): the fastest section, ½–1 bar per shot, matches on action.
6. Peak (105–118 s): one or two held or slowed shots on the musical climax.
7. Cool-down and savasana (118–135 s): long holds (2 bars and more), dissolves, the music thinning.
8. Community and CTA (135–150 s): smiles, a one-line student or instructor soundbite, the end card on the last hit.

A 150 s cut needs two musical arcs, or one track with a breakdown that falls between sections 4 and 5. Above 180 s, Instagram warns that the reel will not be recommended to new audiences [37], so 150 s leaves margin.

### 2.3 Shot order, match cuts and continuity

- **Wide → medium → close within a sequence**, then a detail insert, then wide again to reset. This is the classical establishing pattern. Studio guides ask for shots from wide to close and everything in between [34].
- **Change size or angle by at least 30°** between consecutive shots of the same subject, or it reads as a jump cut [38].
- **Match on action**: cut from one student's arm rising to another's arm at the same phase, or from a wide shot of a movement to its close-up mid-movement [23]. Murch ranks the criteria for a cut as emotion (51%), story (23%), rhythm (10%), eye trace (7%), the 2D screen plane (5%) and 3D space (4%) [39]. For a beat-driven editor, rhythm is one criterion of six: never truncate a pose mid-motion only to hit a beat. One critic argues that eye trace counts for more in fast-paced video than Murch suggests [40], so in fast sections keep the subject in the same region of the frame across the cut.
- **People over spaces.** Faces and hands-on adjustments carry emotion. Empty-room shots belong only in the establishing section.

### 2.4 Slow motion and speed ramps

Phones record 120 or 240 fps slow motion. Conforming plays every frame at the timeline rate (120 fps at 30 fps gives 4× slow motion), with natural motion blur for the high shutter speed [25]. Conforming also slows the audio, so a slowed clip has no usable sound and must be muted [25]. The montage research already covers using slip and speed ramps to land a visual accent on a musical one [4].

Editorial judgement for yoga: use slow motion on flowing movement (an arm sweep, hair, fabric, a transition into the peak pose), never on held static poses, where it is invisible and wastes the frame-rate budget. Keep it to about a fifth of the runtime at most, concentrated in the peak and calm sections. Use ramps (100% → 30–50% → 100%) to make a movement complete exactly on a downbeat.

### 2.5 Transitions

- **The hard cut is the default.** Over-using transitions is the mark of an amateur editor [41].
- **Dissolves mean time passing, a change of place, or a link between shots.** They slow the action and feel gradual and comforting [26]. A standard dissolve lasts 24–48 frames (1–2 s at 24 fps). Short ones read almost as cuts, long ones feel dreamlike [42]. Short dissolves of 6–12 frames soften a jump cut [26].
- **For a yoga promo**: hard cuts in the hook, establish, instructor and flow sections. Dissolves of about half a beat to one beat only in the cool-down and calm sections, and only at phrase boundaries. A dip to white or black at most once, between the class and the end card. No wipes or spins.
- **A fade-to-black ending is wrong for a loop.** See rule 27.

### 2.6 Colour

Wellness promos lean warm: a warm white balance, low-contrast "morning light" with creamy highlights and soft shadows, skin protected from turning orange, and greens desaturated so plants do not compete [43]. A studio brand guide argues the opposite way, for natural light and minimal editing with no heavy filters, for authenticity [44]. The sources are vendor blogs, not industry standards. For an automatic editor the safe rule is to match the clips to each other first (phone footage from different devices and windows varies), then apply a light warm grade, never a strong look.

### 2.7 Vertical-platform norms

- **Hook.** TikTok's own guidance is to put the hook in the first 6 s and state the proposition in the first 3 s [36].
- **On-screen text.** TikTok recommends 5–10 words per second when text is used [36]. Captions should be burnt in for the key message.
- **Sound on or off: the evidence conflicts.** 88% of TikTok users say sound is essential to the experience [45]. In a survey, only 47% of Instagram users and 45% of Facebook users said they use the app with sound on most or all of the time [46]. Design for both: the story must read with the sound off (text for the offer and the schedule), and the sound must reward a listener.
- **Length.** Reels and YouTube Shorts both allow 3 minutes, Reels since January 2025 [47] and Shorts since October 2024 [48]. Data on length conflicts. Buffer found 90–179 s Reels gained reach and those over 180 s lost about half of it [37]. Socialinsider found Reels engagement and views rising with length up to 120–180 s, and TikTok engagement best under 30 s [49]. Both are correlational. A short (about 60 s) and a long (about 150 s) cut both fall within the ranges these studies favour.
- **Safe zones (1080×1920).** No platform publishes official zones for organic posts, so these are community estimates [27]. TikTok: keep 108 px clear at the top, 320 px at the bottom, 60 px on the left and 120 px on the right [50]. Reels: conservative figures range from 210 px top and 310 px bottom to 270 px top and 670 px bottom for ads [51]. The common safe area is about 900×1400 px centred [51]. Text, faces and the end-card logo stay inside it.
- **End screen.** On YouTube, end-screen elements occupy the last 5–20 s of a video of at least 25 s [52]. For vertical social video, 3–6 s of end card is editorial judgement: long enough to read the offer at 5–10 words per second, short enough not to lose the loop.
- **Loops.** Reels and Shorts replay automatically. Making the last shot flow back into the first (a matching frame or movement, no audible click at the join) can earn replays, but does not double watch time, and YouTube's engaged views exclude loops [53], [54].

## 3. The clips' own sound under a music bed

### 3.1 Roles

In a music-led promo the music is foreground and the room is texture. Speech reverses that. Broadcast news has the same three-layer logic: voice, soundbites and a NAT track that the system ducks whenever voice or a soundbite is present [21]. Video journalists cut full-volume natural sound between stretches of narration to keep viewers engaged [19], and great natural sound can tell a story faster than words [20]. Natural sound is captured, not manufactured: an audio picture of the place [18].

### 3.2 Levels: how far to duck

| Situation | Measured or recommended difference | Source |
|---|---|---|
| Speech over music | At least **10 LU** (speech louder) | Listening test, 22 participants [5] |
| Speech over ambience | At least **15 LU** | [5] |
| Non-experts vs experts | Non-experts prefer differences about **4 LU larger** than experts do | [5] |
| Accessibility (WCAG 1.4.7, level AAA) | Background at least **20 dB** below foreground speech | [55] |
| Practitioner duck depth | Music 18–22 dB under dialogue; Premiere auto-duck start at −18 dB | [56] |
| In-house default | `duck_audio` duck depth −12 dB | [11] |

Ducking depth (dB of gain reduction) and loudness difference (LU between the layers) are not the same quantity. A −12 dB duck on music that started 2 LU under the speech yields a 14 LU difference. The planner should target the *difference* and compute the depth from measured loudness. Recommended targets: speech ≥ 12 LU above the ducked music, nearer 15 LU for phone delivery, because the viewers are non-experts and the speakers are small [5]. Use an instrumental, sparse, mid-range-light track under speech, because a vocal or busy midrange masks speech [57], [29].

When no one speaks, the room bed should sit well under the music. By analogy with the speech-over-ambience figure [5], about 15 LU under is a starting point (editorial judgement). It should be audible as presence, not as noise.

### 3.3 Nat sound pops

No source gives a duration. Editorial judgement, from news practice: a pop is 0.5–3 s of natural sound at full level (a bell, an exhale, a laugh, a mat unrolling, the cue "and inhale"), with the music dipped 6–12 dB (or out) and ramped back over 100–300 ms. Place it at a phrase boundary or a rest in the music, so it does not fight the beat. Use one or two in 60 s and three to five in 150 s. A breath pop works best on a slow shot of a chest or a face exhaling.

### 3.4 Soundbites and split edits

- Feature the instructor's voice only when a phrase is short, clear and self-contained: a cue ("let your shoulders soften"), a welcome, or one line of philosophy. That means 2–5 s in the 60 s version and 5–10 s in the 150 s version (editorial judgement).
- **J-cut into it**: start the voice 0.5–1.5 s before cutting to the speaker. **L-cut out of it**: let the sentence finish over the next B-roll shot. Keep split edits short, a few seconds at most [58], [22].
- Duck with an attack of tens of milliseconds and a release of a few hundred, so the music does not pump between words. `duck_audio`'s 50 ms / 400 ms / 200 ms hold is a sound default [11].

### 3.5 Delivery: keep the music removable

Professional deliveries keep dialogue, music and effects as separate stems that sum exactly to the full mix, labelled as such [6]. For nonfiction without a Foley budget, Netflix accepts a dialogue stem plus married music and effects stems [59]. Music levels in the M&E must not change from the original mix [28]. For a promo this means:

- Render and keep `dialogue` (soundbites), `nat` (room, breath, pops) and `music` stems, sample-aligned and the same length, plus the summed mix.
- Store the duck and pop gains as **automation data on the timeline**, not baked into the stems, so a different song can be laid in and the ducking re-derived.
- Also export a **no-music version** (dialogue plus nat). A platform can mute a track over a rights claim, and a studio may want its own licensed music.

### 3.6 Loudness

No social platform publishes a loudness target. YouTube normalises toward about −14 LUFS and turns louder uploads down [60]. AES TD1008 recommends −18 LUFS for speech and −16 LUFS for music in streaming, with true peak no higher than −1 dBTP [61]. For a music-led promo, deliver about −14 LUFS integrated with a true peak of −1 dBTP (practitioner convention; editorial judgement). Measure it with `mixing.loudness` [12].

## 4. Music for yoga and wellness promos

### 4.1 Genres

A stock library's yoga and Pilates theme mixes ambient, meditation, chillout beats, Indian and Hindustani classical (surbahar, sitar), alternative hip hop and even Afrobeats, with moods of dreamy, floating, laid back and peaceful. Listed tempos run from 64 to 146 BPM. The 146 BPM chillout-beats track is most likely felt at half time, about 73 BPM [62]. Other libraries put handpan and ambient pads, often with nature sounds, at the centre of the category [63]. Studio-promo practice adds organic house for vinyasa, power and hot-yoga brands, and acoustic or lo-fi for a casual community feel.

| Genre | Typical tempo | Fits | Notes |
|---|---|---|---|
| Ambient, meditation, handpan | 60–80 BPM or free time | Yin, restorative, meditation studios | Weak beat grid: cut on phrase changes and swells, not on beats. Free-time ambient has no grid at all, so the planner should detect it and fall back to phrase or energy cues |
| Indian classical fusion (sitar, tabla, surbahar) | 70–100 BPM | Traditional or Hatha studios | Tabla gives a clear grid; avoid a vocal raga under speech |
| Lo-fi hip hop | about 70–90 BPM [64] | Casual or community studios, younger audiences | Very regular 4- and 8-bar loops make cutting easy |
| Downtempo, chillout | under 110 BPM [65] | General wellness | |
| Organic house | about 120 BPM, roughly 115–125 [66] | Vinyasa, power, hot yoga, retreats | Clear phrases and builds; the most "promo-like" choice |
| Acoustic (guitar, piano) | 70–100 BPM | Warm, community, retreats | Often has a real ending |

### 4.2 Tempo by class style

ACSM puts yoga and Pilates in its low-impact tempo band below 110–120 BPM, and music under 100 BPM is most often used for slower mind-body classes [67]. A studio-music curator gives class-music tempos by style and by class phase [68]:

| Class type | Class music [68] | Suggested promo tempo (editorial judgement) |
|---|---|---|
| Yin, restorative | 40–62 BPM | 60–80 BPM (or a half-time feel at 120–160) |
| Hatha, gentle | 62–80 BPM | 70–90 BPM |
| Vinyasa, flow | 78–100 BPM | 85–110 BPM |
| Power flow, power yoga | 92–115 BPM | 100–122 BPM |
| Hot yoga | 80–105 BPM | 95–120 BPM |

Within a 60-minute vinyasa class the same source gives an energy curve: opening and breathwork 70–80 BPM, sun salutations 85–95, peak 88–100, floor work 75–85, savasana 50 or below [68]. That curve has the shape of the promo arc in section 2.2, which is one reason the 150 s template follows the class. A promo should sit slightly above the class's own music, because it has to hold attention in a feed. Very slow class music (below about 60 BPM) gives bars of 4 s or more, too long for a feed, so use a half-time feel or a faster track.

### 4.3 Structure of a promo track

The track needs an arc that the edit can follow:

1. Intro (1–2 bars, or none): texture only. The hook is visual and starts at once.
2. Build (1–2 phrases): elements enter, which carries the establish and instructor sections.
3. Swell or drop (one phrase): the peak pose.
4. Breakdown or thinning: the calm section.
5. Resolution: a final hit or a sustained chord that rings for about 2–4 s, under the end card.

To edit a track to length, mark its sections, then remove whole sections or half-choruses at bar lines, checking that no beat doubles or jumps across the join. Do not fade out [7]. Place the musical ending on the final card first and leave room for its natural decay, then fit the rest backwards [8]. A small time-stretch to make the natural ending land on the last frame is acceptable [8].

### 4.4 Syncing cuts in a non-music-video promo

- **Cut on a ranked subset.** AutoMatch found that changes in the music do not necessarily lead to transitions, and that editors pick a context-dependent subset [4]. For a promo, rank cut candidates as section boundary > phrase start (every 4 or 8 bars) > downbeat > beat, and let section energy decide how deep in the ranking a section may go. This is BEAT's energy-adaptive cut bonus, already in the montage research [4].
- **Cut density follows the song's energy.** Editors accelerate cutting toward climaxes and slow it in bridges [1].
- **Anticipate slightly.** Editors often place cuts just before the downbeat [1]. Editorial judgement: one or two frames early (33–67 ms at 30 fps) reads as on the beat. Off-beat cuts are a deliberate effect for surprise or an indie feel, not a default [1].
- **Holds on phrases.** Hold the peak pose and the calm shots across a whole bar or two, and change section on a phrase boundary.
- **A hit for the logo.** The end card or logo appears on the song's last strong downbeat or final hit, not on an arbitrary frame.

### 4.5 Prompting a song generator

The guidance on Suno's meta-tags comes from community guides, not official documentation, and varies by model version. Treat it as a hypothesis to test [69]. The guides agree that `[End]` and `[Outro]` signal the song to stop, that `[End]` is a hard stop while `[Fade Out]` fades, and that `[Big Finish]` may push a climax. They also report that some genres loop forever without resolving; the suggested fixes are adding "end" to the style field, or trimming afterwards [70].

A style prompt that asks for what the editor needs, for an instrumental bed:

```
Style: instrumental organic downtempo, 84 BPM, 4/4, D minor, handpan, soft kick on every beat, shaker, warm pads, airy flute; clear 8-bar phrases; gentle build to one swell; ends on a sustained final chord, no fade out; no vocals
Lyrics field (structure only): [Intro] [Build] [Drop] [Breakdown] [Swell] [Outro] [Big Finish] [End]
```

Generate longer than needed, for example 2–3 minutes for a 60 s cut. Detect beats, downbeats and sections with the montage stack [9], check that the last 3 s are an ending (RMS decays from a final onset rather than a linear fade), and cut whole sections to length. Ask for an instrumental. A vocal masks the soundbites, and in the fleet only some of `arioso`'s backends honour given lyrics anyway [14].

## 5. Disconfirming views and caveats

- **"Cut on the beat" is not the professional norm for calm content.** Even in music videos, only a fifth set shot length to the bar, and co-occurrence of cuts with downbeats and section boundaries was modest (mean scores between about 0.1 and 0.36 on a 0–1 scale, by genre) [1]. Over-synchronised cutting looks like an app template.
- **Some editors deliberately desynchronise.** An imperfectly synchronised soundtrack was kept on one project because it suited the intended mood [1].
- **Authenticity versus polish.** Studio guides and brand guides warn against heavy filters and over-produced looks [44]. Phone footage of a real class is an asset, not a defect to hide.
- **Sound-off design versus sound-on platforms.** See 2.7. The data conflicts by platform.
- **Length data conflicts and is correlational** [37], [49].

## 6. Rules for the planner

Each rule ends with its basis in parentheses: *sourced* (with references), *derived* from sourced numbers, or *editorial judgement*. A rule marked editorial judgement is a default to tune, not a finding.

**Structure**

1. Choose a template by target length: 60 s gives 7 sections (Hook, Establish, Instructor, Flow, Peak, Calm, EndCard); 150 s gives 8 sections (Hook, Arrival, Instructor, WarmUp, Flow, Peak, CoolDown, CommunityCTA). Section budgets as in section 2.2. *(editorial judgement, from [34], [35])*
2. The hook occupies 0–3 s and shows the single highest-scoring moving shot (peak pose or most motion-salient flow), with a text title on screen by 1 s. What the studio offers must be clear by 3 s, and the hook must have landed by 6 s. *(sourced [36])*
3. Snap every section boundary to a phrase boundary (every 4 or 8 bars) or, failing that, to a downbeat. Never place one mid-bar. *(derived [29], [1])*
4. The end card lasts 3–6 s, starts on the song's final strong downbeat or hit, and stays inside the 900×1400 safe area. *(editorial judgement; zone sourced [51])*
5. Fit the music to length by removing whole sections at bar lines, anchoring the ending to the last frame first. Never fade out unless the track has no ending, and then only over the last 0.5–1 s. *(sourced [7], [8])*

**Shot length and cut points**

6. Store shot lengths in bars and convert at the track's tempo. Defaults: Hook ½–1 bar; Establish 1 bar; Instructor 1–2 bars; Flow ½–1 bar (never under 1 beat); Peak 2 bars; Calm 1–2 bars (2 or more in the 150 s cool-down). *(editorial judgement, anchored to [1], [2])*
7. Clamp every shot to between 1.0 s and 8 s, whatever the tempo; at slow tempos, halve the bar multiple rather than exceed 8 s; at fast tempos, double it rather than go under 1.0 s. *(editorial judgement)*
8. Target a mean shot length of 2.5–4 s overall for the 60 s cut and 3–5 s for the 150 s cut. Flag an edit whose mean shot is under 2 s (it reads as a sizzle reel or a HIIT promo) or over 6 s. *(derived [2], [30], [1])*
9. Never exceed 10 *unrelated* cuts (a change of scene, subject or room) in any 30 s window; related cuts (the same subject from a new angle) do not count toward this limit. *(sourced, second-hand: [33], [24], [32])*
10. Rank cut candidates as section boundary (1.0) > phrase start (0.8) > downbeat (0.6) > beat (0.3) > onset (0.1), scaled by section energy. Calm sections may only use phrase starts and downbeats; Flow may use beats. *(derived [4], [1])*
11. Place each cut 1–2 frames before its musical target. *(derived [1]; editorial judgement for the frame count)*
12. Do not cut a movement before it completes. If a pose's completion misses the target by 150 ms or less, slip the clip; if by up to about 25%, speed-ramp it; otherwise choose another cut point. *(derived [39], [4])*

**Shot selection and order**

13. Within each section, order shots wide → medium → close/detail, and reset to wide when the section changes. *(editorial judgement [34])*
14. Consecutive shots of the same subject must differ by a size step or by 30° or more of angle; otherwise insert a detail shot between them. *(sourced [38])*
15. In Flow, prefer matches on action: pair outgoing and incoming clips whose motion direction and phase agree, and keep the main subject in the same third of the frame across the cut. *(sourced [23], [40])*
16. Every 60 s cut includes at least: 1 instructor shot with speech, 1 hands-on adjustment if one exists, 2 detail inserts, 1 face smiling or at rest, and 1 group shot. The 150 s cut includes at least double. *(editorial judgement [34])*

**Sound**

17. Under a soundbite, duck the music until speech is at least 12 LU louder than the music (target 15 LU), computed from measured loudness rather than as a fixed depth. Attack 50 ms, release 400 ms, hold 200 ms. *(sourced [5]; timings [11])*
18. With no one speaking, keep the room-tone and nat bed about 15 LU under the music, so it is present but not noisy. *(derived, by analogy with [5])*
19. Use 1–2 nat pops in 60 s and 3–5 in 150 s. Each is 0.5–3 s of full-level natural sound placed at a phrase boundary or rest, with the music dipped 6–12 dB and ramped over 100–300 ms. *(editorial judgement [19], [20])*
20. Use soundbites of 2–5 s (60 s) or 5–10 s (150 s), at most two in 60 s and three in 150 s, and only clean, self-contained phrases (transcribe and check that the sentence is complete). *(editorial judgement)*
21. Lead into each soundbite with a J-cut of 0.5–1.5 s and leave it with an L-cut of up to one bar. *(sourced [22], [58]; durations editorial judgement)*
22. Mute the audio of any clip played at a speed other than 100%. *(sourced [25])*
23. Prefer instrumental tracks. If the track has vocals, a soundbite may not overlap a sung phrase. *(sourced [57], [29])*
24. Deliver about −14 LUFS integrated with a true peak of −1 dBTP, and export separate `dialogue`, `nat` and `music` stems that sum to the mix, plus a no-music version. Store duck and pop gains as automation, not baked into the stems. *(sourced [61], [60], [6])*

**Picture treatment and delivery**

25. Hard cuts by default. Dissolves of ½–1 beat only in Calm or CoolDown and only at phrase boundaries; at most one dip to white or black, before the end card. *(sourced [26], [42], [41])*
26. Slow motion only on moving subjects (sourced from 120 or 240 fps clips where available), at most about 20% of the runtime, mostly in Peak and Calm. *(editorial judgement [25])*
27. If a loop is wanted, end on a shot whose framing or motion matches the hook's first frame, and make the audio join click-free: the last hit's tail must not run into the first frame's sound. Otherwise end on the end card. Never end on a fade to black. *(sourced [53], [54])*
28. Keep text, faces and logos inside the platform's safe zone (TikTok: 108 px top, 320 px bottom, 60 px left, 120 px right; universal: 900×1400 centred), set through `tituli`'s delivery presets. *(sourced [50], [51], [13])*
29. Text on screen: no more than 10 words per second of display time, and the offer and schedule are in text so the piece works with sound off. *(sourced [36], [46])*
30. Colour: first match clips to each other (white balance and exposure), then apply at most a light warm, low-contrast grade with skin tones protected. *(editorial judgement [43], [44])*

**Music selection and generation**

31. Choose the tempo by studio style, a little above the class's own music: 60–80 BPM for yin and restorative, 70–90 for Hatha, 85–110 for vinyasa, 100–122 for power and hot yoga. *(derived [67], [68], [66])*
32. Reject a track if its beat grid is unstable (downbeat confidence below threshold) *and* it has no detectable phrase or section boundaries. Free-time ambient is allowed only with energy-cue cutting. *(editorial judgement)*
33. When generating, request an instrumental with an explicit BPM, 4/4, 8-bar phrases, one swell and "ends on a sustained final chord, no fade out"; add `[Outro] [Big Finish] [End]` tags; generate at least twice the target length and verify the ending before use. *(sourced, community: [70], [69])*

## Open questions

- **No measured shot-length data for wellness promos.** The cheapest fix: collect 30–50 public yoga-studio promos (vertical, 30–180 s), run shot detection and the montage stack's beat and section analysis on them, and measure ASL per section, cut-to-downbeat co-occurrence and the share of dissolves. That would turn rules 6–11 from editorial judgement into measurement. Analysis of publicly viewable videos is fine; do not redistribute them.
- **Nat-pop duration and music-dip depth** are unsourced. A small A/B listening test with the planner's output would settle them.
- **The Lang et al. (1999) cut counts** for slow, medium and fast pacing were not read in the original; the 10-unrelated-cuts threshold comes second-hand [33].
- **Safe-zone numbers** are community estimates and change with app updates; re-check before relying on exact pixels.
- **Suno tag behaviour** is unverified and model-dependent; test it through `arioso` before encoding it.
- **Sound-on rates** on Reels specifically were not found.

## REFERENCES

[1] [Prétet L, Richard G, Is there a "language of music-video clips"? A qualitative and quantitative study — ISMIR 2021, arXiv:2108.00970](https://arxiv.org/abs/2108.00970)

[2] [Evolution of movies (James Cutting's shot-length estimates) — FlowingData, 2014](https://flowingdata.com/2014/09/22/evolution-of-movies/)

[3] [Cutting JE et al., changes in Hollywood film shot length, motion and luminance — PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC3485803)

[4] [muvid-montage: methods and prior art — in-house, reeleehq/muvid](../../../../muvid/data/skills/muvid-montage/references/methods_and_prior_art.md)

[5] [Torcoli M, Freke-Morin A, Paulus J, Simon C, Shirley B, Preferred levels for background ducking to produce esthetically pleasing audio for TV with clear speech — J Audio Eng Soc 67(12), 2019](https://salford-repository.worktribe.com/output/1371938/background-ducking-to-produce-esthetically-pleasing-audio-for-tv-with-clear-speech)

[6] [Netflix sound mix specifications and best practices — Netflix Partner Help Center](https://backlothelp.netflix.com/hc/en-us/articles/360001794307-Netflix-Sound-Mix-Specifications-Best-Practices-v1-5)

[7] [Timing music for video editing — PremiumBeat](https://www.premiumbeat.com/blog/timing-music-for-video-editing/)

[8] [How to make music fit your video length exactly — Mubert](https://mubert.com/blog/how-to-make-music-fit-your-video-length-exactly)

[9] [muvid-montage: libraries and licences — in-house, reeleehq/muvid](../../../../muvid/data/skills/muvid-montage/references/libraries_and_licences.md)

[10] [muvid-montage: apps, UX patterns and market — in-house, reeleehq/muvid](../../../../muvid/data/skills/muvid-montage/references/apps_and_market.md)

[11] [mixing.audio.audio_ops.duck_audio — in-house, reeleehq/mixing](https://github.com/reeleehq/mixing/blob/main/mixing/audio/audio_ops.py)

[12] [mixing.loudness (EBU R128 / BS.1770 meter) — in-house, reeleehq/mixing](https://github.com/reeleehq/mixing/blob/main/mixing/loudness.py)

[13] [tituli — typesetting for video (captions, end cards, delivery safe zones) — in-house](https://github.com/reeleehq/tituli)

[14] [arioso — AI song generation behind one generate() — in-house](https://github.com/thorwhalen/arioso)

[15] [Sizzle reel — Adobe](https://www.adobe.com/creativecloud/video/discover/sizzle-reel)

[16] [What is a sizzle reel? How to make and score one — Soundstripe](https://www.soundstripe.com/blogs/what-is-a-sizzle-reel)

[17] [NPR training glossary (ambi / nat sound) — NPR](https://npr.org/g-s1-65734)

[18] [The natural approach (natural sound vs. sound effects) — Videomaker](https://www.videomaker.com/article/c4/10785-the-natural-approach/)

[19] [Cataloging natural sound — Video Journalism: Storytelling Techniques (Lynda.com)](https://www.lynda.com/Premiere-Pro-tutorials/Cataloging-natural-sound/120605/134580-4.html)

[20] [Natural sound tells a story faster than words — Poynter](https://www.poynter.org/?p=979830)

[21] [Working with audio tracks in a news sequence (NAT track ducked under VO/SOT) — Avid MediaCentral help](https://help.avid.com/MediaCentral/MediaCentralCloudUX/MCCUX_Help/NUX_UG_Audio.07.11.html)

[22] [Split edit (J cut, L cut) — Wikipedia](https://en.wikipedia.org/wiki/Split_edit)

[23] [Match cut — Wikipedia](https://en.wikipedia.org/wiki/Match_cut)

[24] [Lang A, Bolls P, Potter RF, Kawahara K, The effects of production pacing and arousing content on the information processing of television messages — J Broadcasting & Electronic Media 43(4), 1999](https://doi.org/10.1080/08838159909364504)

[25] [Playing 120 fps footage in a 24 fps timeline (interpret footage for slow motion) — Adobe Community](https://community.adobe.com/questions-729/playing-120fps-footage-in-a-24fps-timeline-1345682)

[26] [Dissolve (filmmaking) — Wikipedia](https://en.wikipedia.org/wiki/Dissolve_(filmmaking))

[27] [Social safe zones (note that no platform publishes them for organic posts) — Tella help](https://www.tella.com/help/editing/social-safe-zones)

[28] [M&E creation guidelines — Netflix Partner Help Center](https://backlothelp.netflix.com/hc/en-us/articles/115006122187-M-E-Creation-Guidelines)

[29] [A guide to editing music into your videos — Artlist](https://artlist.io/blog/how-to-add-music-to-a-video/)

[30] [MacLachlan J, Logan M, Camera shot length in TV commercials and their memorability and persuasiveness — Journal of Advertising Research / WARC](https://www.warc.com/Content/421e1376-baa5-472f-aa9d-adc58bea5146)

[31] [Pérez Rufí JP, Rodríguez López J, Video clip editing and duration of the shot: analysis of "I Took a Pill in Ibiza" — Doxa Comunicación, 2017](https://doaj.org/article/81ae4b0f49464cc59acb7565f5d65055)

[32] [Lang A, Zhou S, Schwartz N, Bolls PD, Potter RF, The effects of edits on arousal, attention, and memory for television messages — 2000](https://scholars.cityu.edu.hk/en/publications/the-effects-of-edits-on-arousal-attention-and-memory-for-televisi/)

[33] [Niederdeppe J, Syntax and the processing of health messages (cites Lang et al. 1999 for the 10-cuts-per-30-s overload threshold) — 2005](https://www.uky.edu/~ngrant/CJT780/readings/Day%2010/Niederdeppe2005.pdf)

[34] [Video content ideas for yoga studios — TeamUp](https://goteamup.com/resources/video-content-ideas-for-yoga-studios)

[35] [5 must-have videos for your fitness business — Mindbody](https://mindbodyonline.com/business/education/blog/5-must-have-videos-for-your-fitness-business)

[36] [Creative best practices for performance ads — TikTok Ads Help Center](https://ads.tiktok.com/help/article/creative-best-practices)

[37] [How long should Instagram Reels be? We analyzed 2.7 million Reels — Buffer](https://buffer.com/resources/instagram-reels-length)

[38] [30-degree rule — Wikipedia](https://en.wikipedia.org/wiki/30-degree_rule)

[39] [Walter Murch's Rule of Six — StudioBinder](https://www.studiobinder.com/blog/walter-murch-rule-of-six/)

[40] [Editing, eye trace and why the Rule of Six may be incorrect for fast-paced video — No Film School, 2018](https://nofilmschool.com/2018/08/editing-eye-trace-mind-rule-six-incorrect)

[41] [Cutting vs. using transitions — Creating a Short Film: Editing (Lynda.com)](https://origin-www.lynda.com/Premiere-Pro-tutorials/Cutting-vs-using-transitions/129026/789204-4.html)

[42] [Video cross dissolve — Adobe](https://www.adobe.com/creativecloud/video/discover/video-cross-dissolve)

[43] [Warm lifestyle video filters (warm white balance, low-contrast pastel, protect skin) — Filmora](https://filmora.wondershare.com/video-creative-tips/warm-lifestyle-video-filters.html)

[44] [Brand kit for a yoga studio (natural light, no heavy filters) — Lovart](https://www.lovart.ai/ru/blog/brand-kit-yoga-studio-lovart)

[45] [Kantar report: how brands are making noise and driving impact with sound on TikTok — TikTok for Business](https://ads.tiktok.com/business/en-US/blog/kantar-report-how-brands-are-making-noise-and-driving-impact-with-sound-on-tiktok)

[46] [Sound-on usage by app (survey) — Voices.com](https://www.voices.com/?p=21943)

[47] [Instagram expands Reels length to 3 minutes — Lindsey Gamble, 2025](https://www.lindseygamble.com/blog/instagram-three-minute-reels)

[48] [YouTube Shorts now up to 3 minutes long — eMarketer, 2024](https://www.emarketer.com/content/youtube-shorts-now---long)

[49] [2026 social media video performance statistics — Socialinsider](https://www.socialinsider.io/blog/short-form-video-statistics/)

[50] [What are the safe zones for TikToks and Instagram Reels? — Ignite Social Media](https://www.ignitesocialmedia.com/content-creation/what-are-the-safe-zones-for-tiktoks-and-instagram-reels/)

[51] [Social media safe zones 2026: complete guide — AdaptlyPost](https://adaptlypost.com/blog/social-media-safe-zones-2026-complete-guide)

[52] [Add end screens to videos (last 5–20 s) — YouTube Help](https://support.google.com/youtube/answer/6388789)

[53] [Does looping video boost views on TikTok and Instagram? — Vimeo](https://vimeo.com/blog/post/does-looping-video-increase-views)

[54] [How to double your YouTube watch time by looping Shorts — vidIQ](https://vidiq.com/blog/post/double-youtube-watch-time-looping-shorts)

[55] [WCAG 2.2 success criterion 1.4.7 Low or No Background Audio — summary](https://www.disabilityworld.org/toolkit/standards/wcag/1-4-7-low-or-no-background-audio/)

[56] [How to balance audio in Premiere Pro — Storyblocks](https://www.storyblocks.com/resources/tutorials/how-to-balance-audio-premiere-pro)

[57] [How to choose music for a voiceover-heavy video — Audio Network](https://blog.audionetwork.com/the-edit/music/how-to-choose-music-for-a-voiceover-heavy-video/)

[58] [A video editor's guide to J-cuts and L-cuts — Soundstripe](https://www.soundstripe.com/blogs/a-video-editors-guide-to-j-cuts-and-l-cuts)

[59] [M&E creation and delivery guidelines for nonfiction — Netflix Partner Help Center](https://backlothelp.netflix.com/hc/en-us/articles/360057558533-M-E-Creation-and-Delivery-Guidelines-for-Nonfiction)

[60] [LUFS targets per platform, 2026 (no published social targets) — Fora Soft](https://www.forasoft.com/learn/audio-for-video/articles-audio/lufs-targets-per-platform-2026)

[61] [AES TD1008 loudness recommendations for streaming, explained — Production Advice](https://productionadvice.co.uk/td1008/)

[62] [Yoga & Pilates music theme — Epidemic Sound](https://www.epidemicsound.com/music/themes/workout-wellness/yoga-pilates/)

[63] [Ambient handpan and yoga ambience royalty-free music — TunePocket](https://www.tunepocket.com/music-for-yoga/)

[64] [Lofi Beats sample pack (75–88 BPM) — Loopmasters](https://www.loopmasters.com/genres/167-Lo-Fi-Hip-Hop/products/18306-Lofi-Beats?bid=14123)

[65] [Downtempo genre overview — Splice](https://splice.com/sounds/genres/downtempo/overview)

[66] [Organic house music: what it is and how to make it — Native Instruments](https://www.native-instruments.com/blogs/blog/organic-house-music)

[67] [Music tempo guidelines for exercise — American College of Sports Medicine (PDF)](https://www.acsm.org/wp-content/uploads/2025/02/Music-Tempo-Guidelines-for-Exercise-PDF.pdf)

[68] [Yoga studio music (BPM by class type) — Activaire Curation Desk](https://activaire.com/blog/yoga-studio-music)

[69] [Suno meta-tags reference — community guide](https://niller2005.github.io/suno/guide/meta-tags.html)

[70] [How do I end the song? — How To Prompt Suno (community guide)](https://howtopromptsuno.com/common-problems/how-do-i-end-the-song)
