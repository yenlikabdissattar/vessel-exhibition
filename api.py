"""
VESSEL API — production version (no Blender)
POST /generate  {"traits": "anxious serene"}  → returns pot_params for Three.js
POST /scan      {"image": "<base64 jpeg>"}    → Claude vision → returns pot_params
POST /photobooth {"composite": "<base64 jpg>"} → saves composite, returns URL for QR
GET  /renders/<filename>                       → serves saved composites
GET  /health                                   → {"ok": true}
GET  /                                         → serves index.html
"""
from __future__ import annotations

import base64
import colorsys
import json
import os
import re
import time
from pathlib import Path

from flask import Flask, request, jsonify, send_from_directory, send_file

_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    for _line in _env_path.read_text().splitlines():
        if "=" in _line and not _line.startswith("#"):
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

HERE = Path(__file__).parent
RENDERS_DIR = HERE / "renders"
RENDERS_DIR.mkdir(exist_ok=True)

app = Flask(__name__)


@app.after_request
def add_cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response


# ── Trait database ─────────────────────────────────────────────────────────────
TRAIT_DB: dict[str, tuple] = {
    "anxious":     ("hourglass",   (0.84, 0.18, 0.12), (0.28, 0.72, 0.42), 0.80, 8),
    "serene":      ("wide_squat",  (0.10, 0.38, 0.78), (0.92, 0.94, 0.98), 0.72, 8),
    "chaotic":     ("irregular",   (0.96, 0.22, 0.04), (0.98, 0.94, 0.06), 0.85, 10),
    "nostalgic":   ("urn",         (0.72, 0.30, 0.12), (0.96, 0.84, 0.52), 0.82, 7),
    "melancholic": ("pedestal",    (0.18, 0.14, 0.48), (0.72, 0.62, 0.92), 0.75, 6),
    "playful":     ("balloon",     (0.98, 0.68, 0.06), (0.94, 0.22, 0.58), 0.78, 10),
    "mysterious":  ("pedestal",    (0.08, 0.04, 0.18), (0.62, 0.16, 0.94), 0.70, 6),
    "ethereal":    ("tall_slim",   (0.78, 0.86, 0.98), (0.94, 0.96, 1.00), 0.55, 8),
    "grumpy":      ("wide_squat",  (0.22, 0.28, 0.14), (0.58, 0.72, 0.32), 0.88, 6),
    "jealous":     ("hourglass",   (0.06, 0.52, 0.24), (0.94, 0.92, 0.08), 0.80, 7),
    "curious":     ("balloon",     (0.94, 0.62, 0.08), (0.18, 0.52, 0.94), 0.76, 9),
    "confident":   ("cylindrical", (0.06, 0.08, 0.72), (0.98, 0.78, 0.06), 0.72, 8),
    "gentle":      ("wide_squat",  (0.96, 0.72, 0.78), (0.98, 0.94, 0.84), 0.68, 8),
    "intense":     ("hourglass",   (0.76, 0.04, 0.04), (0.98, 0.92, 0.88), 0.78, 7),
    "warm":        ("urn",         (0.94, 0.42, 0.08), (0.98, 0.86, 0.22), 0.80, 8),
    "cold":        ("pedestal",    (0.22, 0.48, 0.82), (0.86, 0.94, 0.98), 0.70, 6),
    "sad":         ("narrow",      (0.38, 0.44, 0.62), (0.78, 0.82, 0.94), 0.78, 6),
    "happy":       ("balloon",     (0.98, 0.88, 0.06), (0.96, 0.42, 0.18), 0.76, 10),
    "angry":       ("hourglass",   (0.88, 0.04, 0.04), (0.98, 0.88, 0.06), 0.84, 8),
    "bubbly":      ("balloon",     (0.96, 0.58, 0.82), (0.98, 0.94, 0.42), 0.78, 10),
    "dreamy":      ("urn",         (0.72, 0.58, 0.94), (0.94, 0.88, 0.98), 0.65, 9),
    "wild":        ("irregular",   (0.28, 0.72, 0.08), (0.96, 0.78, 0.06), 0.86, 10),
    "elegant":     ("pedestal",    (0.08, 0.08, 0.08), (0.94, 0.90, 0.82), 0.60, 7),
    "dark":        ("pedestal",    (0.06, 0.04, 0.10), (0.52, 0.12, 0.86), 0.65, 6),
    "bright":      ("balloon",     (0.98, 0.96, 0.08), (0.96, 0.38, 0.06), 0.80, 10),
    "nervous":     ("hourglass",   (0.62, 0.48, 0.36), (0.42, 0.74, 0.52), 0.82, 7),
    "peaceful":    ("wide_squat",  (0.42, 0.74, 0.58), (0.94, 0.98, 0.92), 0.70, 8),
    "romantic":    ("urn",         (0.92, 0.28, 0.48), (0.98, 0.88, 0.92), 0.72, 9),
    "bold":        ("hourglass",   (0.06, 0.06, 0.62), (0.96, 0.82, 0.06), 0.78, 8),
    "tender":      ("wide_squat",  (0.96, 0.78, 0.84), (0.98, 0.94, 0.92), 0.68, 8),
    "frantic":     ("irregular",   (0.92, 0.26, 0.04), (0.96, 0.82, 0.06), 0.88, 10),
    "stoic":       ("cylindrical", (0.28, 0.28, 0.30), (0.68, 0.72, 0.66), 0.82, 6),
    "whimsical":   ("balloon",     (0.82, 0.48, 0.96), (0.98, 0.92, 0.42), 0.76, 10),
}

