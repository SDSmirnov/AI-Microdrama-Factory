"""Category metadata for procedural room-sketch models.

Pure Python: room_sketch.py uses it to classify anchor objects and to attach
size, placement and colour to the render spec. The Blender-side renderer only
sees the resulting category and colour, so it needs no project imports.

Boxes and cylinders are the last resort: anything unmatched is `generic`.
"""
import re

DEFAULT_CATEGORY = 'generic'

# Not drawn: props under ~30 cm (room QA ignores them too) and parts of
# objects that are drawn anyway. A 0.6 m generic box would misplace them.
SKIP_CATEGORY = 'skip'
PROP_MAX_HEIGHT_M, PROP_MAX_SPAN_M = 0.3, 0.5  # below both: a prop, not furniture
# Surfaces and wall fittings are thin by nature: a stated low height is not a prop.
THIN = frozenset({'patch', 'batten', 'pipe', 'tray', 'panel', 'artwork'})

# Ordered; the first matching rule wins. Matched against the id first and the
# label only when the id matches nothing: labels are prose ("Light wood work
# counter", "Floor-standing speaker") and their modifiers hit wrong rules.
# Free-text `notes` are never used: they mention neighbouring objects. Text
# after a linking preposition is dropped ("laptop-on-table" is a laptop, not a
# second table). Simple plural folding; keywords match as whole words/phrases.
CATEGORY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    # Shelving is furniture whatever it holds ("bottle-shelves", "back-bar shelf"); a prop *on* a shelf is cut above.
    ('shelf', ('shelving', 'shelf', 'bookshelf', 'bookcase')),
    (SKIP_CATEGORY, ('laptop', 'mug', 'cup', 'teacup', 'saucer', 'bottle', 'whiskey glass',
                     'wine glass', 'pen', 'pencil', 'phone', 'smartphone', 'keyboard',
                     'clipboard', 'paper', 'binder', 'bowl', 'pan', 'jar', 'blanket',
                     'pillow', 'cushion', 'detector', 'remote', 'pill', 'medicine',
                     'hook', 'text', 'lettering', 'slot', 'sign', 'garland', 'string', 'headboard',
                     'glassware', 'tumbler', 'jug')),
    ('extinguisher', ('extinguisher',)),
    ('spool', ('spool', 'reel', 'coil')),
    # Wall decor before the wall/door/floor rules its labels mention.
    ('artwork', ('artwork', 'art', 'painting', 'picture', 'canvas', 'photo', 'framed',
                 'schematic', 'poster', 'tapestry', 'mirror', 'whiteboard', 'sculpture',
                 'installation', 'crucifix', 'icon')),
    ('monitor', ('monitor', 'screen', 'viewscreen', 'display', 'television', 'tv',
                 'holographic')),
    # Ceiling fixtures: the lamp model is a floor lamp.
    ('batten', ('batten', 'fluorescent', 'light strip', 'ceiling tube', 'ceiling light',
                'overhead light', 'track light', 'track lighting', 'spotlight', 'downlight')),
    ('lamp', ('lamp', 'lantern', 'sconce', 'chandelier', 'light')),
    ('window', ('window', 'skylight', 'glass pane')),
    # Trunking is often described as running "above hatch"; the cable run,
    # not the hatch, is the object.
    ('tray', ('trunking', 'cable tray', 'cable ladder', 'duct')),
    ('panel', ('feature wall', 'accent wall', 'flower wall', 'backdrop')),
    ('door', ('door', 'doorway', 'hatch', 'gate', 'gateway', 'archway', 'arch', 'opening')),
    ('pipe', ('pipe', 'conduit', 'vent')),
    # Human-sized figures and stands share the plinth-and-shaft column model.
    ('column', ('column', 'pillar', 'post', 'beam', 'pedestal', 'statue', 'bust',
                'mannequin', 'spacesuit', 'android', 'skeleton', 'robot', 'coat rack',
                'coat stand', 'barrel', 'cauldron', 'reactor')),
    ('vehicle', ('car', 'truck', 'van', 'bus', 'motorcycle', 'vehicle')),
    # Kitchen and bedroom casework before "table"/"counter" claim it.
    ('cabinet', ('nightstand', 'dresser', 'sideboard', 'credenza', 'media console',
                 'tv stand', 'minibar', 'fridge', 'refrigerator', 'freezer', 'stove',
                 'oven', 'cooker', 'sink', 'dishwasher', 'cooking station', 'galley',
                 'fireplace', 'speaker', 'clock', 'server rack', 'ups', 'converter',
                 'generator', 'machine')),
    ('crate', ('crate', 'carton', 'pallet', 'container', 'box')),
    ('chair', ('chair', 'stool', 'bench', 'seat', 'ottoman')),
    # A counter is a solid block with a worktop: cover, and nothing to see under it.
    ('counter', ('counter', 'countertop', 'bar')),
    ('table', ('table', 'desk', 'island', 'workbench', 'console', 'terminal', 'workstation')),
    ('shelf', ('rack',)),
    ('cabinet', ('cabinet', 'cupboard', 'locker', 'wardrobe', 'drawer', 'filing')),
    ('bed', ('bed', 'mattress', 'cot', 'hammock')),
    ('sofa', ('sofa', 'couch', 'armchair', 'booth', 'loveseat')),
    ('plant', ('plant', 'houseplant', 'tree', 'bush', 'fern', 'flower')),
    ('patch', ('floor', 'deck', 'patch', 'stain', 'mark', 'debris', 'rubble',
               'threshold', 'graffiti', 'rug', 'carpet', 'doormat', 'mat')),
    ('panel', ('wall', 'partition', 'panel', 'breach', 'roof', 'span', 'ceiling',
               'edge', 'curtain', 'drape', 'shower', 'enclosure')),
    # Bare "entrance" names an opening only when nothing else did.
    ('door', ('entrance', 'hole')),
)

