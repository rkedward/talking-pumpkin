"""The pumpkin's brain (Claude or OpenAI): costume recognition, greeting and Q&A. Holds per-visit
conversation history."""

import json
import os
import random
import re
import threading
import time
import urllib.error
import urllib.request
import uuid

import tunes

SESSION_TTL = 15 * 60
MODEL = "claude-opus-5-5"
EFFORT = "low"
FAKE = False
LAUGH = True             # [claude] laugh: false = no "Ha ha ha!" lines at all
LAUGH_TEXT = "Ha ha ha!" # [claude] laugh_text: how the pumpkin writes its laugh
GAME = True              # [claude] song_game: offer the "guess the song" game
PROVIDER = "claude"      # claude | openai
OPENAI_MODEL = "gpt-5-mini"
OPENAI_REASONING = "minimal"
CREATURES = []          # [{"name": ..., "description": ..., "windows": [...]}] that can appear in a window
WINDOWS = {}            # window name -> where it is, as the pumpkin tells kids ("the front door window behind you")
ONLINE = lambda: list(WINDOWS)   # windows whose projector is switched on right now


def configure(cfg, creatures=(), windows=None, online=None):
    global MODEL, EFFORT, FAKE, CREATURES, WINDOWS, ONLINE, PROVIDER, OPENAI_MODEL, OPENAI_REASONING
    MODEL, EFFORT, FAKE = cfg["model"], cfg["effort"], bool(cfg["fake"])
    PROVIDER = cfg.get("provider", "claude")
    global LAUGH
    LAUGH = bool(cfg.get("laugh", True))
    global LAUGH_TEXT, GAME
    GAME = bool(cfg.get("song_game", True))
    tunes.SOURCE = cfg.get("song_source", "auto")
    LAUGH_TEXT = cfg.get("laugh_text") or LAUGH_TEXT
    OPENAI_MODEL, OPENAI_REASONING = cfg.get("openai_model", OPENAI_MODEL), cfg.get("openai_reasoning", "")
    CREATURES, WINDOWS = list(creatures), dict(windows or {})
    ONLINE = online or (lambda: list(WINDOWS))


def _live():
    """(creatures that can appear right now, windows that are on)."""
    on = [w for w in ONLINE() if w in WINDOWS]
    if not on:
        return [], []
    return [c for c in CREATURES if not c.get("windows") or set(c["windows"]) & set(on)], on


def sideshow_prompt():
    """Extra instructions when window projectors can show creatures."""
    creatures, on = _live()
    if not creatures:
        return ""
    many = len(on) > 1
    names = "\n".join(f"- {c['name']}: {c['description']}"
                      + (f" (only appears in: {', '.join(w for w in c['windows'] if w in on)})" if many and c.get("windows") else "")
                      for c in creatures)
    if many:
        spots = "\n".join(f"- {w}: {WINDOWS[w]}" for w in on)
        where = f"""one of the windows of the house. Windows you can use right now (set "window" to its name):
{spots}
"""
        example = WINDOWS[on[0]]
        extra = """
- Pick the window that fits the moment, and use a different one if kids ask for more."""
        fliers = [c["name"] for c in creatures if c.get("flies")]
        if fliers:
            extra += f"""
- {" and ".join(fliers)} can fly from window to window: while it is visible, set "fly_to" to another window
  and it flies there after saying its "creature_says" line (tell the kids to watch it go, e.g. "Boo, go check
  {WINDOWS[on[-1]]}!"). Great when kids ask for a trick or want to see it fly. Otherwise leave "fly_to" empty."""
    else:
        example = WINDOWS[on[0]]
        where, extra = example + ".", ""
    return f"""

Side show: you have assistants, creatures who live inside the house and help you run your Halloween
porch. You can summon one and it appears in {where}
Treat them as your helpers and sidekicks: call them by name ("Knuckles, come say hi!"), give them little jobs (checking the candy supply, judging
the best costume, telling a joke, doing a silly trick), and banter with them. Your assistants:
{names}
- To summon one, set "summon" to its exact name and, in "say", tell the kids where to look
  (for example "Look at {example}!"). Summon at most once per visit, at a fun moment such as
  after your joke or when kids ask for something spooky. Skip it for very small or nervous kids.
- While an assistant is visible it can speak for itself: put its line in "creature_says" (short, in its own
  character, loyal to you and happy to help; silly and friendly with kids, spookier only with teenagers). Kids may talk to it, and it can answer.
- Leave "summon" and "creature_says" empty when not using them.{extra}"""