DEFAULT = ("urn", (0.68, 0.28, 0.12), (0.94, 0.82, 0.42), 0.78, 8)

TRAIT_SPECIES: dict[str, list] = {
    "anxious":     ["cosmos",    "tulip",    "lavender",      "poppy"],
    "serene":      ["daisy",     "lotus",    "lily",          "orchid"],
    "chaotic":     ["sunflower", "carnation","iris",          "chrysanthemum"],
    "nostalgic":   ["daisy",     "rose",     "lavender",      "peony"],
    "melancholic": ["cosmos",    "orchid",   "iris",          "lavender"],
    "playful":     ["daffodil",  "peony",    "wildflower",    "cosmos"],
    "mysterious":  ["cosmos",    "orchid",   "iris",          "lotus"],
    "ethereal":    ["daisy",     "lily",     "lavender",      "orchid"],
    "grumpy":      ["wildflower","carnation","iris",          "chrysanthemum"],
    "jealous":     ["cosmos",    "tulip",    "iris",          "poppy"],
    "curious":     ["sunflower", "peony",    "orchid",        "daffodil"],
    "confident":   ["sunflower", "tulip",    "iris",          "lily"],
    "gentle":      ["daisy",     "peony",    "lavender",      "rose"],
    "intense":     ["sunflower", "rose",     "iris",          "poppy"],
    "warm":        ["sunflower", "carnation","daffodil",      "rose"],
    "cold":        ["cosmos",    "tulip",    "iris",          "lotus"],
    "sad":         ["wildflower","orchid",   "lavender",      "tulip"],
    "happy":       ["daisy",     "daffodil", "sunflower",     "peony"],
    "angry":       ["wildflower","rose",     "iris",          "poppy"],
    "bubbly":      ["daffodil",  "peony",    "cosmos",        "daisy"],
    "dreamy":      ["cosmos",    "peony",    "lavender",      "lotus"],
    "wild":        ["sunflower", "chrysanthemum","wildflower","poppy"],
    "elegant":     ["cosmos",    "orchid",   "lily",          "carnation"],
    "dark":        ["wildflower","orchid",   "iris",          "lotus"],
    "bright":      ["sunflower", "daffodil", "cosmos",        "daisy"],
    "nervous":     ["cosmos",    "tulip",    "lavender",      "wildflower"],
    "peaceful":    ["daisy",     "lotus",    "lavender",      "lily"],
    "romantic":    ["daisy",     "peony",    "rose",          "carnation"],
    "bold":        ["sunflower", "iris",     "lily",          "chrysanthemum"],
    "tender":      ["daisy",     "carnation","lavender",      "rose"],
    "frantic":     ["sunflower", "chrysanthemum","wildflower","cosmos"],
    "stoic":       ["cosmos",    "lotus",    "iris",          "lily"],
    "whimsical":   ["daffodil",  "peony",    "cosmos",        "wildflower"],
}

SHAPE_TO_THREE = {
    "cylindrical": "uniformCylinder",
    "tall_slim":   "narrowCylinder",
    "wide_squat":  "bulbous",
    "tapered":     "amphora",
    "balloon":     "bulbous",
    "narrow":      "pinnedNeck",
    "irregular":   "flaringRim",
    "hourglass":   "flaringRim",
    "pedestal":    "pinnedNeck",
    "urn":         "amphora",
}