# Keyword overrides of the category defaults, first match wins (longer phrases
# first): (height_m, span_m, depth_m), None keeps the category value. Span and
# depth apply only to zero-footprint anchors.
KEYWORD_DIMS_M: tuple[tuple[str, tuple[float | None, float | None, float | None]], ...] = (
    ('coffee table', (0.45, 1.1, 0.6)),
    ('side table', (0.55, 0.5, 0.5)),
    ('bedside table', (0.55, 0.5, 0.4)),
    ('nightstand', (0.55, 0.5, 0.4)),
    ('console table', (0.8, 1.2, 0.35)),
    ('media console', (0.55, 1.6, 0.45)),
    ('tv stand', (0.55, 1.6, 0.45)),
    ('dresser', (0.85, 1.4, 0.5)),
    ('sideboard', (0.85, 1.8, 0.5)),
    ('bar stool', (0.75, None, None)),
    ('stool', (0.45, 0.4, 0.4)),
    ('bench', (0.45, 1.4, 0.4)),
    ('armchair', (0.85, 0.9, 0.9)),
    ('bar', (1.05, None, None)),
    ('counter', (0.92, None, None)),
    ('island', (0.92, 1.8, 0.9)),
    ('wine fridge', (0.85, 0.6, 0.6)),
    ('fridge', (1.8, 0.8, 0.7)),
    ('refrigerator', (1.8, 0.8, 0.7)),
    ('sink', (0.9, 0.8, 0.6)),
    ('stove', (0.9, 0.8, 0.6)),
    ('oven', (0.9, 0.6, 0.6)),
    ('dishwasher', (0.9, 0.6, 0.6)),
    ('fireplace', (1.1, 1.6, 0.5)),
    ('speaker', (1.0, 0.3, 0.35)),
    ('clock', (2.0, 0.5, 0.35)),
    ('double door', (None, 1.6, None)),
    ('full length mirror', (1.9, 0.6, 0.05)),
    ('mirror', (0.9, 0.7, 0.05)),
    ('whiteboard', (1.0, 1.5, 0.05)),
    ('tapestry', (1.8, 1.4, 0.03)),
    ('bust', (1.5, 0.4, 0.4)),
    ('pedestal', (1.1, 0.4, 0.4)),
    ('coat rack', (1.8, 0.45, 0.45)),
    ('barrel', (0.9, 0.6, 0.6)),
    ('cauldron', (0.6, 0.6, 0.6)),
    ('mannequin', (1.75, 0.45, 0.35)),
    ('spacesuit', (1.8, 0.6, 0.4)),
    ('android', (1.8, 0.5, 0.3)),
    ('skeleton', (1.8, 0.5, 0.3)),
    ('bunk bed', (1.7, None, None)),
    ('floor lamp', (1.6, 0.4, 0.4)),
    ('table lamp', (0.5, 0.3, 0.3)),
    ('bedside lamp', (0.5, 0.3, 0.3)),
)

DEFAULT_HEIGHT_M: dict[str, float] = {
    'extinguisher': 0.55,
    'spool': 0.50,
    'monitor': 0.45,
    'batten': 0.10,
    'lamp': 0.60,
    'window': 1.20,
    'door': 2.10,
    'pipe': 0.15,
    'tray': 0.15,
    'column': 2.60,
    'vehicle': 1.50,
    'crate': 0.60,
    'chair': 0.90,
    'table': 0.75,
    'counter': 1.00,
    'shelf': 1.90,
    'cabinet': 1.80,
    'bed': 0.55,
    'sofa': 0.85,
    'plant': 1.00,
    'artwork': 0.80,
    'patch': 0.04,
    'panel': 2.40,
    DEFAULT_CATEGORY: 0.60,
}

