#!/usr/bin/env python3
"""
photos/  ->  fal BiRefNet v2  ->  demo/img/*.png   (transparent cut-outs)

Shoot the five objects yourself on any flat surface, drop the JPGs in ./photos/
named after the item ids used in demo/index.html:

    photos/chupa.jpg  hacendado.jpg  damm.jpg  freixenet.jpg  colacao.jpg

Then:
    export FAL_KEY=...
    python3 cutouts.py

Nothing here generates an image. BiRefNet only removes the background from the
photograph you took, which is the only use of a generative-media API this piece
can honestly make: every object on the shelf has to be a real object.
"""
import os, sys, json, time, pathlib, mimetypes
import urllib.request, urllib.error

FAL_KEY = os.environ.get("FAL_KEY")
if not FAL_KEY:
    sys.exit("FAL_KEY not set.  export FAL_KEY=...")

SRC = pathlib.Path("photos")
OUT = pathlib.Path("demo/img")
OUT.mkdir(parents=True, exist_ok=True)

RUN_URL   = "https://fal.run/fal-ai/birefnet/v2"          # synchronous
QUEUE_URL = "https://queue.fal.run/fal-ai/birefnet/v2"    # async, if a photo is large
UPLOAD_INIT = "https://rest.alpha.fal.ai/storage/upload/initiate"

AUTH = {"Authorization": "Key " + FAL_KEY}


def post_json(url, payload, timeout=300):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), method="POST",
        headers={**AUTH, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def upload(path: pathlib.Path) -> str:
    """Put a local file in fal storage and return its public URL."""
    ctype = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    init = post_json(UPLOAD_INIT, {"content_type": ctype, "file_name": path.name})
    put = urllib.request.Request(
        init["upload_url"], data=path.read_bytes(), method="PUT",
        headers={"Content-Type": ctype})
    urllib.request.urlopen(put, timeout=300).read()
    return init["file_url"]


def cut(image_url: str) -> str:
    out = post_json(RUN_URL, {
        "image_url": image_url,
        # Heavy is slower but keeps the lollipop stick and bottle neck intact;
        # thin objects fall apart on Light.
        "model": "General Use (Heavy)",
        "operating_resolution": "2048x2048",
        "refine_foreground": True,
        "output_format": "png",
    })
    return out["image"]["url"]


def download(url: str, dest: pathlib.Path):
    with urllib.request.urlopen(url, timeout=300) as r:
        dest.write_bytes(r.read())


def main():
    photos = sorted(p for p in SRC.glob("*")
                    if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"))
    if not photos:
        sys.exit(f"no photos in {SRC.resolve()}")

    for p in photos:
        dest = OUT / (p.stem + ".png")
        if dest.exists():
            print(f"  skip   {p.name} -> {dest} (exists)")
            continue
        t0 = time.time()
        try:
            src_url = upload(p)
            cut_url = cut(src_url)
            download(cut_url, dest)
            kb = dest.stat().st_size // 1024
            print(f"  ok     {p.name} -> {dest}  {kb} KB  [{time.time()-t0:.1f}s]")
        except urllib.error.HTTPError as e:
            print(f"  FAILED {p.name}: HTTP {e.code} {e.read().decode()[:200]}")
        except Exception as e:
            print(f"  FAILED {p.name}: {e}")

    print("\nNow swap the CSS objects for the cut-outs in demo/index.html:")
    print('  ART.pop = \'<img src="img/chupa.png" alt="">\'   (etc.)')
    print("and drop the .art--* gradient rules.")


if __name__ == "__main__":
    main()
