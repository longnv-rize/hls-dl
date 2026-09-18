#!/usr/bin/env python3
"""Tai video HLS (.m3u8 -> cac manh .ts) va ghep lai thanh 1 file mp4 dat dung ten.

Mot video:
    python hls_dl.py "https://site/abc/index.m3u8" -o "Bai 1 - Cung va cau"

Ca khoa hoc (batch):
    python hls_dl.py --manifest manifest.json -d "D:/Videos/Khoa hoc"
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse as urlparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import requests
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from tqdm import tqdm

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)


def enable_utf8_console():
    """Console Windows mac dinh la cp1252 -> in ten bai co dau tieng Viet se
    nem UnicodeEncodeError va chet ca tien trinh. Ep stdout/stderr sang UTF-8."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass  # da bi redirect sang cho khac -> ke


ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
RESERVED = {"CON", "PRN", "AUX", "NUL",
            *(f"COM{i}" for i in range(1, 10)),
            *(f"LPT{i}" for i in range(1, 10))}


# ----------------------------------------------------------------- .env

def load_env(path=None):
    """Doc file .env nam canh script. Khong can thu vien ngoai."""
    path = path or os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    conf = {}
    if not os.path.exists(path):
        return conf
    with open(path, encoding="utf-8-sig") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].lstrip()
            key, sep, val = line.partition("=")
            if not sep:
                continue
            key, val = key.strip(), val.strip()
            if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
                val = val[1:-1]
            if val:
                conf[key] = val
    return conf


ENV = load_env()


def env(key, default=None):
    """Bien moi truong that > .env > mac dinh."""
    return os.environ.get(key) or ENV.get(key) or default


def env_int(key, default):
    try:
        return int(env(key, default))
    except (TypeError, ValueError):
        return default


# ----------------------------------------------------------------- ten file

def safe_name(title: str, maxlen: int = 120) -> str:
    """Bien title cua trang web thanh ten file hop le tren Windows."""
    name = ILLEGAL.sub(" ", str(title))
    name = re.sub(r"\s+", " ", name).strip().rstrip(".")
    if name.upper().split(".")[0] in RESERVED:
        name = "_" + name
    if len(name) > maxlen:
        name = name[:maxlen].rstrip()
    return name or "untitled"


def env_bool(key, default=False):
    val = env(key)
    if val is None:
        return default
    return str(val).strip().lower() in ("1", "true", "yes", "on")


def out_path(outdir, title, index=None, ext=".mp4", series=None):
    """Dung duong dan file tu NAME_TEMPLATE trong .env.

    Ten tap thuong da co san so ("E1. Just an Old Book"), nhung E1/E10/E2 sap xep
    sai trong File Explorer, nen mac dinh van them so thu tu zero-pad o dau.
    """
    template = env("NAME_TEMPLATE") or ("{index:03d} - {title}" if index is not None else "{title}")
    try:
        stem = template.format(index=index or 0,
                               title=safe_name(title),
                               series=safe_name(series or ""))
    except (KeyError, ValueError, IndexError) as exc:
        print(f"  NAME_TEMPLATE loi ({exc}) - dung ten goc", file=sys.stderr)
        stem = safe_name(title)

    if series and env_bool("GROUP_BY_SERIES", True):
        outdir = os.path.join(outdir, safe_name(series))
    return os.path.join(outdir, safe_name(stem) + ext)


# ----------------------------------------------------------------- m3u8

@dataclass
class Key:
    method: str
    uri: str
    iv: bytes | None
    _data: bytes | None = field(default=None, repr=False)

    def material(self, sess: requests.Session) -> bytes:
        if self._data is None:
            self._data = sess.get(self.uri, timeout=30).content
        return self._data


@dataclass
class Segment:
    url: str
    index: int
    key: Key | None
    byterange: tuple[int, int] | None = None  # (length, offset)


@dataclass
class Playlist:
    segments: list[Segment]
    init: str | None  # #EXT-X-MAP:URI= cho fMP4
    duration: float


