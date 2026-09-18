#!/usr/bin/env python3
"""Ghep cac manh .ts DA CO SAN tren o dia thanh 1 file mp4 dat dung ten.

Dung khi ban da tai ve mot dong manh ten lon xon (seg-1.ts, 0001.ts, hash.ts...).

    python merge_local.py "D:/tai-ve/bai-01" -o "Bai 1 - Cung va cau"
    python merge_local.py "D:/tai-ve/bai-01" -o "Bai 1" --order playlist.m3u8

Thu tu manh la thu quan trong nhat: sai thu tu -> video nhay lung tung.
Mac dinh sap xep tu nhien theo so trong ten file. Neu ten file khong co so
tang dan (vd ten bam hash) thi BAT BUOC dung --order voi file m3u8 goc.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile

from hls_dl import enable_utf8_console, safe_name


def natural_key(path: str):
    """Sap xep 'seg2.ts' truoc 'seg10.ts' (sap xep chu cai se cho ket qua nguoc)."""
    name = os.path.basename(path)
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


def seq_number(path: str):
    """So thu tu manh = so cuoi cung trong ten file (bo qua hash/id o dau)."""
    nums = re.findall(r"\d+", os.path.splitext(os.path.basename(path))[0])
    return int(nums[-1]) if nums else None


def report_gaps(parts):
    """Canh bao neu thieu manh - ghep thieu manh se ra video nhay coc."""
    nums = [seq_number(p) for p in parts]
    if any(n is None for n in nums) or len(set(nums)) != len(nums):
        print("  (ten file khong co so thu tu duy nhat - khong kiem tra duoc do thieu manh)")
        return []
    missing = sorted(set(range(min(nums), max(nums) + 1)) - set(nums))
    if missing:
        show = ", ".join(map(str, missing[:20])) + (" ..." if len(missing) > 20 else "")
        print(f"  CANH BAO: thieu {len(missing)} manh trong khoang "
              f"{min(nums)}-{max(nums)}: {show}")
        print("  Ghep tiep se ra video bi nhay. Nen tai bu cac manh thieu truoc.")
    return missing


def from_playlist(playlist: str, folder: str) -> list[str]:
    """Lay dung thu tu manh tu file .m3u8 goc da luu ve."""
    with open(playlist, encoding="utf-8", errors="replace") as f:
        names = [os.path.basename(ln.strip().split("?")[0])
                 for ln in f if ln.strip() and not ln.startswith("#")]
    out, missing = [], []
    for n in names:
        p = os.path.join(folder, n)
        (out if os.path.exists(p) else missing).append(p if os.path.exists(p) else n)
    if missing:
        raise SystemExit(f"Thieu {len(missing)} manh so voi playlist, vd: {missing[:3]}")
    return out


def main():
    enable_utf8_console()
    ap = argparse.ArgumentParser(description="Ghep cac manh .ts co san thanh mp4")
    ap.add_argument("folder", help="Thu muc chua cac manh")
    ap.add_argument("-o", "--title", required=True, help="Ten video mong muon")
    ap.add_argument("-d", "--outdir", help="Thu muc luu (mac dinh: canh thu muc manh)")
    ap.add_argument("-e", "--ext", default=".ts", help="Duoi file manh (mac dinh .ts)")
    ap.add_argument("--order", help="File .m3u8 goc de lay dung thu tu manh")
    ap.add_argument("--dry-run", action="store_true", help="Chi in thu tu, khong ghep")
    ap.add_argument("--force", action="store_true", help="Van ghep du thieu manh")
    args = ap.parse_args()

    if args.order:
        parts = from_playlist(args.order, args.folder)
    else:
        parts = sorted(
            (os.path.join(args.folder, n) for n in os.listdir(args.folder)
             if n.lower().endswith(args.ext.lower())),
            key=natural_key,
        )
    if not parts:
        raise SystemExit(f"Khong thay file {args.ext} nao trong {args.folder}")

    print(f"{len(parts)} manh, thu tu ghep:")
    head, tail = parts[:3], parts[-3:] if len(parts) > 6 else []
    for p in head:
        print(f"  {os.path.basename(p)}")
    if tail:
        print("  ...")
        for p in tail:
            print(f"  {os.path.basename(p)}")
    missing = report_gaps(parts) if not args.order else []
    if args.dry_run:
        return 0
    if missing and not args.force:
        raise SystemExit("Dung lai. Them --force neu van muon ghep du thieu manh.")

    outdir = args.outdir or args.folder
    os.makedirs(outdir, exist_ok=True)
    target = os.path.join(outdir, safe_name(args.title) + ".mp4")

    # File noi tam de o o dia noi bo, khong de canh dich - dich co the la thu muc
    # Google Drive/OneDrive, de canh do se ghi va doc qua mang mot cach vo ich.
    work = os.path.join(tempfile.gettempdir(), "hls-dl")
    os.makedirs(work, exist_ok=True)
    blob = os.path.join(work, os.path.basename(target) + ".merged")
    with open(blob, "wb") as out:
        for p in parts:
            with open(p, "rb") as f:
                shutil.copyfileobj(f, out)

    base = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", blob,
            "-c", "copy", "-movflags", "+faststart"]
    if subprocess.run(base + ["-bsf:a", "aac_adtstoasc", target]).returncode != 0:
        subprocess.run(base + [target], check=True)
    os.remove(blob)

    print(f"-> {target} ({os.path.getsize(target) / 1048576:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
