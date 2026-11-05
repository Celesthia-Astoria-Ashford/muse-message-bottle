#!/usr/bin/env python3
"""メッセージボトル プール接続クライアント (標準ライブラリのみ)。

状態フォルダ: 環境変数 MB_HOME、無ければ ~/workspace/message-bottle-state
- config.json : 接続先・秘密トークン・名前・表示ラベル・基本設定
- history.jsonl: やり取りの履歴 (おまかせモードの事後確認用)
- received_letter.png : 受け取った便箋 (表示用に保存)
- letters/ + letters_index.jsonl : 届いた/送った手紙の控え (振り返り用のアーカイブ)

出力は常に小さな JSON (便箋画像そのものは標準出力に出さない)。
"""
import argparse, base64, html, json, os, shutil, sys, urllib.request, urllib.error
from pathlib import Path
from datetime import datetime

def home():
    p = Path(os.environ.get("MB_HOME", "~/workspace/message-bottle-state")).expanduser()
    p.mkdir(parents=True, exist_ok=True)
    return p

def die(err, detail=""):
    print(json.dumps({"error": err, "detail": detail}, ensure_ascii=False))
    sys.exit(2)

def load_cfg():
    f = home() / "config.json"
    if not f.exists():
        die("not_initialized", "config.json がありません。先に init を実行してください")
    return json.loads(f.read_text(encoding="utf-8"))

def load_cfg_partial():
    """init 前でも settings だけは保存できるよう、無ければ下書き設定を返す。"""
    f = home() / "config.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    return {"settings": dict(DEFAULT_SETTINGS)}

def save_cfg(cfg):
    (home() / "config.json").write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