def output_schema(with_costumes):
    props = {"say": {"type": "string", "description": "Exactly what the pumpkin says aloud."}}
    required = ["say"]
    if GAME and not with_costumes:
        props["play_song"] = {"type": "string", "enum": [""] + list(tunes.catalog()),
                              "description": "Song to play for the guessing game right after you speak, or empty."}
        required.append("play_song")
    if with_costumes:
        props = {"costumes": {"type": "array", "items": {"type": "string"},
                              "description": "Short description of each costume seen, e.g. 'witch with a green hat'."},
                 "audience": {"type": "string", "enum": ["kids", "teens"],
                              "description": "kids unless the group is clearly all teenagers or adults."},
                 **props}
        required[:0] = ["costumes", "audience"]
    if CREATURES:
        props["summon"] = {"type": "string", "enum": [""] + [c["name"] for c in CREATURES],
                           "description": "Creature to show in the window now, or empty."}
        props["creature_says"] = {"type": "string", "description": "What the visible creature says aloud, or empty."}
        required += ["summon", "creature_says"]
        if len(WINDOWS) > 1:
            props["window"] = {"type": "string", "enum": [""] + list(WINDOWS),
                               "description": "Which window the summoned creature appears in, or empty."}
            required.append("window")
            if any(c.get("flies") for c in CREATURES):
                props["fly_to"] = {"type": "string", "enum": [""] + list(WINDOWS),
                                   "description": "Window the visible flying creature flies to next, or empty."}
                required.append("fly_to")
    return {"type": "object", "properties": props, "required": required, "additionalProperties": False}


PERSONA = """You are Jack, a friendly, theatrical talking jack-o'-lantern on a front porch on Halloween night.
Trick-or-treaters (often young kids, sometimes teens and parents) walk up to you. Everything you write is
spoken aloud by a text-to-speech voice, so:
- Write plain spoken sentences only. No emoji, stage directions, asterisks, lists, or markdown.
- Keep it short: one to three sentences, under about 45 words.
- You are JOLLY: big-hearted, bubbly and silly, and you crack yourself up.{laugh}
- Fun, not scary: with little kids or mixed groups be cozy and goofy. "Spooky" means silly-spooky
  ("ooky spooky", wobbly ghost noises), never frightening, and never mean or sarcastic.
- If the group is clearly all teenagers (no little kids with them), you may be spookier: dramatic,
  campy-creepy horror-movie humor, and your assistants can try to startle them. Still no gore, violence or
  anything mean. When unsure, treat them as little kids. Never say anyone's age out loud.
- Puns and silly pumpkin humor are great. Keep everything G-rated.
- Talk about costumes only, never about anyone's body, face, weight, skin, age guess, or other personal traits.
- Never ask for names, addresses, school, or other personal information. If a kid offers their name, you may use it.
- If you can't tell what a costume is, guess playfully or compliment the colors or details instead.
- What you see comes through your own pumpkin eyes. Never mention a camera, photo, picture, image or screen.
- Stay in character as a pumpkin. If asked if you're real, have fun with it ("as real as a pumpkin can be!").
- If someone asks something unsafe or inappropriate, gently change the subject back to Halloween.
- Candy is in the bowl; you can remind them to take one (or two, if the porch owner allows)."""

LAUGH_ON = """ After a joke or pun, laugh at it
  as its own short sentence written out in words: "{laugh_text}" (always that laugh, never "*laughs*").
  You can chuckle at a funny costume or question too."""
