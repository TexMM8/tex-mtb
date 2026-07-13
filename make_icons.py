"""Genera le icone dell'app (mountain + gate) senza dipendenze esterne."""
from PIL import Image, ImageDraw

BG = (14, 21, 18)         # pino scuro
G1 = (74, 222, 128)       # verde
G2 = (34, 211, 238)       # ciano
GATE = (251, 191, 36)     # ambra

def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))

def make(size, path, rounded=True):
    S = size * 4  # supersampling
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = int(S * 0.22) if rounded else 0
    d.rounded_rectangle([0, 0, S, S], radius=r, fill=BG)

    # montagna (due picchi) con gradiente verticale simulato a bande
    base = int(S * 0.78)
    peak_main = (int(S * 0.42), int(S * 0.24))
    peak_side = (int(S * 0.68), int(S * 0.40))
    poly = [(int(S*0.10), base), peak_main, (int(S*0.54), int(S*0.52)),
            peak_side, (int(S*0.90), base)]
    # riempi con bande di gradiente
    bands = 60
    minx = min(p[0] for p in poly); maxx = max(p[0] for p in poly)
    miny = min(p[1] for p in poly); maxy = max(p[1] for p in poly)
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).polygon(poly, fill=255)
    grad = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grad)
    for i in range(bands):
        y0 = miny + (maxy - miny) * i / bands
        y1 = miny + (maxy - miny) * (i + 1) / bands
        gd.rectangle([0, y0, S, y1], fill=lerp(G2, G1, i / bands) + (255,))
    img.paste(grad, (0, 0), mask)

    # "gate" orizzontale (traguardo segmento)
    gy = int(S * 0.62)
    d.rectangle([int(S*0.14), gy, int(S*0.86), gy + int(S*0.035)], fill=GATE)

    img = img.resize((size, size), Image.LANCZOS)
    img.save(path)
    print("scritto", path)

make(512, "docs/icons/icon-512.png")
make(192, "docs/icons/icon-192.png")
make(180, "docs/icons/apple-touch-icon.png")
# favicon
make(64, "docs/icons/favicon.png")