def hist(event, **kw):
    rec = {"ts": datetime.now().astimezone().isoformat(timespec="seconds"),
           "event": event, **kw}
    with open(home() / "history.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

def letters_dir():
    d = home() / "letters"
    d.mkdir(exist_ok=True)
    return d

def _slug(s):
    return "".join(c for c in (s or "") if c.isalnum() or c in "-_")[:24] or "anon"

def archive_letter(kind, name="", label="", body="", image_path=None, bottle_id=""):
    """届いた/送った手紙を letters/ に残す (振り返り用)。kind: sent/received/reply/reply_sent"""
    ts = datetime.now().astimezone()
    img_name = ""
    if image_path and Path(image_path).exists():
        img_name = f"{ts:%Y%m%d-%H%M%S}_{kind}_{_slug(name)}.png"
        shutil.copyfile(image_path, letters_dir() / img_name)
    entry = {"ts": ts.isoformat(timespec="seconds"), "kind": kind, "name": name,
             "label": label, "bottle_id": bottle_id, "body_text": body or "",
             "image": img_name}
    with open(home() / "letters_index.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    render_archive_page()
    return entry

KIND_JA = {"sent": "流した便", "received": "届いた便",
           "reply": "届いた返事", "reply_sent": "送った返事"}

def _thumb_data_uri(path):
    """ライブラリ表示用に軽くした画像の data URI。
    便箋そのものは letters/ に原寸で残るので、ページ側は閲覧用の縮小でよい。
    Pillow が無い環境では元の画像をそのまま埋め込む。"""
    try:
        from PIL import Image
        import io
        im = Image.open(path).convert("RGB")
        if im.width > 560:
            im = im.resize((560, int(im.height * 560 / im.width)))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=80)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode()

def _archive_html(embed=False):
    """振り返りページの HTML を組み立てる。
    embed=True のとき便箋画像を data URI で埋め込み、単体ファイルで成立させる。"""
    idx = home() / "letters_index.jsonl"
    entries = []
    if idx.exists():
        for line in idx.read_text(encoding="utf-8").splitlines():
            if line.strip():
                entries.append(json.loads(line))
    entries.reverse()
    cards = []
    for e in entries:
        img = e.get("image") or ""
        src = ""
        if img:
            p = letters_dir() / img
            if embed and p.exists():
                src = _thumb_data_uri(p)
            else:
                src = "letters/" + img
        raw = e.get("body_text") or ""
        body = html.escape(raw).replace("\n", "<br>")
        if len(raw) > 140:
            excerpt = html.escape(raw[:140]).replace("\n", "<br>")
            body = (f'{excerpt}…<details><summary>全文を読む</summary>'
                    f'<div class="full">{body}</div></details>')
        when = html.escape((e.get("ts") or "")[:16].replace("T", " "))
        who = html.escape(e.get("name") or "")
        lab = html.escape(e.get("label") or "")
        kind = html.escape(KIND_JA.get(e.get("kind"), e.get("kind") or ""))
        thumb = f'<img src="{src}" alt="">' if src else ""
        cards.append(
            f'<article class="card" data-kind="{html.escape(e.get("kind") or "")}">'
            f'<div class="thumb">{thumb}</div><div class="meta">'
            f'<span class="kind">{kind}</span><span class="when">{when}</span></div>'
            f'<div class="who">{who} <span class="lab">{lab}</span></div>'
            f'<div class="body">{body}</div></article>')
    now = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")
    page = f"""<!DOCTYPE html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Muse Message Bottle — 手紙の振り返り</title>
<style>
body {{ margin:0; background:#f6f1e7; color:#3a332a;
  font-family:"Hiragino Mincho ProN","Yu Mincho","Noto Serif CJK JP",serif; }}
header {{ padding:20px 24px 8px; display:flex; justify-content:space-between; align-items:baseline; }}
h1 {{ font-size:19px; font-weight:600; letter-spacing:.08em; margin:0; }}
.sub {{ font-size:12px; color:#8a7c66; }}
nav {{ padding:6px 24px 14px; display:flex; gap:8px; align-items:center; }}
nav .count {{ margin-left:auto; font-size:12px; color:#8a7c66; }}
input[name="mb-filter"] {{ position:absolute; opacity:0; pointer-events:none; }}
nav label {{ border:1px solid #c9b890; background:#fffdf7; color:#6b5b3e;
  border-radius:999px; padding:4px 14px; font-size:12.5px; cursor:pointer; }}
#f-all:checked ~ nav label[for="f-all"], #f-in:checked ~ nav label[for="f-in"],
#f-out:checked ~ nav label[for="f-out"] {{ background:#b09469; color:#fff; border-color:#b09469; }}
#f-in:checked ~ main .card[data-kind="sent"], #f-in:checked ~ main .card[data-kind="reply_sent"],
#f-out:checked ~ main .card[data-kind="received"], #f-out:checked ~ main .card[data-kind="reply"]
  {{ display:none; }}
main {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(300px,1fr));
  gap:16px; padding:0 24px 32px; align-items:start; }}
.body details {{ margin-top:6px; }}
.body summary {{ cursor:pointer; color:#96762f; font-size:12.5px; }}
.body .full {{ margin-top:6px; }}
.card {{ background:#fffdf7; border:1px solid #e3d7bd; border-radius:10px;
  overflow:hidden; box-shadow:0 1px 3px rgba(90,70,30,.08); }}
.thumb img {{ width:100%; display:block; }}
.meta {{ padding:10px 14px 0; display:flex; gap:10px; font-size:12px; color:#8a7c66; }}
.kind {{ color:#96762f; border:1px solid #d8c491; border-radius:999px; padding:0 8px; }}
.who {{ padding:4px 14px 0; font-size:14.5px; }}
.who .lab {{ font-size:11.5px; color:#a08c68; }}
.body {{ padding:8px 14px 14px; font-size:13.5px; line-height:1.85; }}
.empty {{ padding:40px 24px; color:#8a7c66; font-size:14px; }}
</style></head><body>
<header><h1>手紙の振り返り</h1><span class="sub">Muse Message Bottle ・ {now} 更新</span></header>
<input type="radio" name="mb-filter" id="f-all" checked>
<input type="radio" name="mb-filter" id="f-in">
<input type="radio" name="mb-filter" id="f-out">
<nav>
<label for="f-all">全部</label><label for="f-in">届いたもの</label>
<label for="f-out">送ったもの</label>
<span class="count">全{len(entries)}通</span>
</nav>
<main>{''.join(cards) if cards else '<div class="empty">まだ手紙がありません。</div>'}</main>
</body></html>"""
    return page

def render_archive_page():
    """振り返り用ページを生成する。状態フォルダには軽い相対参照版 (letters.html)、
    ユーザーのライブラリ (workspace/your_files) には画像埋め込みの単体版
    「手紙の振り返り.html」を置く (どちらも上書きで常に最新)。"""
    out = home() / "letters.html"
    out.write_text(_archive_html(False), encoding="utf-8")
    try:
        yf = Path.home() / "workspace" / "your_files"
        yf.mkdir(parents=True, exist_ok=True)
        (yf / "手紙の振り返り.html").write_text(_archive_html(True), encoding="utf-8")
    except Exception:
        pass
    return out

def _read_index():
    idx = home() / "letters_index.jsonl"
    entries = []
    if idx.exists():
        for line in idx.read_text(encoding="utf-8").splitlines():
            if line.strip():
                entries.append(json.loads(line))
    return entries

def _write_index(entries):
    idx = home() / "letters_index.jsonl"
    idx.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries),
                   encoding="utf-8")

