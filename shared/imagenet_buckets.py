"""Map a vision label to one of a few demo "superclasses" -> an RGB LED color.

Used by `reflex`: MobileNetV2 gives a fine-grained ImageNet top-1 (e.g. "Labrador
retriever", "espresso", "minivan"); the audience-facing demo collapses that to a
handful of buckets and lights the status LED a matching color.

Why not raw WordNet (per docs/demos-plan.md): the ImageNet hierarchy is heavily
unbalanced (the dog subtree is ~25x the cat subtree) and would need calibration.
Curated mappings (Tsipras et al. NeurIPS 2020 11 superclasses; MadryLab
`robustness` mixed_10) are the recommended source. Those map by WordNet synset id,
which we don't have offline here, so we bake an equivalent table by KEYWORD over
the readable label string. This is a static label->bucket->color lookup decided at
import time (no runtime hierarchy logic), and because it works on the label TEXT it
behaves identically in --mock (synthetic labels) and on the board (info.json
labels). The buckets are tuned for the things you actually hold up to a camera at
a tech talk: food, animals, devices, vehicles, clothing, containers.

The RGB status LED is on/off per channel (7 colors + off), so every bucket color
below is a pure primary/secondary that survives the on/off quantization in
`shared/leds.py`.
"""

# bucket -> (LED color, keyword list). First bucket whose keyword is a substring
# of the (lower-cased) label wins; order matters, so the more specific buckets
# (devices, vehicles) come before the broad "animal" net. Keywords are matched as
# plain substrings of the full label, so "retriever" catches "Labrador retriever".
_BUCKETS = [
    ("vehicle", "#ff0000", [  # red
        "car", "truck", "jeep", "van", "minivan", "bus", "trailer", "tractor",
        "motor", "moped", "scooter", "bicycle", "bike", "tricycle", "unicycle",
        "boat", "ship", "canoe", "yawl", "catamaran", "speedboat", "submarine",
        "airliner", "airship", "warplane", "aircraft", "wing", "balloon",
        "locomotive", "freight car", "passenger car", "streetcar", "snowplow",
        "forklift", "garbage truck", "tow truck", "fire engine", "police van",
        "ambulance", "cab", "convertible", "limousine", "sports car", "go-kart",
    ]),
    ("device", "#ffffff", [  # white
        "keyboard", "mouse", "computer", "laptop", "notebook", "desktop", "screen",
        "monitor", "printer", "scanner", "modem", "router", "hard disc", "ipod",
        "cellular", "cellphone", "telephone", "phone", "dial", "remote", "camera",
        "lens", "projector", "television", "loudspeaker", "microphone", "radio",
        "tape player", "cassette", "cd player", "oscilloscope", "joystick",
        "game", "console", "calculator", "digital", "electric", "switch", "watch",
        "clock", "fan", "vacuum", "toaster", "microwave", "refrigerator",
        "washer", "dishwasher", "espresso maker", "waffle iron", "hair dryer",
    ]),
    ("clothing", "#ff00ff", [  # magenta
        "shirt", "jersey", "sweatshirt", "sweater", "cardigan", "jean", "trouser",
        "pajama", "kimono", "poncho", "cloak", "gown", "suit", "vestment",
        "abaya", "jacket", "coat", "fur coat", "lab coat", "bib", "apron",
        "hat", "cap", "bonnet", "sombrero", "helmet", "hood", "mask", "shoe",
        "sandal", "clog", "boot", "loafer", "sneaker", "running shoe", "sock",
        "mitten", "glove", "scarf", "tie", "bow tie", "necklace", "ring",
        "sunglass", "glasses", "swimming trunks", "bikini", "diaper", "wig",
    ]),
    ("food", "#00ff00", [  # green
        "banana", "apple", "orange", "lemon", "lime", "fig", "pineapple",
        "strawberry", "pomegranate", "jackfruit", "custard apple", "fruit",
        "corn", "cucumber", "broccoli", "cauliflower", "cabbage", "artichoke",
        "pepper", "mushroom", "pizza", "burrito", "hotdog", "hamburger",
        "cheeseburger", "bagel", "pretzel", "bread", "loaf", "dough", "meatloaf",
        "guacamole", "mashed potato", "carbonara", "ice cream", "ice lolly",
        "trifle", "chocolate", "espresso", "cup", "coffee", "mug", "eggnog",
        "red wine", "beer", "plate", "bowl", "soup", "consomme", "potpie",
        "bottle", "water jug", "pitcher", "wine bottle", "pop bottle",
    ]),
    ("animal", "#0000ff", [  # blue
        "dog", "puppy", "retriever", "terrier", "spaniel", "hound", "poodle",
        "setter", "shepherd", "collie", "corgi", "bulldog", "boxer", "mastiff",
        "husky", "malamute", "pinscher", "schnauzer", "chihuahua", "pug",
        "cat", "tabby", "siamese", "persian", "lynx", "cougar", "leopard",
        "lion", "tiger", "cheetah", "jaguar", "bird", "cock", "hen", "ostrich",
        "finch", "jay", "magpie", "chickadee", "owl", "eagle", "vulture",
        "parrot", "macaw", "cockatoo", "lorikeet", "hummingbird", "toucan",
        "duck", "goose", "swan", "flamingo", "pelican", "penguin", "fish",
        "shark", "ray", "eel", "snake", "serpent", "cobra", "viper", "lizard",
        "iguana", "gecko", "chameleon", "turtle", "tortoise", "frog", "toad",
        "salamander", "newt", "crocodile", "alligator", "bear", "panda", "fox",
        "wolf", "coyote", "monkey", "ape", "gorilla", "chimpanzee", "orangutan",
        "baboon", "macaque", "lemur", "elephant", "zebra", "horse", "pony",
        "ox", "bison", "buffalo", "antelope", "gazelle", "impala", "ram",
        "sheep", "goat", "pig", "hog", "boar", "rabbit", "hare", "hamster",
        "squirrel", "beaver", "otter", "skunk", "badger", "weasel", "mongoose",
        "spider", "scorpion", "tick", "centipede", "beetle", "butterfly",
        "moth", "bee", "ant", "fly", "dragonfly", "grasshopper", "cricket",
        "mantis", "cockroach", "snail", "slug", "crab", "lobster", "crayfish",
        "jellyfish", "starfish", "urchin", "coral", "whale", "dolphin",
        "seal", "sea lion", "dugong",
    ]),
]

