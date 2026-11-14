#!/usr/bin/env python3
"""Find, survey and download printable models from Printables.com through its public GraphQL API — no browser, so no
Chrome "Save as" dialogs blocking the download. Standard library + Pillow (contact sheet only).

  printables.py search "sleeping cat" [--limit 12]          id, likes, downloads, licence, name
  printables.py info MODEL_ID                               name, author, licence, every file with id and size
  printables.py sheet MODEL_ID [MODEL_ID ...] --out survey.png [--per 3]
                                                            contact sheet of each model's photos, to judge realism
  printables.py fetch MODEL_ID --out DIR [--match cat] [--every 3] [--max 12] [--ledger SOURCES-and-licenses.csv]
                                                            download STL/3MF/OBJ files, append author + licence

The API is what printables.com's own pages call (api.printables.com/graphql/); it is unofficial and can change.
If a query starts failing with "Cannot query field", open a model page in the browser pane and read the network
requests to see the current field names.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import urllib.request
from io import BytesIO
from pathlib import Path

API = "https://api.printables.com/graphql/"
HEADERS = {"content-type": "application/json", "origin": "https://www.printables.com", "referer": "https://www.printables.com/",
           "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0 Safari/537.36"}
SEARCH_Q = ("query SearchModels($query: String!, $limit: Int) { result: searchPrints2(query: $query, limit: $limit) "
            "{ items { id name likesCount downloadCount license { name } user { publicUsername } } } }")
MODEL_Q = ("query Model($id: ID!) { model: print(id: $id) { id name license { name } user { publicUsername } "
           "stls { id name fileSize } images { filePath } } }")
LINK_Q = ("mutation GetDownloadLink($id: ID!, $modelId: ID!, $fileType: DownloadFileTypeEnum!, $source: DownloadSourceEnum!) "
          "{ getDownloadLink(id: $id, printId: $modelId, fileType: $fileType, source: $source) "
          "{ ok errors { field messages code } output { link count ttl } } }")


def gql(op: str, query: str, variables: dict) -> dict:
    req = urllib.request.Request(API, method="POST", headers=HEADERS,
                                 data=json.dumps({"operationName": op, "variables": variables, "query": query}).encode())
    with urllib.request.urlopen(req, timeout=30) as r:
        out = json.loads(r.read())
    if out.get("errors"):
        raise RuntimeError(out["errors"])
    return out["data"]


def model(model_id: str) -> dict:
    data = gql("Model", MODEL_Q, {"id": str(model_id)})["model"]
    if not data:
        raise SystemExit(f"model {model_id} not found")
    return data


def download_link(model_id: str, file_id: str, file_type: str = "stl") -> str:
    out = gql("GetDownloadLink", LINK_Q, {"id": file_id, "modelId": str(model_id), "fileType": file_type,
                                           "source": "model_detail"})["getDownloadLink"]
    if not out["ok"]:
        raise RuntimeError(out["errors"])
    return out["output"]["link"]


def fetch_bytes(url: str, timeout: int = 300) -> bytes:
    return urllib.request.urlopen(urllib.request.Request(url, headers={"user-agent": HEADERS["user-agent"]}),
                                  timeout=timeout).read()


def cmd_search(args):
    for m in gql("SearchModels", SEARCH_Q, {"query": args.query, "limit": args.limit})["result"]["items"]:
        lic = (m.get("license") or {}).get("name", "?")
        print(f"{m['id']:>8}  likes {m['likesCount']:>5}  dl {m['downloadCount']:>6}  {lic[:40]:40}  {m['name']}")


def cmd_info(args):
    m = model(args.model_id)
    print(f"{m['name']} | by {m['user']['publicUsername']} | {(m.get('license') or {}).get('name', '?')}")
    print(f"https://www.printables.com/model/{m['id']}")
    for s in m["stls"] or []:
        print(f"  file {s['id']:>9}  {s['fileSize'] / 1e6:7.1f} MB  {s['name']}")


def cmd_sheet(args):
    from PIL import Image, ImageDraw
    tiles = []
    for mid in args.model_ids:
        m = model(mid)
        for k, im in enumerate((m.get("images") or [])[:args.per]):
            img = Image.open(BytesIO(fetch_bytes("https://media.printables.com/" + im["filePath"], 30))).convert("RGB")
            img.thumbnail((360, 360))
            tiles.append((f"{mid} #{k + 1} {m['name'][:30]}", img))
    cols = max(1, args.per)
    sheet = Image.new("RGB", (cols * 360, max(1, (len(tiles) + cols - 1) // cols) * 390), "white")
    for i, (label, img) in enumerate(tiles):
        x, y = (i % cols) * 360, (i // cols) * 390
        sheet.paste(img, (x + (360 - img.width) // 2, y))
        ImageDraw.Draw(sheet).text((x + 5, y + 365), label, fill=(0, 0, 0))
    sheet.save(args.out)
    print(args.out, f"{len(tiles)} photos")


def cmd_fetch(args):
    m = model(args.model_id)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    files = sorted(m["stls"] or [], key=lambda s: s["name"])
    if args.match:
        files = [s for s in files if args.match.lower() in s["name"].lower()]
    files = files[::args.every][:args.max]
    for s in files:
        dest = out / s["name"]
        if dest.exists():
            print("have", dest.name)
            continue
        dest.write_bytes(fetch_bytes(download_link(args.model_id, s["id"])))
        print("got", dest.name, f"{dest.stat().st_size / 1e6:.1f} MB")
    if args.ledger:
        ledger = Path(args.ledger)
        rows = list(csv.DictReader(ledger.open())) if ledger.exists() else []
        source = f"https://www.printables.com/model/{m['id']}"
        if not any(r.get("source") == source for r in rows):
            rows.append({"file": f"{out.name}/" + (files[0]["name"] if len(files) == 1 else "*"), "model": m["name"],
                         "author": m["user"]["publicUsername"],
                         "license": (m.get("license") or {}).get("name", "?"), "source": source})
            with ledger.open("w", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=["file", "model", "author", "license", "source"])
                writer.writeheader()
                writer.writerows(rows)
            print("ledger +1:", ledger)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("search"); p.add_argument("query"); p.add_argument("--limit", type=int, default=12)
    p = sub.add_parser("info"); p.add_argument("model_id")
    p = sub.add_parser("sheet"); p.add_argument("model_ids", nargs="+"); p.add_argument("--out", required=True)
    p.add_argument("--per", type=int, default=3)
    p = sub.add_parser("fetch"); p.add_argument("model_id"); p.add_argument("--out", required=True)
    p.add_argument("--match", default=""); p.add_argument("--every", type=int, default=1)
    p.add_argument("--max", type=int, default=50); p.add_argument("--ledger")
    args = ap.parse_args(argv)
    {"search": cmd_search, "info": cmd_info, "sheet": cmd_sheet, "fetch": cmd_fetch}[args.cmd](args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