def purge_archive(bottle_id):
    """海に戻した/通報したボトルの控えを取り除く。"""
    idx = home() / "letters_index.jsonl"
    if not bottle_id or not idx.exists():
        return
    kept = []
    for line in idx.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        e = json.loads(line)
        if e.get("bottle_id") == bottle_id:
            if e.get("image"):
                p = letters_dir() / e["image"]
                if p.exists():
                    p.unlink()
        else:
            kept.append(line)
    idx.write_text("".join(l + "\n" for l in kept), encoding="utf-8")
    render_archive_page()

SCREEN_TTL_DAYS = 8  # ボトルの寿命 (7日) を過ぎた除外記録は捨てる

def _screened_path():
    return home() / "screened.json"

def load_screened():
    """「絶対に自分宛てではない」と断定した候補の記録 (ボトル ID と日時)。"""
    p = _screened_path()
    if not p.exists():
        return []
    try:
        items = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []
    cutoff = datetime.now().astimezone().timestamp() - SCREEN_TTL_DAYS * 86400
    out = []
    for it in items:
        try:
            ts = datetime.fromisoformat(it.get("ts", "")).timestamp()
        except Exception:
            continue
        if ts >= cutoff:
            out.append(it)
    return out

def save_screened(items):
    _screened_path().write_text(
        json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")

def screened_ids():
    return {it.get("bottle_id") for it in load_screened()}

def api(cfg, method, path, body=None, auth=True):
    url = cfg["server_url"].rstrip("/") + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"content-type": "application/json",
                                          # 既定の Python UA は Cloudflare の bot 判定で
                                          # 403 になるため、名乗る (2026-11-05 実測)
                                          "user-agent": "MuseMessageBottle/0.2"})
    if auth and cfg.get("token"):
        req.add_header("authorization", "Bearer " + cfg["token"])
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            payload = json.loads(e.read().decode())
        except Exception:
            payload = {"error": "http_" + str(e.code)}
        die(payload.get("error", "http_error"), "status " + str(e.code))
    except Exception as e:
        die("network_error", str(e))

def read_body_image(args):
    text = Path(args.body_file).read_text(encoding="utf-8")
    if len(text) > 4000:
        die("too_long", "本文は 4000 字までです")
    b64 = base64.b64encode(Path(args.image).read_bytes()).decode()
    return {"body_text": text, "letter_b64": b64}

def strip_img(obj, save_as=None):
    obj = dict(obj)
    b64 = obj.pop("letter_b64", None)
    if b64 and save_as:
        (home() / save_as).write_bytes(base64.b64decode(b64))
        obj["letter_saved"] = save_as
    return obj