LAUGH_OFF = """ Show it in your words and delight, but never
  write out laughter ("ha ha", "ho ho", "hee hee") or "*laughs*"."""
LAUGH_RE = re.compile(r"^\W*((ha|ho|hee|he|heh|hah|mwa|mwah)\W*)+$", re.I)

_LAUGH_WORD = r"(?:(?:ha|ho|hee|heh|hah)\b[\s,\-]*){2,}|(?:ha(?:ha)+|he(?:he)+|ho(?:ho)+|heehee|mwa(?:ha)+)\b[\s,\-]*"
LEAD_LAUGH = re.compile(r"^(?:" + _LAUGH_WORD + r")+", re.I)
MID_LAUGH = re.compile(r",\s*(?:(?:ha|hee|heh|hah)\b[\s,\-]*)+,\s*", re.I)          # "I mean, ha, I'm ..."
LEAD_ONE_LAUGH = re.compile(r"^(?:(?:ha|hee|heh|hah)\b\s*[,\-]\s*)+", re.I)             # "Ha, nice hat!"
TRAIL_LAUGH = re.compile(r"[\s,\-]+(?:" + _LAUGH_WORD + r")+([.!?]*)$", re.I)


def game_prompt():
    if not GAME:
        return ""
    cat = tunes.catalog()
    kinds = []
    for kind, ids in tunes.kinds().items():
        listed = ", ".join(f"{sid} ({cat[sid]['title']}{', teens only' if cat[sid]['teens'] else ''})" for sid in ids)
        kinds.append(f"- {kind}: {listed}")
    songs = "\n".join(kinds)
    return f"""

Guess-the-song game: you can play a few seconds of a song and the trick-or-treaters guess it.
- In your greeting or early in the chat, you may ask if they want to play a game (not every visit, and not if
  they're in a hurry or shy).
- Pick songs that suit the group: little kids get kids' songs, nursery rhymes, movie and video game songs and
  the friendlier Halloween ones; older kids, teens and grown-ups can get anything. Songs marked "teens only" are never for little
  kids. You can ask which kind they'd like to hear ({", ".join(tunes.kinds())}).
- When they say yes (or ask for a song), say something short like "Listen closely!" in "say" and set
  "play_song" to a song id; the tune plays right after you speak. Never say the title before they guess.
- On their guess: cheer if they're right (close enough counts). If not, give a fun hint (what the song is about,
  or which movie or princess it's from) and let them guess again. After two wrong guesses, tell them the answer kindly.
- After a round, you can offer one more song with a different id. Leave "play_song" empty otherwise.
Songs you can play, by kind:
{songs}"""


def persona():
    laugh = LAUGH_ON.replace("{laugh_text}", LAUGH_TEXT) if LAUGH else LAUGH_OFF
    return PERSONA.replace("{laugh}", laugh) + sideshow_prompt() + game_prompt()


def _no_laughs(text):
    """Drop written-out laughter (a "Ha ha!" sentence) when laughing is switched off."""
    if LAUGH or not text:
        return text
    kept = []
    for part in re.findall(r"[^.!?]+[.!?]*", text):
        part = part.strip()
        if LAUGH_RE.match(part):
            continue
        part = MID_LAUGH.sub(", ", part)
        part = LEAD_ONE_LAUGH.sub("", LEAD_LAUGH.sub("", part))          # "Hee hee, I'm a great host!" -> "I'm a great host!"
        part = TRAIL_LAUGH.sub(r"\1", part)       # "What fun, ha ha!" -> "What fun!"
        if part:
            kept.append(part[0].upper() + part[1:])
    return " ".join(kept) or text


GREET_INSTRUCTIONS = """Trick-or-treaters just walked up. This snapshot is from the camera next to you ({people} {noun} detected).
Identify each visible costume and whether this group is "kids" (any little kids, or you can't tell) or
"teens" (clearly all teenagers or grown-ups), then write what you say out loud: greet them, compliment the
costume(s) specifically, tell one short joke or pun based on a costume, and laugh at your own joke. For a group, mention a couple of costumes
rather than listing everyone. If nobody is visible or the image is unclear, greet them warmly anyway; if you
can't make out a costume, say something like "my eyes are a bit blurry tonight" and ask what they're dressed as."""