def _attrs(line: str) -> dict:
    """Tach ATTR=val,ATTR="val,co,phay" cua the EXT-X."""
    out, buf, in_q = {}, "", False
    for ch in line:
        if ch == '"':
            in_q = not in_q
        if ch == "," and not in_q:
            if "=" in buf:
                k, v = buf.split("=", 1)
                out[k.strip()] = v.strip().strip('"')
            buf = ""
        else:
            buf += ch
    if "=" in buf:
        k, v = buf.split("=", 1)
        out[k.strip()] = v.strip().strip('"')
    return out


def parse(sess: requests.Session, url: str, depth: int = 0) -> Playlist:
    """Doc m3u8. Neu la master playlist thi tu chon variant bitrate cao nhat."""
    if depth > 3:
        raise RuntimeError("m3u8 long nhau qua sau")
    resp = sess.get(url, timeout=30)
    resp.raise_for_status()
    lines = [ln.strip() for ln in resp.text.splitlines() if ln.strip()]

    if any(ln.startswith("#EXT-X-STREAM-INF") for ln in lines):
        best, best_bw = None, -1
        for i, ln in enumerate(lines):
            if not ln.startswith("#EXT-X-STREAM-INF"):
                continue
            bw = int(_attrs(ln.split(":", 1)[1]).get("BANDWIDTH", 0))
            nxt = next((l for l in lines[i + 1:] if not l.startswith("#")), None)
            if nxt and bw > best_bw:
                best, best_bw = nxt, bw
        if not best:
            raise RuntimeError("master playlist khong co variant nao")
        print(f"  master playlist -> chon variant {best_bw // 1000} kbps")
        return parse(sess, urlparse.urljoin(url, best), depth + 1)

    segments = []
    key = None
    init = None
    total = 0.0
    pending_range = None
    next_offset = 0

    for ln in lines:
        if ln.startswith("#EXT-X-KEY"):
            a = _attrs(ln.split(":", 1)[1])
            method = a.get("METHOD", "NONE")
            if method == "NONE":
                key = None
            else:
                iv = None
                raw_iv = a.get("IV")
                if raw_iv:
                    iv = bytes.fromhex(raw_iv[2:] if raw_iv.lower().startswith("0x") else raw_iv)
                key = Key(method, urlparse.urljoin(url, a.get("URI", "")), iv)
        elif ln.startswith("#EXT-X-MAP"):
            init = urlparse.urljoin(url, _attrs(ln.split(":", 1)[1]).get("URI", ""))
        elif ln.startswith("#EXTINF"):
            try:
                total += float(ln.split(":", 1)[1].split(",")[0])
            except ValueError:
                pass
        elif ln.startswith("#EXT-X-BYTERANGE"):
            length, _, off = ln.split(":", 1)[1].partition("@")
            pending_range = (int(length), int(off) if off else next_offset)
        elif not ln.startswith("#"):
            segments.append(Segment(urlparse.urljoin(url, ln), len(segments), key, pending_range))
            if pending_range:
                next_offset = pending_range[1] + pending_range[0]
            pending_range = None

    if not segments:
        raise RuntimeError("khong tim thay manh .ts nao trong playlist")
    return Playlist(segments, init, total)


# ----------------------------------------------------------------- tai

def decrypt(data: bytes, key: Key, sess: requests.Session, seq: int) -> bytes:
    if key.method != "AES-128":
        raise RuntimeError(f"chua ho tro ma hoa {key.method} (co the la DRM Widevine)")
    iv = key.iv or seq.to_bytes(16, "big")
    dec = Cipher(algorithms.AES(key.material(sess)), modes.CBC(iv)).decryptor()
    plain = dec.update(data) + dec.finalize()
    pad = plain[-1] if plain else 0  # PKCS7
    return plain[:-pad] if 0 < pad <= 16 else plain