# Anything that matches no bucket above (furniture, structures, tools, containers,
# instruments, abstract textures...). Cyan keeps it visually distinct from the five.
_OTHER = ("other", "#00ffff")  # cyan

# Public: bucket order (for legends / web swatches) with colors.
BUCKETS = [(name, color) for name, color, _kw in _BUCKETS] + [_OTHER]
BUCKET_COLOR = {name: color for name, color in BUCKETS}


def bucket_for_label(label: str):
    """Return (bucket_name, hex_color) for a single vision label string.

    Substring keyword match, first bucket wins; unmatched -> "other"/cyan."""
    low = (label or "").lower()
    for name, color, keywords in _BUCKETS:
        for kw in keywords:
            if kw in low:
                return name, color
    return _OTHER


def bucket_for_topk(items, min_conf: float = 0.0):
    """Pick a bucket from a top-k list [{label, confidence}, ...].

    Walks the items in confidence order and returns the first that lands in a
    real (non-"other") bucket above min_conf, so a confident but unbucketed top-1
    (e.g. a texture) doesn't mask a clearly-bucketed runner-up. Falls back to the
    top-1's bucket (possibly "other") if nothing qualifies. Returns
    (bucket_name, hex_color, label_that_decided)."""
    if not items:
        return (*_OTHER, "")
    for it in items:
        if it.get("confidence", 0.0) < min_conf:
            continue
        name, color = bucket_for_label(it.get("label", ""))
        if name != _OTHER[0]:
            return name, color, it.get("label", "")
    top = items[0]
    name, color = bucket_for_label(top.get("label", ""))
    return name, color, top.get("label", "")
