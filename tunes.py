"""Kids' songs for the pumpkin's "guess the song" game: the opening of each melody, played on a music-box
sound made right here (traditional public-domain tunes, nothing to download)."""

import numpy as np

RATE = 24000

# id -> (title, notes). Notes are "NAME+OCTAVE:BEATS"; "R" is a rest.
SONGS = {
    "twinkle": ("Twinkle, Twinkle, Little Star",
                "C4:1 C4:1 G4:1 G4:1 A4:1 A4:1 G4:2 F4:1 F4:1 E4:1 E4:1 D4:1 D4:1 C4:2"),
    "mary_lamb": ("Mary Had a Little Lamb",
                  "E4:1 D4:1 C4:1 D4:1 E4:1 E4:1 E4:2 D4:1 D4:1 D4:2 E4:1 G4:1 G4:2"),
    "old_macdonald": ("Old MacDonald Had a Farm",
                      "G4:1 G4:1 G4:1 D4:1 E4:1 E4:1 D4:2 B4:1 B4:1 A4:1 A4:1 G4:3"),
    "row_boat": ("Row, Row, Row Your Boat",
                 "C4:1.5 C4:1.5 C4:1 D4:0.5 E4:1.5 E4:1 D4:0.5 E4:1 F4:0.5 G4:3"),
    "itsy_spider": ("The Itsy Bitsy Spider",
                    "G4:0.5 C5:1 C5:0.5 C5:1 D5:0.5 E5:1.5 E5:1 D5:0.5 C5:1 D5:0.5 E5:1 C5:2"),
    "happy_birthday": ("Happy Birthday",
                       "G4:0.75 G4:0.25 A4:1 G4:1 C5:1 B4:2 G4:0.75 G4:0.25 A4:1 G4:1 D5:1 C5:2"),
    "london_bridge": ("London Bridge Is Falling Down",
                      "G4:1.5 A4:0.5 G4:1 F4:1 E4:1 F4:1 G4:2 D4:1 E4:1 F4:2 E4:1 F4:1 G4:2"),
    "wheels_bus": ("The Wheels on the Bus",
                   "C4:1 F4:1 F4:0.5 F4:0.5 F4:1 A4:1 C5:1 A4:1 F4:2 G4:1 E4:1 C4:2 C5:1 A4:1 F4:2"),
    "baa_baa": ("Baa, Baa, Black Sheep",
                "C4:1 C4:1 G4:1 G4:1 A4:0.5 B4:0.5 C5:0.5 A4:0.5 G4:2 F4:1 F4:1 E4:1 E4:1 D4:1 D4:1 C4:2"),
}

_STEPS = {"C": -9, "D": -7, "E": -5, "F": -4, "G": -2, "A": 0, "B": 2}


def _freq(name):
    step = _STEPS[name[0]] + (1 if "#" in name else -1 if name[1] == "b" else 0)
    octave = int(name[-1])
    return 440.0 * 2 ** ((step + 12 * (octave - 4)) / 12)


def synth(song_id, beat_s=0.42):
    """The song's opening as 16-bit mono audio at RATE."""
    _, notes = SONGS[song_id]
    parts = []
    for token in notes.split():
        name, beats = token.split(":")
        n = int(RATE * float(beats) * beat_s)
        t = np.arange(n) / RATE
        if name == "R":
            parts.append(np.zeros(n))
            continue
        f = _freq(name)
        tone = np.sin(2 * np.pi * f * t) + 0.35 * np.sin(4 * np.pi * f * t) + 0.12 * np.sin(6 * np.pi * f * t)
        envelope = np.minimum(1.0, t / 0.008) * np.exp(-t * 3.2)
        envelope[-int(RATE * 0.02):] *= np.linspace(1, 0, int(RATE * 0.02))   # no click between notes
        parts.append(tone * envelope)
    audio = np.concatenate(parts)
    audio *= 0.55 * 32767 / max(np.abs(audio).max(), 1e-9)
    return audio.astype(np.int16), RATE