def grab(sess: requests.Session, seg: Segment, dest: str, retries: int) -> None:
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        return  # resume: manh nay tai xong tu lan truoc
    headers = {}
    if seg.byterange:
        length, offset = seg.byterange
        headers["Range"] = f"bytes={offset}-{offset + length - 1}"
    last = None
    for attempt in range(retries):
        try:
            r = sess.get(seg.url, timeout=60, headers=headers)
            r.raise_for_status()
            data = r.content
            if not data:
                raise RuntimeError("manh rong")
            if seg.key:
                data = decrypt(data, seg.key, sess, seg.index)
            tmp = dest + ".part"
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, dest)
            return
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(min(2 ** attempt, 15))
    raise RuntimeError(f"manh #{seg.index} that bai sau {retries} lan: {last}")


def merge(parts, init, target, workdir=None):
    """Noi cac manh roi remux sang mp4 (copy stream - nhanh, khong giam chat luong).

    File noi tam (blob) phai nam o o dia noi bo, KHONG duoc de canh file dich.
    Neu dich la thu muc Google Drive / OneDrive thi de canh dich se thanh: ghi
    ~110MB blob len mang, ffmpeg doc nguoc lai tu mang, roi ghi tiep file mp4.
    Gap ba luot truyen thay vi mot.
    """
    blob = os.path.join(workdir or os.path.dirname(os.path.abspath(target)),
                        os.path.basename(target) + ".merged")
    with open(blob, "wb") as out:
        for src in ([init] if init else []) + parts:
            with open(src, "rb") as f:
                shutil.copyfileobj(f, out)
    base = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", blob,
            "-c", "copy", "-movflags", "+faststart"]
    if subprocess.run(base + ["-bsf:a", "aac_adtstoasc", target]).returncode != 0:
        # audio khong phai AAC/ADTS -> bo bitstream filter
        subprocess.run(base + [target], check=True)
    os.remove(blob)


def probe_duration(path):
    """Doc thoi luong thuc te cua file bang ffprobe. None = khong doc duoc."""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", path],
            capture_output=True, text=True, timeout=60)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    try:
        return float(r.stdout.strip())
    except ValueError:
        return None


def verify(target, mong_doi):
    """So thoi luong file vua ghep voi tong #EXTINF trong playlist.

    Ly do can: mot lan tai co the 'thanh cong' theo moi dau hieu - exit code 0,
    khong dong loi nao, log bao da ghi file - ma ket qua van sai. Playlist da
    noi truoc phim dai bao nhieu, nen doi chieu lai la cach re nhat de loi khong
    di qua trong im lang.

    Tra ve chuoi canh bao neu lech vua phai, nem loi neu lech nghiem trong.
    """
    if not env_bool("VERIFY_OUTPUT", True) or not mong_doi:
        return None
    thuc = probe_duration(target)
    if thuc is None:
        raise RuntimeError("ffprobe khong doc duoc file vua ghep - file hong")

    lech = abs(thuc - mong_doi)
    nang = max(10.0, mong_doi * 0.05)
    nhe = max(3.0, mong_doi * 0.01)
    mota = (f"dai {thuc:.0f}s nhung playlist noi {mong_doi:.0f}s "
            f"(lech {lech:.0f}s)")
    if lech > nang:
        raise RuntimeError(f"file ghep ra sai nhieu: {mota}")
    if lech > nhe:
        print(f"  ! canh bao: {mota}", file=sys.stderr)
        return mota
    return None


