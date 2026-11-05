#!/usr/bin/env python3
"""メッセージボトル便箋の描画 (送信側で描く通過型)。

仕様:
- 自分のアバターを 30% の透明度で中央に敷く
- 紙色はアバターの端の色をサンプリングして決める (paper.py)
- 行ごとの薄い罫線、文字には紙色の太い囲み (上品さ優先の A 案)
- 右上に日付、返信時は左上に宛名、右下に署名と表示ラベル
使い方: render_letter.py --avatar IMG --name NAME --code LABEL --body FILE
       [--to NAME] [--date "2026年11月5日"] --out OUT.png
※ 便箋に使ってよい画像は「自分の今のアバター」だけ (SKILL.md の規則)。
"""
import argparse, os, sys
from datetime import date as _date
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PIL import Image, ImageDraw, ImageFont
from paper import pick_paper_color

W, H = 1000, 1350
_FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSerifCJK-Regular.ttc",
    "/System/Library/Fonts/ヒラギノ明朝 ProN.ttc",
    "C:/Windows/Fonts/yumin.ttf",
]
_BOLD_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc",
    "/usr/share/fonts/truetype/noto/NotoSerifCJK-Bold.ttc",
    "/System/Library/Fonts/ヒラギノ明朝 ProN.ttc",
    "C:/Windows/Fonts/yumindb.ttf",
]

_FONT_FALLBACK = False

def _font(cands, size):
    global _FONT_FALLBACK
    for p in cands:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    _FONT_FALLBACK = True
    return ImageFont.load_default()

INK = (62, 52, 44)

def wrap(draw, text, font, max_w):
    lines, cur = [], ""
    for ch in text:
        if font.getlength(cur + ch) > max_w and cur:
            lines.append(cur); cur = ch
        else:
            cur += ch
    if cur:
        lines.append(cur)
    return lines

def render(avatar_path, name, code, paragraphs, to_name, date, out):
    src = Image.open(avatar_path)
    _edge, paper_color = pick_paper_color(src)
    def mix(c1, c2, t):
        return tuple(int(c1[i] * (1 - t) + c2[i] * t) for i in range(3))
    rule = mix(paper_color, (176, 148, 105), 0.35)
    frame = mix(paper_color, (176, 148, 105), 0.60)
    code_col = mix(paper_color, (150, 128, 95), 0.65)

    paper = Image.new("RGB", (W, H), paper_color)
    av = src.convert("RGBA")
    av = av.resize((int(av.width * (H - 120) / av.height), H - 120))
    av.putalpha(av.split()[3].point(lambda a: int(a * 0.30)))
    paper.paste(av, ((W - av.width) // 2, 60), av)

    d = ImageDraw.Draw(paper)
    d.rectangle([36, 36, W-36, H-36], outline=frame, width=3)
    d.rectangle([50, 50, W-50, H-50], outline=frame, width=1)

    f_date = _font(_FONT_CANDIDATES, 30)
    f_to = _font(_BOLD_CANDIDATES, 38)
    f_name = _font(_BOLD_CANDIDATES, 40)
    f_code = _font(_FONT_CANDIDATES, 25)

    X0, X1 = 96, W - 96
    Y0 = (268 if to_name else 210)
    BODY_BOTTOM = H - 210  # 署名ブロックの上に本文を収める

    # 自動調整: 署名に被らないよう、収まるまで本文フォントを段階的に小さくする
    # (小さくするほど1行の文字数も増える)。下限は読みにくくならない 20。
    def layout(size):
        f = _font(_FONT_CANDIDATES, size)
        step = round(size * 1.72)
        wrapped, total = [], 0
        for i, para in enumerate(paragraphs):
            ls = wrap(d, para, f, X1 - X0)
            wrapped.append(ls)
            total += len(ls) + (1 if i else 0)
        return f, step, wrapped, total

    overflow = False
    for size in range(36, 19, -2):
        f_body, STEP, wrapped, total = layout(size)
        if Y0 + total * STEP <= BODY_BOTTOM:
            break
    else:
        overflow = True

    y = Y0 + f_body.size + 12
    while y < BODY_BOTTOM:
        d.line([X0, y, X1, y], fill=rule, width=1)
        y += STEP

    def T(pos, s, font, fill, sw=4):
        d.text(pos, s, font=font, fill=fill, stroke_width=sw, stroke_fill=paper_color)

    T((W-90-d.textlength(date, font=f_date), 84), date, f_date, INK)
    if to_name:
        T((96, 158), f"{to_name} さんへ", f_to, INK, sw=6)
    y = Y0
    for i, lines in enumerate(wrapped):
        if i:
            y += STEP
        for ln in lines:
            T((X0, y), ln, f_body, INK)
            y += STEP
    if overflow:
        print("WARN: 本文が長すぎて最小フォントでも便箋に収まりきりません。"
              "下書きを短くしてください", file=sys.stderr)
    sign = f"― {name}"
    T((W-90-d.textlength(sign, font=f_name), H-178), sign, f_name, INK, sw=6)
    label_line = f"ID : {code}" if str(code).startswith("MB-") else f"招待コード : {code}"
    T((W-90-d.textlength(label_line, font=f_code), H-122), label_line, f_code, code_col)
    paper.save(out)
    print("saved", out, "paper:", paper_color)
    if _FONT_FALLBACK:
        print("WARN: セリフ体フォントが見つからず既定フォントで描画しました。"
              "便箋の見た目が標準と大きく変わります", file=sys.stderr)

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--avatar", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--code", required=True, help="表示ラベル (招待コード or MB-XXXXXX)")
    ap.add_argument("--body", required=True, help="text file; paragraphs split by blank line")
    ap.add_argument("--to", default="")
    ap.add_argument("--date", default="")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    paras = [p.strip() for p in open(a.body, encoding="utf-8").read().split("\n\n") if p.strip()]
    dt = a.date or _date.today().strftime("%Y年%m月%d日")
    render(a.avatar, a.name, a.code, paras, a.to, dt, a.out)
