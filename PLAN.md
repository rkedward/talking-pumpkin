# Talking Pumpkin: Build Plan (Raspberry Pi 5 edition)

A pumpkin on the porch with an animated jack-o'-lantern face projected onto it. A camera spots
trick-or-treaters, the eyes follow them (and turn toward whoever is talking), the pumpkin greets them,
comments on their costume, tells a costume joke and answers questions, while servo eyebrows move,
fog puffs and lights flash when kids walk up. Everything runs on one Raspberry Pi 5.

## 1. Shopping list (links to buy each part: [PARTS.md](PARTS.md))

| Part | Pick | Notes |
|---|---|---|
| Computer | Raspberry Pi 5, 4 GB or 8 GB | 8 GB gives headroom for speech recognition. |
| Cooling + power | Official Active Cooler, official 27 W USB-C supply | Speech recognition works the CPU hard. |
| Storage | 32 GB+ microSD (A2) | Raspberry Pi OS 64-bit **with desktop**. |
| Camera | Camera Module 3 (or Camera Module 3 **Wide** for a wide porch) | Plus a **Pi 5 camera cable** (the Pi 5 uses the smaller 22-pin connector; 300-500 mm is handy). A USB webcam also works. |
| Projector | Small LED projector, 200+ ANSI lumens, HDMI | Plus a **micro-HDMI to HDMI** cable. |
| Pumpkin | Foam craft pumpkin or a pale real one ("Lumina") | Uncarved; pale surfaces show the face best. |
| Microphone | **reSpeaker XVF3800 4-Mic Array** (Russ ordered the XIAO ESP32S3 version; the older ReSpeaker USB Mic Array v2.0 also works) | Gives clean audio *and* the direction of the voice, so the eyes find the talker. The XIAO version needs its USB firmware loaded once (`flash_xvf3800.sh`). |
| Speaker | USB-powered speaker, or a USB audio adapter + powered speaker | The Pi 5 has no headphone jack. Hide it behind/inside the pumpkin display. |
| Eyebrows (optional) | Adafruit 16-channel PWM/Servo HAT or bonnet (PCA9685) + 2 micro servos (MG90S) | Separate 5 V supply for the servos. Glue foam brows to the servo horns above the projected eyes. |
| Fog (optional) | Fog machine with a wired remote + 3.3 V-triggerable relay module | The relay closes the remote's button contacts. Never switch mains with a bare relay board. |
| Lights (optional) | Relay module or a MOSFET board for a 12 V LED strip | Flashes on arrival, stays on during the visit. |
| Misc | Tripod/clamp for the projector, extension cord, rain cover, a small sign ("This pumpkin talks and uses a camera") | |

### Wiring (optional props)
| Prop | Connects to |
|---|---|
| PCA9685 servo board | I2C: GPIO2 (SDA), GPIO3 (SCL), 3.3 V, GND; servos on channels 0 (left brow) and 1 (right brow); servo power from its own 5 V supply |
| Fog relay | Signal to GPIO17, plus 5 V/3.3 V and GND per the relay board; relay contacts across the fog remote's button |
| Lights relay/MOSFET | Signal to GPIO27, plus power/GND |

## 2. How it works

```
 Pi Camera ─► vision.py   person detection (EfficientDet-Lite0, on the Pi CPU) + tracking
 ReSpeaker ─► doa.py      direction of the voice ──┐
           └► audio.py    voice activity → Whisper (local speech-to-text)
                                                   ▼
                main.py   the brain: idle → greet → listen/answer → goodbye; picks where to look
                   │  └─► brain.py   Claude: looks at a snapshot (costumes, greeting, joke), answers questions
                   ├────► audio.py   Piper neural voice → speaker, loudness → mouth opening
                   ├────► props.py   eyebrow servos, fog relay, lights
                   └────► web.py     pushes eyes/mouth state to the face page
                                           ▼
 Projector ◄── Chromium kiosk: static/  canvas jack-o'-lantern face (gaze, blinking, lip sync, flicker)
 Phone ───────► same page with ?debug: camera view, log, buttons, line up the face
```

- **Detection is local** so the eyes react instantly; whole people are detected, not faces, because
  costumes hide faces.
- **Looking at the talker**: when the mic array hears a voice, its direction is matched to the
  detected person in that direction, and the eyes go to them. A voice from outside the camera's view
  turns the eyes that way anyway.
- **Speech recognition is local** (Whisper base.en on the Pi), so kids' voices never leave the house.
- **Voice**: Piper, a local neural text-to-speech voice, deepened a little. ElevenLabs character
  voices are an option if you want something more theatrical (needs internet and an ElevenLabs key).
- **Lip sync** uses the real loudness of the audio as it plays, so the mouth matches the words.
- **Claude** is called once per visit with a snapshot, then once per question. Only that snapshot
  and the transcribed question leave the Pi. Default model `claude-opus-5-5` at low effort; set
  `claude-haiku-4-5` in config.toml for faster replies.

### Conversation flow
1. **Idle**: eyes half closed and wandering, brows neutral.
2. **Arrival** (someone in view for about a second): lights flash, fog puffs, brows shoot up, eyes
   open wide, and a filler line ("Ooh! Who goes there?") plays while Claude looks at the snapshot.
3. **Greeting**: costume compliment and a costume joke; brows move with each sentence.
4. **Q&A**: listens, answers in a sentence or two, remembers the costumes.
5. **Goodbye** when everyone leaves, or a friendly wrap-up after 5 questions or 90 seconds so the line keeps moving.

### Side show (window projectors)
The Pi 5 has two HDMI outputs. The second drives Russ's window projector behind the frosted front-door
glass. Claude is told which creatures exist (your clips plus built-in ghost, shadow eyes and skeleton
hand); when it decides to summon one, the pumpkin says where to look, its eyes glance at the window, the
creature appears there, and the creature can speak in its own deeper, slower voice. Kids can keep
talking to it while it's visible.
Smart projectors on Wi-Fi (Russ has five Magcubic HY300 Pro+, Android 11) each run a kiosk browser on
`window.html?w=<name>`. Each window has its own name, "where" phrase and eye direction in config.toml;
Claude picks the window, and only windows whose projector has checked in are offered.

## 3. Milestones
1. **Bench test** (any laptop or the Pi): run with a USB webcam and fake replies, check the face, tracking and voice.
2. **Pi build**: run `install_pi.sh`, connect camera, ReSpeaker, speaker and projector, reboot into kiosk mode.
3. **Porch rig**: line the face up with the pumpkin from your phone, point the mic array, set `min_height` so the sidewalk is ignored.
4. **Props**: wire servos, fog relay and lights; test each.
5. **Dress rehearsal** with family members in costumes; tune voice, personality, visit length.
6. **Halloween night**: plug in, check Wi-Fi reaches the porch, keep the phone remote handy.

## 4. Privacy and safety
- No images or audio are stored. Speech is transcribed on the Pi; only a cropped snapshot per visit
  and the text of questions go to the Claude API.
- The pumpkin is told to stay G-rated, never comment on bodies, and never ask for personal information.
- Keep the projector and Pi dry, cables taped down, and the fog machine where kids can't touch the nozzle.