# Footprint (span, depth) in metres for anchors saved with width_x = depth_y = 0;
# literal sizes render as 5 cm posts. Span runs along the wall for WALL_MOUNTED.
DEFAULT_FOOTPRINT_M: dict[str, tuple[float, float]] = {
    'extinguisher': (0.2, 0.2), 'spool': (0.5, 0.5), 'monitor': (1.0, 0.08),
    'batten': (1.2, 0.3), 'lamp': (0.45, 0.45), 'window': (1.4, 0.1),
    'door': (0.9, 0.1), 'pipe': (0.15, 1.0), 'tray': (0.3, 1.0),
    'column': (0.45, 0.45), 'vehicle': (1.8, 4.5), 'crate': (0.6, 0.6),
    'chair': (0.55, 0.55), 'table': (1.2, 0.8), 'counter': (1.8, 0.6), 'shelf': (1.0, 0.4),
    'cabinet': (0.8, 0.5), 'bed': (1.6, 2.0), 'sofa': (2.0, 0.9),
    'plant': (0.5, 0.5), 'artwork': (1.2, 0.06), 'patch': (2.0, 1.4),
    'panel': (1.0, 0.1), DEFAULT_CATEGORY: (0.4, 0.4),
}

# A footprint below this share of the room on both axes counts as none: the sketch gives it the category's size.
ZERO_FOOTPRINT = 0.02

# Zero-footprint anchors of these sit on their nearest wall, span along it.
WALL_MOUNTED = frozenset({'door', 'window', 'artwork', 'panel', 'monitor', 'shelf'})

# Objects whose base sits on the floor; their anchor `z` is ignored because
# extraction often reports a visual height rather than a physical centre.
FLOOR_STANDING = frozenset({
    'vehicle', 'crate', 'chair', 'table', 'counter', 'shelf', 'cabinet', 'bed', 'sofa',
    'plant', 'column', 'spool', 'door',
})

CATEGORY_HEX: dict[str, str] = {
    'extinguisher': '#c0392b',
    'spool': '#d35400',
    'monitor': '#2c3e50',
    'batten': '#f1c40f',
    'lamp': '#f39c12',
    'window': '#aed6f1',
    'door': '#8d6e63',
    'pipe': '#7f8c8d',
    'tray': '#95a5a6',
    'column': '#6d7b86',
    'vehicle': '#a93226',
    'crate': '#b9770e',
    'chair': '#16a085',
    'table': '#a0522d',
    'counter': '#7b4a2a',
    'shelf': '#5d6d7e',
    'cabinet': '#7d8c3a',
    'bed': '#8e6e95',
    'sofa': '#3b7a57',
    'plant': '#27ae60',
    'artwork': '#8e6bbf',
    'patch': '#aab2b8',
    'panel': '#bcc3c8',
    DEFAULT_CATEGORY: '#9aa0a6',
}


_PLURAL_ES = ('ches', 'shes', 'sses', 'xes')
# "to" is not a link: "floor-to-ceiling window", "archway-to-living-room". "and" is: a group is
# named after its first member ("table-and-chairs" is a table).
_LINKS = frozenset({'on', 'over', 'above', 'under', 'below', 'near', 'by', 'beside',
                    'behind', 'with', 'and'})
# Where a thing is, unless it is the thing itself: "wall-crucifix" hangs on a wall, "back-wall" is one.
_PLACE_WORDS = frozenset({'wall', 'ceiling', 'floor'})


def _singular(token: str) -> str:
    if len(token) <= 3 or not token.endswith('s') or token.endswith('ss'):
        return token
    if token.endswith('ves'):
        return token[:-3] + 'f'
    return token[:-2] if token.endswith(_PLURAL_ES) else token[:-1]


def _normalise(text: str) -> str:
    """Head phrase: singular tokens up to the first linking preposition."""
    tokens = [_singular(t) for t in re.findall(r'[a-z0-9]+', (text or '').lower())]
    cut = next((i for i, t in enumerate(tokens) if i and t in _LINKS), len(tokens))
    return ' ' + ' '.join(tokens[:cut]) + ' '


def _texts(obj: dict) -> list[str]:
    return [_normalise(str(obj.get(key) or '')) for key in ('id', 'label')]


def _match(text: str, keyword: str) -> bool:
    return text.endswith(f' {keyword} ') if keyword in _PLACE_WORDS else f' {keyword} ' in text


# Standing places named by their last word ("barman-behind-counter-spot") are zones, never furniture.
SPOT_WORDS = frozenset({'spot', 'stance', 'position', 'zone', 'area'})


def is_spot(obj: dict) -> bool:
    words = re.findall(r'[a-z0-9]+', str(obj.get('id') or '').lower())
    return bool(words) and words[-1] in SPOT_WORDS


def classify_object(obj: dict) -> str:
    if is_spot(obj):
        return SKIP_CATEGORY
    for text in _texts(obj):
        for category, keywords in CATEGORY_RULES:
            if any(_match(text, k) for k in keywords):
                return category
    return 'door' if obj.get('opens') else DEFAULT_CATEGORY  # a "passage" with a stated mechanism


def keyword_dims_m(obj: dict) -> tuple[float | None, float | None, float | None]:
    """(height, span, depth) override for the first keyword the id, else label, names."""
    for text in _texts(obj):
        for keyword, dims in KEYWORD_DIMS_M:
            if _match(text, keyword):
                return dims
    return None, None, None


def srgb_hex_to_linear(hex_color: str) -> list[float]:
    value = hex_color.lstrip('#')
    channels = [int(value[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    return [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
            for c in channels]