FAKE_GREETINGS = [
    ("a mystery costume", "Well hello there, mysterious visitor! What a fang-tastic costume. "
     "Why didn't the skeleton go trick-or-treating? It had no body to go with! Ha ha ha!"),
    ("a witch", "Greetings, young witch! Your hat is spell-binding. "
     "Why do witches fly on brooms? Because vacuum cleaners have cords! Hee hee hee!"),
]
FAKE_ANSWERS = [
    "Ooh, great question! I'd tell you, but my brain is mostly pumpkin seeds. Ha ha ha!",
    "Hmm, let me think about that with my gourd-geous brain. I say yes!",
    "My favorite candy? Anything orange, of course. Take one from the bowl!",
]

FALLBACK_SAY = "Happy Halloween! I love your costume. Grab some candy! Ha ha ha!"

_sessions = {}
_lock = threading.Lock()
_client = None


def client():
    global _client
    if _client is None:
        import anthropic  # imported lazily so fake mode works without the package

        _client = anthropic.Anthropic()
    return _client


_NO_REASONING = set()   # OpenAI models that rejected reasoning_effort


def call_openai(messages, schema=None):
    """One OpenAI Chat Completions request with the same messages (Claude's format is converted)."""
    def convert(content):
        if isinstance(content, str):
            return content
        out = []
        for block in content:
            if block["type"] == "image":
                src = block["source"]
                out.append({"type": "image_url",
                            "image_url": {"url": f"data:{src['media_type']};base64,{src['data']}"}})
            else:
                out.append({"type": "text", "text": block["text"]})
        return out

    body = {"model": OPENAI_MODEL, "max_completion_tokens": 2000,
            "messages": [{"role": "system", "content": persona()}]
                        + [{"role": m["role"], "content": convert(m["content"])} for m in messages]}
    if schema:
        body["response_format"] = {"type": "json_schema",
                                   "json_schema": {"name": "pumpkin_reply", "strict": True, "schema": schema}}
    if OPENAI_REASONING and OPENAI_MODEL not in _NO_REASONING:
        body["reasoning_effort"] = OPENAI_REASONING

    def post(b):
        req = urllib.request.Request("https://api.openai.com/v1/chat/completions", data=json.dumps(b).encode(),
                                     headers={"Authorization": f"Bearer {os.environ.get('OPENAI_API_KEY', '')}",
                                              "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())

    try:
        data = post(body)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        if exc.code == 400 and "reasoning" in detail and "reasoning_effort" in body:
            _NO_REASONING.add(OPENAI_MODEL)          # the chosen model doesn't take this setting; stop sending it
            body.pop("reasoning_effort")
            data = post(body)
        else:
            raise RuntimeError(f"OpenAI {exc.code}: {detail[:300]}") from None
    message = data["choices"][0]["message"]
    if message.get("refusal"):
        return None
    return (message.get("content") or "").strip() or None


def call_claude(messages, schema=None):
    """One brain request. Returns the response's final text (or None on refusal)."""
    if PROVIDER == "openai":
        return call_openai(messages, schema)
    kwargs = {}
    if schema:
        kwargs["output_config"] = {"effort": EFFORT, "format": {"type": "json_schema", "schema": schema}}
    else:
        kwargs["output_config"] = {"effort": EFFORT}
    response = client().beta.messages.create(
        model=MODEL,
        max_tokens=2000,
        system=persona(),
        messages=messages,
        # Server-side fallback: if a safety classifier declines, the API retries on a suitable model.
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        **kwargs,
    )
    if response.stop_reason == "refusal":
        return None
    texts = [b.text for b in response.content if b.type == "text"]
    return texts[-1].strip() if texts else None


def prune_sessions():
    now = time.time()
    with _lock:
        for sid in [s for s, v in _sessions.items() if now - v["touched"] > SESSION_TTL]:
            del _sessions[sid]


def _parse(text):
    try:
        data = json.loads(text) if text else {}
    except json.JSONDecodeError:
        data = {}
    return data if isinstance(data, dict) else {}


def _sideshow_fields(data):
    names = {c["name"] for c in CREATURES}
    summon = data.get("summon") if data.get("summon") in names else ""
    window = data.get("window") if data.get("window") in WINDOWS else ""
    fly_to = data.get("fly_to") if data.get("fly_to") in WINDOWS else ""
    return {"summon": summon, "window": window, "fly_to": fly_to,
            "creature_says": _no_laughs((data.get("creature_says") or "").strip())}


def greet(image_b64, people, note=""):
    sid = uuid.uuid4().hex
    if FAKE:
        costume, say = random.choice(FAKE_GREETINGS)
        data = {"costumes": [costume], "audience": "kids", "say": say}
        creatures, on = _live()
        if creatures:   # exercise the side show in fake mode
            c = random.choice(creatures)
            w = random.choice([x for x in on if not c.get("windows") or x in c["windows"]])
            data.update(say=say + f" Now look at {WINDOWS[w]}!", summon=c["name"], window=w,
                        creature_says="Hee hee, hi everybody! Happy Halloween!")
            others = [x for x in on if x != w]
            if c.get("flies") and others:
                data["fly_to"] = random.choice(others)
    else:
        prompt = GREET_INSTRUCTIONS.format(people=people, noun="person" if people == 1 else "people")
        if note:
            prompt += "\n" + note
        content = []
        if image_b64:
            content.append({"type": "image",
                            "source": {"type": "base64", "media_type": "image/jpeg", "data": image_b64}})
        content.append({"type": "text", "text": prompt})
        data = _parse(call_claude([{"role": "user", "content": content}], schema=output_schema(True)))
    costumes = data.get("costumes") or []
    say = _no_laughs(data.get("say") or FALLBACK_SAY)
    audience = "teens" if data.get("audience") == "teens" else "kids"
    result = {"costumes": costumes, "audience": audience, "say": say, **_sideshow_fields(data)}

    # Keep a text-only history; the image isn't re-sent on every question.
    seen = ", ".join(costumes) if costumes else "costumes you couldn't make out"
    history = [
        {"role": "user", "content": f"(Trick-or-treaters arrived. Costumes you saw: {seen}. "
                                    f"Audience: {'teenagers, so you may be spookier' if audience == 'teens' else 'kids, so keep it fun, not scary'}.)"},
        {"role": "assistant", "content": json.dumps({k: v for k, v in result.items() if k not in ("costumes", "audience")})},
    ]
    with _lock:
        _sessions[sid] = {"history": history, "touched": time.time()}
    return {"session": sid, **result}


def chat(sid, text, on_stage=None):
    """on_stage: name of the creature currently visible in the window, if any."""
    with _lock:
        session = _sessions.get(sid)
    if session is None:
        session = {"history": [{"role": "user", "content": "(A trick-or-treater walked up.)"},
                               {"role": "assistant", "content": json.dumps({"say": "Happy Halloween!"})}],
                   "touched": time.time()}
        with _lock:
            _sessions[sid] = session
    note = f" ({on_stage} is visible right now.)" if on_stage else ""
    history = session["history"] + [{"role": "user", "content": f'The trick-or-treater says: "{text}"{note}'}]
    if FAKE:
        data = {"say": random.choice(FAKE_ANSWERS)}
        if on_stage:
            data["creature_says"] = "Ooooh, I agree with the pumpkin!"
    else:
        data = _parse(call_claude(history, schema=output_schema(False)))
    song = data.get("play_song") if data.get("play_song") in tunes.catalog() else ""
    result = {"play_song": song, "say": _no_laughs(data.get("say")) or "Ooh, let's talk about something else. Like candy! Have you picked one yet?",
              **_sideshow_fields(data)}
    with _lock:
        session["history"] = history + [{"role": "assistant", "content": json.dumps(result)}]
        session["touched"] = time.time()
    return result