def download(url, target, sess, workers=8, retries=5, keep=False):
    if os.path.exists(target) and os.path.getsize(target) > 0:
        print(f"  bo qua (da co): {os.path.basename(target)}")
        return target
    os.makedirs(os.path.dirname(os.path.abspath(target)), exist_ok=True)

    pl = parse(sess, url)
    work = os.path.join(tempfile.gettempdir(), "hls-dl",
                        safe_name(os.path.splitext(os.path.basename(target))[0], 60))
    os.makedirs(work, exist_ok=True)

    init_file = None
    if pl.init:
        init_file = os.path.join(work, "init.mp4")
        grab(sess, Segment(pl.init, -1, None), init_file, retries)

    parts = [os.path.join(work, f"{s.index:06d}.seg") for s in pl.segments]
    print(f"  {len(pl.segments)} manh, ~{int(pl.duration // 60)}m{int(pl.duration % 60):02d}s"
          + (" [AES-128]" if pl.segments[0].key else ""))

    errors = []
    with tqdm(total=len(pl.segments), unit="seg", leave=False) as bar:
        def task(pair):
            seg, dest = pair
            try:
                grab(sess, seg, dest, retries)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)
            bar.update(1)

        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(task, zip(pl.segments, parts)))

    if errors:
        for e in errors[:5]:
            print(f"  ! {e}", file=sys.stderr)
        raise RuntimeError(f"{len(errors)}/{len(pl.segments)} manh loi - chay lai de resume")

    merge(parts, init_file, target, work)
    try:
        canh_bao = verify(target, pl.duration)
    except Exception:
        # giu lai manh de con chay lai duoc, va xoa file hong di
        if os.path.exists(target):
            os.remove(target)
        raise
    if not keep:
        shutil.rmtree(work, ignore_errors=True)
    print(f"  -> {os.path.basename(target)} ({os.path.getsize(target) / 1048576:.1f} MB)"
          + ("  [CO CANH BAO]" if canh_bao else ""))
    return target


# ----------------------------------------------------------------- upload

DONE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "done.txt")


def already_done(name):
    """Da tai + day len cloud xong tu lan truoc chua?

    Khi bat upload thi file local bi xoa, nen khong the dua vao 'file co ton tai'
    de biet da xong hay chua. Phai ghi so rieng, khong thi chay lai se tai lai het.
    """
    try:
        with open(DONE_FILE, encoding="utf-8") as f:
            return name in {ln.strip() for ln in f if ln.strip()}
    except FileNotFoundError:
        return False


def mark_done(name):
    with open(DONE_FILE, "a", encoding="utf-8") as f:
        f.write(name + "\n")


def upload(path):
    """Day file len cloud roi xoa ban local.

    Tra ve True neu da day xong, False neu that bai, None neu khong bat upload.
    Dung 'rclone moveto': no chi xoa ban local SAU KHI xac nhan day len thanh cong,
    nen khong co canh mat file vi upload dut giua chung.
    """
    remote = env("UPLOAD_TO")
    custom = env("UPLOAD_CMD")
    if not remote and not custom:
        return None

    name = os.path.basename(path)
    if custom:
        cmd = custom.replace("{file}", path).replace("{name}", name)
        ok = subprocess.run(cmd, shell=True).returncode == 0
    else:
        cmd = ["rclone", "moveto", path, f"{remote}:{name}",
               "--progress", "--stats-one-line"]
        folder = env("DRIVE_FOLDER_ID")
        if folder:
            # bien thu muc nay thanh goc cua remote -> file roi dung vao day
            cmd += ["--drive-root-folder-id", folder]
        try:
            ok = subprocess.run(cmd).returncode == 0
        except FileNotFoundError:
            print("  ! chua cai rclone - giu ban local, bo qua upload", file=sys.stderr)
            return False

    if ok:
        print(f"  -> da day len {remote or 'cloud'}, xoa ban local")
    else:
        print(f"  ! upload that bai - GIU lai ban local: {name}", file=sys.stderr)
    return ok


# ----------------------------------------------------------------- cli

def make_session(headers, referer, cookie):
    s = requests.Session()
    s.headers.update({"User-Agent": DEFAULT_UA, "Accept": "*/*"})
    if referer:
        p = urlparse.urlparse(referer)
        s.headers["Referer"] = referer
        s.headers["Origin"] = f"{p.scheme}://{p.netloc}"
    if cookie:
        s.headers["Cookie"] = cookie
    for h in headers or []:
        k, _, v = h.partition(":")
        s.headers[k.strip()] = v.strip()
    return s


