"""Songs for the pumpkin's "guess the song" game: the opening of each melody, played on a music-box sound
made right here (nothing to download, no account, works offline)."""

import numpy as np

RATE = 24000

# id -> (title, notes). Notes are "NAME+OCTAVE:BEATS"; "R" is a rest and "S" a finger snap.
SONGS = {
    # nursery rhymes
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
    # movies
    "star_wars": ("Star Wars (main theme)",
                  "D4:0.33 D4:0.33 D4:0.34 G4:2 D5:2 C5:0.33 B4:0.33 A4:0.34 G5:2 D5:1 "
                  "C5:0.33 B4:0.33 A4:0.34 G5:2 D5:1 C5:0.33 B4:0.33 C5:0.34 A4:2"),
    "harry_potter": ("Hedwig's Theme (Harry Potter)",
                     "B3:1 E4:1.5 G4:0.5 F#4:1 E4:2 B4:1 A4:3 F#4:3 E4:1.5 G4:0.5 F#4:1 D#4:2 F4:1 B3:4"),
    "pink_panther": ("The Pink Panther",
                     "D#4:0.5 E4:1.5 R:1 F#4:0.5 G4:1.5 R:1 D#4:0.5 E4:1 F#4:0.5 G4:1 C5:0.5 B4:1 "
                     "E4:0.5 G4:1 B4:0.5 A#4:3 A4:0.5 G4:0.5 E4:0.5 D4:0.5 E4:2"),
    "jaws": ("Jaws",
             "E3:1 F3:1 R:1.5 E3:1 F3:1 R:1 E3:0.5 F3:0.5 E3:0.5 F3:0.5 E3:0.5 F3:0.5 "
             "E3:0.25 F3:0.25 E3:0.25 F3:0.25 E3:0.25 F3:0.25 E3:0.25 F3:0.25"),
    # video games
    "super_mario": ("Super Mario Bros.",
                    "E5:0.5 E5:0.5 R:0.5 E5:0.5 R:0.5 C5:0.5 E5:1 G5:1 R:1 G4:1 R:1"),
    "tetris": ("Tetris",
               "E5:1 B4:0.5 C5:0.5 D5:1 C5:0.5 B4:0.5 A4:1 A4:0.5 C5:0.5 E5:1 D5:0.5 C5:0.5 "
               "B4:1.5 C5:0.5 D5:1 E5:1 C5:1 A4:1 A4:2"),
    # spooky
    "addams_family": ("The Addams Family",
                      "C4:0.5 D4:0.5 E4:0.5 F4:1 S:0.5 R:0.5 S:0.5 R:0.5 D4:0.5 E4:0.5 F#4:0.5 G4:1 S:0.5 R:0.5 S:0.5 R:0.5 "
                      "D4:0.5 E4:0.5 F#4:0.5 G4:1 R:0.5 D4:0.5 E4:0.5 F#4:0.5 G4:1 R:0.5 "
                      "C4:0.5 D4:0.5 E4:0.5 F4:1 S:0.5 R:0.5 S:0.5"),
    "mountain_king": ("In the Hall of the Mountain King",
                      "B3:0.5 C#4:0.5 D4:0.5 E4:0.5 F#4:0.5 D4:0.5 F#4:1 F4:0.5 C#4:0.5 F4:1 E4:0.5 C4:0.5 E4:1 "
                      "B3:0.5 C#4:0.5 D4:0.5 E4:0.5 F#4:0.5 D4:0.5 F#4:0.5 B4:0.5 A4:0.5 F#4:0.5 D4:0.5 F#4:0.5 A4:2"),
    "funeral_march": ("Funeral March (Chopin)",
                      "A#3:1 A#3:0.75 A#3:0.25 A#3:1 C#4:0.75 C4:0.25 C4:0.75 A#3:0.25 A#3:0.75 A3:0.25 A#3:2"),
    "toccata": ("Toccata and Fugue in D minor (Bach)",
                "A5:0.25 G5:0.25 A5:2 G5:0.25 F5:0.25 E5:0.25 D5:0.25 C#5:1 D5:2 R:1 "
                "A4:0.25 G4:0.25 A4:2 E4:1 F4:1 C#4:1 D4:2"),
    "halloween": ("Halloween (the movie theme)",
                  "C#5:0.5 F#4:0.5 F#4:0.5 C#5:0.5 F#4:0.5 F#4:0.5 C#5:0.5 F#4:0.5 D5:0.5 F#4:0.5 "
                  "C#5:0.5 F#4:0.5 F#4:0.5 C#5:0.5 F#4:0.5 F#4:0.5 C#5:0.5 F#4:0.5 D5:0.5 F#4:0.5"),
}

# Kinds the pumpkin can offer, and who each song suits ("kids" = fine for little kids; "teens" = too scary or
# too grown-up for them).
GENRES = {
    "nursery rhymes": ["twinkle", "mary_lamb", "old_macdonald", "row_boat", "itsy_spider", "happy_birthday",
                       "london_bridge", "wheels_bus", "baa_baa"],
    "movie songs": ["star_wars", "harry_potter", "pink_panther", "jaws"],
    "video game songs": ["super_mario", "tetris"],
    "spooky songs": ["addams_family", "mountain_king", "funeral_march", "toccata", "halloween"],
}
TEENS_ONLY = {"jaws", "toccata", "halloween"}

_STEPS = {"C": -9, "D": -7, "E": -5, "F": -4, "G": -2, "A": 0, "B": 2}


def _freq(name):
    step = _STEPS[name[0]] + (1 if "#" in name else -1 if len(name) > 2 and name[1] == "b" else 0)
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
        if name == "S":   # finger snap: a short burst of noise
            snap = np.random.default_rng(len(parts)).uniform(-1, 1, n) * np.exp(-t * 90) * 0.9
            parts.append(snap)
            continue
        f = _freq(name)
        tone = np.sin(2 * np.pi * f * t) + 0.35 * np.sin(4 * np.pi * f * t) + 0.12 * np.sin(6 * np.pi * f * t)
        envelope = np.minimum(1.0, t / 0.008) * np.exp(-t * 3.2)
        envelope[-int(RATE * 0.02):] *= np.linspace(1, 0, int(RATE * 0.02))   # no click between notes
        parts.append(tone * envelope)
    audio = np.concatenate(parts)
    audio *= 0.55 * 32767 / max(np.abs(audio).max(), 1e-9)
    return audio.astype(np.int16), RATE