def resolve(traits: list[str]) -> tuple:
    norm = [t.lower().strip() for t in traits]
    shape, pot_c, flower_c, rough, n_plants = DEFAULT

    for t in norm:
        if t in TRAIT_DB:
            shape, pot_c, flower_c, rough, n_plants = TRAIT_DB[t]
            break

    for t in norm[1:]:
        if t in TRAIT_DB:
            _, pc2, fc2, *_ = TRAIT_DB[t]
            pot_c    = tuple((a + b) / 2 for a, b in zip(pot_c, pc2))
            flower_c = tuple((a + b) / 2 for a, b in zip(flower_c, fc2))
            break

    species = []
    for t in norm:
        if t in TRAIT_SPECIES:
            species = TRAIT_SPECIES[t][:]
            break
    if not species:
        species = ["daisy", "wildflower", "tulip"]
    for t in norm[1:]:
        if t in TRAIT_SPECIES:
            for s in TRAIT_SPECIES[t]:
                if s not in species:
                    species.append(s)
            break

    return shape, tuple(pot_c), tuple(flower_c), rough, n_plants, species


_ALL_SPECIES = {
    "sunflower","rose","daisy","wildflower","tulip","poppy","grass",
    "orchid","peony","iris","lily","lavender","lotus",
    "chrysanthemum","carnation","daffodil","cosmos",
}


def build_three_params(traits, shape, pot_c, flower_c, rough, n_plants, species):
    flower_types = [s for s in species if s in _ALL_SPECIES]
    if not flower_types:
        flower_types = ["daisy"]
    return {
        "colorRGB":       list(pot_c),
        "flowerColorRGB": list(flower_c),
        "silhouette":     SHAPE_TO_THREE.get(shape, "amphora"),
        "roughness":      rough,
        "flowerTypes":    flower_types[:4],
        "flowerCount":    n_plants,
    }


def hex_to_rgb01(h: str) -> tuple:
    h = h.lstrip("#")
    if len(h) < 6:
        return (0.5, 0.5, 0.5)
    return tuple(int(h[i:i+2], 16) / 255 for i in (0, 2, 4))


def _complementary(r: float, g: float, b: float, hue_offset: float = 0.5) -> tuple:
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    h = (h + hue_offset) % 1.0
    s = max(0.55, min(1.0, s * 1.15))
    v = max(0.55, min(1.0, v * 1.10))
    return colorsys.hsv_to_rgb(h, s, v)


def _blend_scan_colours(scan_colors: list, pot_c: tuple, flower_c: tuple) -> tuple[tuple, tuple]:
    _rgb = [hex_to_rgb01(h) for h in scan_colors if h]
    if not _rgb:
        return pot_c, flower_c
    pot_c = _rgb[0]
    if len(_rgb) >= 2:
        hair = _rgb[1]
        contrast = sum(abs(hair[i] - pot_c[i]) for i in range(3))
        flower_c = hair if contrast >= 0.35 else _complementary(*pot_c)
    else:
        flower_c = _complementary(*pot_c)
    if sum(abs(flower_c[i] - pot_c[i]) for i in range(3)) < 0.35:
        flower_c = _complementary(*pot_c, hue_offset=0.33)
    return pot_c, flower_c


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_file(str(HERE / "index.html"))


@app.route("/health")
def health():
    return jsonify({"ok": True})


@app.route("/generate", methods=["POST", "OPTIONS"])
def generate():
    if request.method == "OPTIONS":
        return "", 204

    data   = request.get_json(force=True, silent=True) or {}
    raw    = data.get("traits", "")
    traits = [t.strip() for t in re.split(r"[,\s]+", raw) if t.strip()]

    if not traits:
        return jsonify({"ok": False, "error": "No traits provided"}), 400

    shape, pot_c, flower_c, rough, n_plants, species = resolve(traits)
    pot_params = build_three_params(traits, shape, pot_c, flower_c, rough, n_plants, species)
    return jsonify({"ok": True, "traits": traits, "pot_params": pot_params})