def main():
    enable_utf8_console()
    ap = argparse.ArgumentParser(
        description="Tai video HLS va dat dung ten theo title. "
                    "Mac dinh doc tu file .env, tham so dong lenh de ghi de.")
    ap.add_argument("url", nargs="?", help="URL file .m3u8")
    ap.add_argument("-o", "--title", help="Ten video (dung lam ten file)")
    ap.add_argument("-d", "--outdir", default=env("OUTPUT_DIR", "."), help="Thu muc luu")
    ap.add_argument("-m", "--manifest", default=env("MANIFEST"),
                    help="File JSON: [{index,title,url}, ...]")
    ap.add_argument("-H", "--header", action="append", help='Them header, vd -H "X-Token: abc"')
    ap.add_argument("-r", "--referer", default=env("REFERER") or env("COURSE_URL") or env("SITE_URL"),
                    help="Referer (nhieu site bat buoc)")
    ap.add_argument("-c", "--cookie", default=env("COOKIE"), help="Cookie header day du")
    ap.add_argument("-j", "--workers", type=int, default=env_int("WORKERS", 8),
                    help="So manh tai song song")
    ap.add_argument("--retries", type=int, default=env_int("RETRIES", 5))
    ap.add_argument("--keep", action="store_true", help="Giu lai cac manh sau khi ghep")
    args = ap.parse_args()

    headers = list(args.header or [])
    if env("AUTH_HEADER"):
        headers.append(env("AUTH_HEADER"))

    sess = make_session(headers, args.referer, args.cookie)
    os.makedirs(args.outdir, exist_ok=True)

    # co URL cu the -> tai mot video, bo qua MANIFEST mac dinh trong .env
    if args.manifest and not args.url:
        if not os.path.exists(args.manifest):
            ap.error(f"khong thay manifest '{args.manifest}'. "
                     "Chay grab.js / auto_grab.js de tao truoc.")
        with open(args.manifest, encoding="utf-8") as f:
            items = json.load(f)
        if isinstance(items, dict):
            items = items.get("videos", [])

        # Mot muc le co the mang series sai (vd trang viet "EP-36" lam ham cat ten
        # tap o grab.js truot, ca cum thanh ten tac pham). Neu de nguyen thi tap do
        # bi nem sang mot thu muc rieng va trong nhu bi mat. Lay gia tri pho bien
        # nhat lam chuan - ca manifest von chi la mot tac pham.
        ten = [it.get("series") for it in items if it.get("series")]
        chuan = Counter(ten).most_common(1)[0][0] if ten else None
        lech = {it.get("series") for it in items if it.get("series") and it["series"] != chuan}
        if lech:
            print(f"  (bo qua {len(lech)} ten tac pham lech, dung {chuan!r}: {sorted(lech)})")

        failed = []
        for i, it in enumerate(items, 1):
            title = it.get("title") or f"video-{i}"
            series = env("SERIES_NAME") or chuan or it.get("series")
            target = out_path(args.outdir, title, it.get("index", i), series=series)
            name = os.path.basename(target)
            print(f"[{i}/{len(items)}] {title}")

            if already_done(name):
                print(f"  bo qua (da tai + day len cloud tu truoc)")
                continue
            try:
                download(it["url"], target, sess, args.workers, args.retries, args.keep)
                # CHI ghi so khi da day len cloud that su. Khong bat upload thi
                # file con nam tren dia, de viec kiem tra "file da ton tai" lo -
                # ghi so luc nay se khien lan sau bat upload len bi bo qua het,
                # va khong tap nao duoc day len ca.
                if upload(target) is True:
                    mark_done(name)
            except Exception as exc:  # noqa: BLE001
                print(f"  LOI: {exc}", file=sys.stderr)
                # giu ca nguyen nhan - biet ten tap ma khong biet vi sao
                # thi bao cao cuoi cung khong dung duoc vao viec gi
                failed.append((title, str(exc)))
        if failed:
            print(f"\n{len(failed)} video that bai:")
            for ten, vi_sao in failed:
                print(f"  - {ten}\n      {vi_sao}")
            return 1
        print("\nXong tat ca.")
        return 0

    if not args.url:
        ap.error("can URL .m3u8 hoac --manifest")
    print(args.title or "video")
    try:
        download(args.url, out_path(args.outdir, args.title or "video"),
                 sess, args.workers, args.retries, args.keep)
    except Exception as exc:  # noqa: BLE001
        # nem nguyen stack trace ra man hinh thi nguoi dung khong phan biet duoc
        # day la loi that hay bug cua cong cu
        print(f"\nLOI: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
