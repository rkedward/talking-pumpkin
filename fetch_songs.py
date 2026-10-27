"""Download short clips of the real songs in tunes.REAL for the guess-the-song game.

Uses Apple's free 30-second song previews (no account needed) and keeps an 8-second piece of each in
sounds/songs/, so nothing is downloaded on Halloween night. Needs ffmpeg (sudo apt install ffmpeg).

    python3 fetch_songs.py          # fetch the songs that aren't there yet
    python3 fetch_songs.py --all    # fetch them all again
    python3 fetch_songs.py let_it_go thriller   # fetch just these again
"""

import json
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request

import tunes

START_S, LENGTH_S = 2.0, 8.0


def find_preview(title, artist):
    query = urllib.parse.urlencode({"term": f"{title} {artist}", "media": "music", "entity": "song",
                                    "limit": 15, "country": "US"})
    with urllib.request.urlopen(f"https://itunes.apple.com/search?{query}", timeout=20) as r:
        results = [x for x in json.loads(r.read()).get("results", []) if x.get("previewUrl")]
    if not results:
        return None
    key = title.lower().split(" (")[0].replace("'", "").replace(",", "")

    bad = ("karaoke", "instrumental", "live", "remix", "cover", "tribute", "version", "made famous", "lullaby",
           "acoustic", "sped up", "slowed")

    def score(x):
        name = x.get("trackName", "").lower().replace("'", "").replace(",", "")
        who = (x.get("artistName", "") + " " + x.get("collectionName", "")).lower()
        clean = not any(b in (name + " " + who) for b in bad)
        return (key in name) * 2 + (artist.lower() in who) * 2 + clean

    best = max(results, key=score)
    return best if score(best) >= 4 else None


def main():
    tunes.CLIPS.mkdir(parents=True, exist_ok=True)
    index_path = tunes.CLIPS / "songs.json"
    try:
        index = json.loads(index_path.read_text())
    except Exception:
        index = {}
    redo = "--all" in sys.argv
    only = [a for a in sys.argv[1:] if not a.startswith("--")]   # song ids to fetch again
    for sid, (title, artist, kind, teens, _who) in tunes.REAL.items():
        out = tunes.CLIPS / f"{sid}.wav"
        if only and sid not in only:
            continue
        if out.exists() and sid in index and not redo and not only:
            print(f"have  {title}")
            continue
        try:
            hit = find_preview(title.split(" (")[0], artist)
            if not hit:
                print(f"MISS  {title} ({artist}): no preview found")
                continue
            with tempfile.NamedTemporaryFile(suffix=".m4a") as tmp:
                with urllib.request.urlopen(hit["previewUrl"], timeout=30) as r:
                    tmp.write(r.read())
                tmp.flush()
                fade = LENGTH_S - 1.0
                subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(START_S), "-t", str(LENGTH_S),
                                "-i", tmp.name, "-ac", "1", "-ar", "24000", "-sample_fmt", "s16",
                                "-af", f"afade=t=in:d=0.3,afade=t=out:st={fade}:d=1,loudnorm=I=-16",
                                str(out)], check=True)
            index[sid] = {"title": title, "kind": kind, "teens": teens,
                          "found": f"{hit.get('trackName')} - {hit.get('artistName')}"}
            print(f"got   {title}  <-  {index[sid]['found']}")
        except Exception as exc:
            print(f"FAIL  {title}: {exc}")
    index = {k: v for k, v in index.items() if k in tunes.REAL}   # forget songs no longer on the list
    index_path.write_text(json.dumps(index, indent=1))
    print(f"{len(index)} song clips in {tunes.CLIPS}")


if __name__ == "__main__":
    main()