@app.route("/scan", methods=["POST", "OPTIONS"])
def scan():
    if request.method == "OPTIONS":
        return "", 204

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return jsonify({"ok": False, "error": "ANTHROPIC_API_KEY not set"}), 500

    data  = request.get_json(force=True, silent=True) or {}
    image = data.get("image", "")
    if not image:
        return jsonify({"ok": False, "error": "No image provided"}), 400
    if "," in image:
        image = image.split(",", 1)[1]

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=120,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image}},
                {"type": "text", "text": (
                    "Look at this person carefully and be precise. "
                    "1. Choose EXACTLY 2 personality traits for THIS specific person based on their "
                    "face expression, eyes, jaw tension, posture and overall energy. "
                    "Single lowercase words only from: anxious, serene, chaotic, nostalgic, melancholic, "
                    "playful, mysterious, ethereal, grumpy, curious, confident, gentle, intense, warm, "
                    "cold, dreamy, wild, elegant, dark, bold, romantic, peaceful, whimsical, happy, sad, "
                    "angry, bubbly, stoic, frantic, tender, nervous. "
                    "2. Extract EXACTLY 4 hex colors by literally reading visible pixels — do not invent: "
                    "color 0 = dominant fabric color of their TOP clothing, "
                    "color 1 = their HAIR color, "
                    "color 2 = a second clothing color or accessory, "
                    "color 3 = any other notable color in frame. "
                    'Return ONLY valid JSON: {"traits": ["word1", "word2"], "colors": ["#rrggbb", "#rrggbb", "#rrggbb", "#rrggbb"]}'
                )},
            ]}],
        )
        raw_text = re.sub(r"^```json\s*", "", message.content[0].text.strip())
        raw_text = re.sub(r"```\s*$", "", raw_text)
        parsed      = json.loads(raw_text)
        traits      = [t.strip().lower() for t in parsed.get("traits", []) if t.strip()][:2] or ["serene"]
        scan_colors = parsed.get("colors", [])[:4]
    except Exception as e:
        return jsonify({"ok": False, "error": f"Vision analysis failed: {e}"}), 500

    shape, pot_c, flower_c, rough, n_plants, species = resolve(traits)
    if scan_colors:
        pot_c, flower_c = _blend_scan_colours(scan_colors, pot_c, flower_c)
    pot_params = build_three_params(traits, shape, pot_c, flower_c, rough, n_plants, species)
    return jsonify({"ok": True, "traits": traits, "colors": scan_colors, "pot_params": pot_params})


@app.route("/analyse", methods=["POST", "OPTIONS"])
def analyse():
    if request.method == "OPTIONS":
        return "", 204
    data  = request.get_json(force=True, silent=True) or {}
    image = data.get("image", "")
    if image.startswith("data:"):
        image = image.split(",", 1)[-1]
    if not image:
        return jsonify({"ok": False})
    try:
        import anthropic as _ant
        _client = _ant.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
        msg = _client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=220,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image}},
                {"type": "text", "text": (
                    "Look at this person. Choose EXACTLY 2 personality traits (single lowercase words) from: "
                    "anxious serene chaotic nostalgic melancholic playful mysterious ethereal "
                    "grumpy curious confident gentle intense warm cold dreamy wild elegant dark bold romantic. "
                    "Extract EXACTLY 4 hex colors: color0=dominant clothing, color1=hair, "
                    "color2=secondary clothing/accessory, color3=skin tone. "
                    'Return ONLY JSON: {"traits":["w1","w2"],"colors":["#rrggbb","#rrggbb","#rrggbb","#rrggbb"]}'
                )},
            ]}],
        )
        raw = re.sub(r"^```json\s*", "", msg.content[0].text.strip())
        raw = re.sub(r"```\s*$", "", raw)
        parsed      = json.loads(raw)
        traits      = [t.strip().lower() for t in parsed.get("traits", []) if t.strip()][:2] or ["serene"]
        scan_colors = parsed.get("colors", [])[:4]
    except Exception as e:
        print(f"[analyse] error: {e}")
        return jsonify({"ok": False})

    shape, pot_c, flower_c, rough, n_plants, species = resolve(traits)
    if scan_colors:
        pot_c, flower_c = _blend_scan_colours(scan_colors, pot_c, flower_c)
    pot_params = build_three_params(traits, shape, pot_c, flower_c, rough, n_plants, species)
    return jsonify({"ok": True, "pot_params": pot_params, "traits": traits, "colors": scan_colors})


@app.route("/photobooth", methods=["POST", "OPTIONS"])
def photobooth():
    if request.method == "OPTIONS":
        return "", 204

    data    = request.get_json(force=True, silent=True) or {}
    img_b64 = data.get("composite", "")
    if not img_b64:
        return jsonify({"ok": False, "error": "No image provided"}), 400
    if "," in img_b64:
        img_b64 = img_b64.split(",", 1)[1]

    filename  = f"photobooth_{int(time.time())}.jpg"
    save_path = RENDERS_DIR / filename
    try:
        save_path.write_bytes(base64.b64decode(img_b64))
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

    render_url = f"{request.host_url}renders/{filename}"
    return jsonify({"ok": True, "filename": filename, "render_url": render_url})


@app.route("/renders/<path:filename>")
def serve_render(filename):
    return send_from_directory(str(RENDERS_DIR), filename)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    print(f"  VESSEL API  →  http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)