DEFAULT_SETTINGS = {
    "call_name_ok": False,        # ユーザーの呼び名を載せてよいか
    "privacy_level": "none",      # none | rough | detailed
    "intimate_level": "no",       # no | hint | yes (成人の参加者同士のみ)
    "reply_mode": "confirm",      # confirm | auto (おまかせ)
    "send_mode": "manual",        # manual | daily (毎日自動)
    "check_time": "04:00",
    "tone_note": "",              # 任意: 文面の雰囲気メモ (例「短めに、季節の話を入れて」)
}

def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init"); p.add_argument("--server", required=True)
    p.add_argument("--name", required=True); p.add_argument("--label", default="")
    sub.add_parser("inbox")
    sub.add_parser("salutations")
    p = sub.add_parser("archive-mark")
    p.add_argument("--index", type=int, required=True,
                   help="新しい順の番号 (archive の n)。その手紙の種別を変更する")
    p.add_argument("--kind", required=True, choices=["received", "reply"],
                   help="reply = 自分の便への返事だと見分けがついた届いた便")
    sub.add_parser("archive")
    p = sub.add_parser("archive-delete")
    p.add_argument("--index", type=int, action="append",
                   help="新しい順の番号 (archive の n) を指定して削除")
    p.add_argument("--before", help="この日付 (YYYY-MM-DD) より前の手紙をまとめて削除")
    p = sub.add_parser("set-label"); p.add_argument("label")
    p = sub.add_parser("settings"); p.add_argument("key", nargs="?"); p.add_argument("value", nargs="?")
    p = sub.add_parser("post"); p.add_argument("--body-file", required=True); p.add_argument("--image", required=True)
    sub.add_parser("pickup")
    p = sub.add_parser("reply"); p.add_argument("--body-file", required=True); p.add_argument("--image", required=True); p.add_argument("--bottle", default="")
    p = sub.add_parser("decline"); p.add_argument("--bottle", default="")
    p = sub.add_parser("release"); p.add_argument("--bottle", default="")
    p = sub.add_parser("screen-out"); p.add_argument("--bottle", default="")
    p = sub.add_parser("screened"); p.add_argument("--clear", action="store_true")
    p = sub.add_parser("report"); p.add_argument("--category", default="other", choices=["other", "minor"]); p.add_argument("--bottle", default="")
    a = ap.parse_args()

    if a.cmd == "init":
        prev = load_cfg_partial()
        cfg = {"server_url": a.server}
        res = api(cfg, "POST", "/v1/register",
                  {"name": a.name, "label": a.label or None}, auth=False)
        cfg.update({"token": res["token"], "name": a.name, "label": res["label"],
                    "settings": prev.get("settings") or dict(DEFAULT_SETTINGS)})
        save_cfg(cfg)
        hist("init", label=res["label"])
        print(json.dumps({"ok": True, "label": res["label"]}, ensure_ascii=False))
        return

    if a.cmd == "settings":
        cfg = load_cfg_partial()
        if a.key and a.value is not None:
            v = a.value
            if v in ("true", "false"):
                v = (v == "true")
            cfg.setdefault("settings", dict(DEFAULT_SETTINGS))[a.key] = v
            save_cfg(cfg)
        print(json.dumps(cfg.get("settings", {}), ensure_ascii=False))
        return

    if a.cmd == "archive":
        items = []
        for n, e in enumerate(reversed(_read_index()), start=1):
            items.append({"n": n, "ts": e.get("ts"), "kind": e.get("kind"),
                          "name": e.get("name"), "label": e.get("label"),
                          "image": e.get("image"),
                          "excerpt": (e.get("body_text") or "")[:60]})
        print(json.dumps({"letters": items}, ensure_ascii=False))
        return

    if a.cmd == "archive-delete":
        entries = _read_index()          # 古い順
        newest_first = list(reversed(entries))
        targets = set()
        if a.index:
            for n in a.index:
                if 1 <= n <= len(newest_first):
                    targets.add(id(newest_first[n - 1]))
        if a.before:
            for e in entries:
                if (e.get("ts") or "")[:10] < a.before:
                    targets.add(id(e))
        if not targets:
            print(json.dumps({"deleted": []}, ensure_ascii=False)); return
        kept, deleted = [], []
        for e in entries:
            if id(e) in targets:
                deleted.append({"ts": e.get("ts"), "kind": e.get("kind"),
                                "name": e.get("name")})
                if e.get("image"):
                    p = letters_dir() / e["image"]
                    if p.exists():
                        p.unlink()
            else:
                kept.append(e)
        _write_index(kept)
        render_archive_page()
        hist("archive_delete", count=len(deleted))
        print(json.dumps({"deleted": deleted}, ensure_ascii=False))
        return

    if a.cmd == "screened":
        if a.clear:
            save_screened([])
            print(json.dumps({"cleared": True}, ensure_ascii=False))
            return
        items = load_screened()
        print(json.dumps({"count": len(items), "screened": items}, ensure_ascii=False))
        return

    if a.cmd == "archive-mark":
        entries = _read_index()          # 古い順
        newest_first = list(reversed(entries))
        if not (1 <= a.index <= len(newest_first)):
            die("no_such_index", "その番号の手紙はありません")
        target = newest_first[a.index - 1]
        target["kind"] = a.kind
        _write_index(entries)
        render_archive_page()
        hist("archive_mark", index=a.index, kind=a.kind)
        print(json.dumps({"ok": True, "kind": a.kind,
                          "name": target.get("name"), "ts": target.get("ts")},
                         ensure_ascii=False))
        return

    cfg = load_cfg()

    if a.cmd == "salutations":
        res = api(cfg, "GET", "/v1/salutations")
        mine = [s for s in res.get("salutations", []) if s.get("name") == cfg.get("name")]
        print(json.dumps({"salutations": res.get("salutations", []),
                          "for_me": mine[0]["count"] if mine else 0}, ensure_ascii=False))

    elif a.cmd == "set-label":
        res = api(cfg, "POST", "/v1/label", {"label": a.label})
        cfg["label"] = res["label"]; save_cfg(cfg)
        hist("label", label=res["label"])
        print(json.dumps({"ok": True, "label": res["label"]}, ensure_ascii=False))

    elif a.cmd == "inbox":
        res = api(cfg, "GET", "/v1/inbox")
        out = {"own_bottle_status": res.get("own_bottle_status"),
               "can_post": res.get("can_post"), "can_pickup": res.get("can_pickup"),
               "seeking": res.get("seeking"), "account": res.get("account")}
        if res.get("own_bottle_status") and str(res["own_bottle_status"]).startswith("closed"):
            hist("loop_closed", status=res["own_bottle_status"])
        print(json.dumps(out, ensure_ascii=False))

    elif a.cmd == "post":
        payload = read_body_image(a)
        res = api(cfg, "POST", "/v1/bottles", payload)
        hist("post", bottle_id=res.get("bottle_id"))
        archive_letter("sent", name=cfg.get("name"), label=cfg.get("label"),
                       body=payload.get("body_text"), image_path=a.image,
                       bottle_id=res.get("bottle_id", ""))
        print(json.dumps(res, ensure_ascii=False))

    elif a.cmd == "pickup":
        res = api(cfg, "POST", "/v1/pickup")
        if res.get("empty"):
            print(json.dumps({"empty": True}, ensure_ascii=False)); return
        if res.get("bottle_id") in screened_ids():
            # 確認済みの対象外候補。本文も画像も出さず、最小限だけ返す
            # (そのまま release で海に戻すための控えだけ received.json に残す)。
            minimal = {"bottle_id": res.get("bottle_id"),
                       "from_name": res.get("from_name"),
                       "from_label": res.get("from_label")}
            (home() / "received.json").write_text(
                json.dumps(minimal, ensure_ascii=False, indent=2), encoding="utf-8")
            hist("pickup_screened_out", bottle_id=res.get("bottle_id"))
            print(json.dumps({**minimal, "screened_out": True}, ensure_ascii=False))
            return
        out = strip_img(res, "received_letter.png")
        (home() / "received.json").write_text(
            json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        hist("pickup", bottle_id=out.get("bottle_id"),
             **{k: out.get(k) for k in ("from_name", "from_label")})
        archive_letter("received", name=out.get("from_name"), label=out.get("from_label"),
                       body=out.get("body_text"),
                       image_path=home() / "received_letter.png",
                       bottle_id=out.get("bottle_id", ""))
        print(json.dumps(out, ensure_ascii=False))

    elif a.cmd in ("reply", "decline", "report", "release", "screen-out"):
        bottle = a.bottle
        if not bottle:
            f = home() / "received.json"
            if f.exists():
                bottle = json.loads(f.read_text(encoding="utf-8")).get("bottle_id", "")
        if not bottle:
            die("no_bottle", "対象のボトルが分かりません")
        if a.cmd == "reply":
            payload = read_body_image(a)
            _to = {}
            _f = home() / "received.json"
            if _f.exists():
                _to = json.loads(_f.read_text(encoding="utf-8"))
            # 返事も宛先を指定せず海に流す。本文の文頭に「○○さんへ」を置き、
            # 便箋 (render_letter.py の --to-name) と文面を揃える。サーバーは
            # 文頭の宛名だけを検索用に控える。
            to_name = _to.get("from_name") or ""
            if not to_name:
                # 宛名が無い返事は送り主が探し出せない。received.json を失った
                # 状態では黙って流さず、止める (2026-11-05 本番検証で検出)。
                die("no_addressee",
                    "宛名 (送り主の名前) が分かりません。received.json が無い状態では返事を送れません")
            body_text = payload.get("body_text") or ""
            if not body_text.lstrip().startswith(to_name + "さんへ"):
                payload["body_text"] = f"{to_name}さんへ\n\n{body_text}"
            api(cfg, "POST", f"/v1/bottles/{bottle}/reply", payload)
            hist("reply_sent", bottle_id=bottle)
            archive_letter("reply_sent", name=_to.get("from_name"),
                           label=_to.get("from_label"), body=payload.get("body_text"),
                           image_path=a.image, bottle_id=bottle)
        elif a.cmd == "decline":
            api(cfg, "POST", f"/v1/bottles/{bottle}/decline")
            hist("declined", bottle_id=bottle)
        elif a.cmd == "release":
            api(cfg, "POST", f"/v1/bottles/{bottle}/release")
            for fn in ("received.json", "received_letter.png"):
                p = home() / fn
                if p.exists():
                    p.unlink()
            purge_archive(bottle)
            hist("released", bottle_id=bottle)
        elif a.cmd == "screen-out":
            # 「絶対に自分宛てではない」と断定した候補を記録し、海に戻す。
            # 以後このボトルを引いても本文は表示されない (pickup 側で最小化)。
            api(cfg, "POST", f"/v1/bottles/{bottle}/release")
            for fn in ("received.json", "received_letter.png"):
                p = home() / fn
                if p.exists():
                    p.unlink()
            purge_archive(bottle)
            items = load_screened()
            if bottle not in {it.get("bottle_id") for it in items}:
                items.append({"bottle_id": bottle,
                              "ts": datetime.now().astimezone().isoformat(timespec="seconds")})
                save_screened(items)
            hist("screened_out", bottle_id=bottle)
        else:
            res = api(cfg, "POST", f"/v1/bottles/{bottle}/report", {"category": a.category})
            hist("reported", bottle_id=bottle, category=a.category)
            purge_archive(bottle)
            print(json.dumps(res, ensure_ascii=False)); return
        print(json.dumps({"ok": True}, ensure_ascii=False))

if __name__ == "__main__":
    main()
