from PIL import Image
import statistics

IVORY = (253, 249, 240)

def sample_edge_color(im):
    im = im.convert("RGB")
    w, h = im.size
    px = []
    step = max(1, min(w, h) // 60)
    for x in range(0, w, step):
        px.append(im.getpixel((x, 2))); px.append(im.getpixel((x, h - 3)))
    for y in range(0, h, step):
        px.append(im.getpixel((2, y))); px.append(im.getpixel((w - 3, y)))
    return tuple(int(statistics.median([p[i] for p in px])) for i in range(3))

def pick_paper_color(im):
    """Sample the avatar's edge color and blend it toward ivory so the
    letter paper harmonizes with the avatar but stays light/elegant."""
    edge = sample_edge_color(im)
    lum = 0.299 * edge[0] + 0.587 * edge[1] + 0.114 * edge[2]
    # dark edges get blended much more toward ivory to keep ink readable
    toward_ivory = 0.88 if lum < 100 else (0.72 if lum < 180 else 0.55)
    paper = tuple(int(edge[i] * (1 - toward_ivory) + IVORY[i] * toward_ivory)
                  for i in range(3))
    return edge, paper
