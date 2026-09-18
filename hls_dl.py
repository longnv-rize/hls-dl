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


def gioi_han_duong_dan():
    """Do dai toi da cua ca duong dan dich.

    Windows chet o 260 ky tu neu chua bat long path, va do la mac dinh tren
    phan lon may. Chua 250 de con cho cho cac hau to tam. Cac he khac rong
    hon nhieu nen khong can that chat.
    """
    return env_int("MAX_PATH_LEN", 250 if os.name == "nt" else 4000)


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

    stem = safe_name(stem)
    duong_dan = os.path.join(outdir, stem + ext)

    # safe_name moi cat TUNG PHAN o 120 ky tu; tong ca duong dan van co the
    # vuot gioi han cua he thong. Cat bot tu CUOI ten, giu nguyen tien to so
    # thu tu o dau: mat vai chu cuoi ten tap thi van biet la tap nao, con mat
    # so thu tu thi hong ca thu tu sap xep lan viec phan biet cac tap voi nhau.
    gioi_han = gioi_han_duong_dan()
    thua = len(os.path.abspath(duong_dan)) - gioi_han
    if thua <= 0:
        return duong_dan

    cho_phep = len(stem) - thua
    if cho_phep < 8:
        raise RuntimeError(
            f"duong dan dich dai {len(os.path.abspath(duong_dan))} ky tu,"
            f" qua gioi han {gioi_han} - hay chon OUTPUT_DIR ngan hon")
    print(f"  ! ten file bi cat bot cho vua gioi han {gioi_han} ky tu",
          file=sys.stderr)
    return os.path.join(outdir, safe_name(stem[:cho_phep]) + ext)


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
    # DASH thuong tach hinh va tieng thanh hai luong rieng, phai tai ca hai roi
    # ghep lai. HLS thi tieng nam san trong .ts nen truong nay de None.
    audio: "Playlist | None" = None
    # mo ta nguon de in ra cho de doi chieu: "HLS", "DASH", "file"
    kind: str = "HLS"


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
        # HLS cung co the tach tieng ra luong rieng giong DASH. Khong xu ly thi
        # variant chi-co-hinh se cho ra video CAM - ma kiem thoi luong van dung,
        # nen loi di qua hoan toan im lang.
        tieng = {}
        for ln in lines:
            if not ln.startswith("#EXT-X-MEDIA"):
                continue
            a = _attrs(ln.split(":", 1)[1])
            if a.get("TYPE") != "AUDIO" or not a.get("URI"):
                continue
            nhom = a.get("GROUP-ID", "")
            if nhom not in tieng or a.get("DEFAULT", "").upper() == "YES":
                tieng[nhom] = a["URI"]

        best, best_bw, best_a = None, -1, {}
        for i, ln in enumerate(lines):
            if not ln.startswith("#EXT-X-STREAM-INF"):
                continue
            a = _attrs(ln.split(":", 1)[1])
            bw = int(a.get("BANDWIDTH", 0))
            nxt = next((l for l in lines[i + 1:] if not l.startswith("#")), None)
            if nxt and bw > best_bw:
                best, best_bw, best_a = nxt, bw, a
        if not best:
            raise RuntimeError("master playlist khong co variant nao")
        print(f"  master playlist -> chon variant {best_bw // 1000} kbps")
        pl = parse(sess, urlparse.urljoin(url, best), depth + 1)

        # Chi ghep them tieng khi variant that su KHONG co san tieng ben trong.
        # CODECS co mp4a/ac-3/... nghia la tieng da nam chung trong manh roi;
        # ghep them nua se thanh hai luong tieng chong nhau.
        nhom = best_a.get("AUDIO")
        co_san = bool(re.search(r"mp4a|ac-3|ec-3|opus|vorbis|dts", best_a.get("CODECS", ""), re.I))
        if nhom and nhom in tieng and not co_san:
            print(f"  tieng tach rieng (nhom {nhom}) -> tai them")
            pl.audio = parse(sess, urlparse.urljoin(url, tieng[nhom]), depth + 1)
        return pl

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

    # Khong co #EXT-X-ENDLIST = playlist con dang duoc noi dai (phat truc tiep).
    # Tai duoc, nhung chi duoc doan dang co tai thoi diem nay, nen phai noi ro.
    if not any(ln.startswith("#EXT-X-ENDLIST") for ln in lines):
        print("  ! playlist khong co ENDLIST - co ve la phat truc tiep,"
              " chi lay duoc doan hien co", file=sys.stderr)

    return Playlist(segments, init, total)


# ----------------------------------------------------------------- DASH (.mpd)

DASH_NS = "{urn:mpeg:dash:schema:mpd:2011}"


def iso_duration(s):
    """PT10M47.5S -> 647.5 giay. Tra ve 0 neu khong doc duoc."""
    m = re.match(r"^P(?:\d+D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:([\d.]+)S)?$", (s or "").strip())
    if not m:
        return 0.0
    gio, phut, giay = m.groups()
    return int(gio or 0) * 3600 + int(phut or 0) * 60 + float(giay or 0)


def _fill(tpl, rep_id, bandwidth, number=None, time=None):
    """Thay $Number$, $Time$, $RepresentationID$... trong mau URL cua DASH.

    Ho tro ca dang co dinh dang nhu $Number%05d$ -> 00042.
    """
    def thay(m):
        ten, dinh_dang = m.group(1), m.group(2)
        gia_tri = {"RepresentationID": rep_id, "Bandwidth": bandwidth,
                   "Number": number, "Time": time}.get(ten)
        if gia_tri is None:
            return m.group(0)
        return (dinh_dang % int(gia_tri)) if dinh_dang else str(gia_tri)

    ra = re.sub(r"\$(RepresentationID|Bandwidth|Number|Time)(%0\d+d)?\$", thay, tpl)
    return ra.replace("$$", "$")


def _base_url(nodes, goc):
    """Noi chuoi BaseURL tu MPD -> Period -> AdaptationSet -> Representation."""
    url = goc
    for n in nodes:
        b = n.find(DASH_NS + "BaseURL")
        if b is not None and (b.text or "").strip():
            url = urlparse.urljoin(url, b.text.strip())
    return url


def _segments_of(rep, aset, goc, tong_giay):
    """Dung danh sach URL cac manh cho mot Representation."""
    base = _base_url([rep], goc)
    rep_id = rep.get("id", "")
    bw = rep.get("bandwidth", "0")

    tpl = rep.find(DASH_NS + "SegmentTemplate")
    if tpl is None:
        tpl = aset.find(DASH_NS + "SegmentTemplate")

    if tpl is not None:
        init = None
        if tpl.get("initialization"):
            init = urlparse.urljoin(base, _fill(tpl.get("initialization"), rep_id, bw))
        media = tpl.get("media", "")
        so_dau = int(tpl.get("startNumber", 1))
        thang = float(tpl.get("timescale", 1)) or 1.0

        urls = []
        dong_ho = tpl.find(DASH_NS + "SegmentTimeline")
        if dong_ho is not None:
            # SegmentTimeline: moi <S> co the lap lai r lan
            n, t = so_dau, 0
            for s in dong_ho.findall(DASH_NS + "S"):
                if s.get("t") is not None:
                    t = int(s.get("t"))
                d = int(s.get("d", 0))
                for _ in range(int(s.get("r", 0)) + 1):
                    urls.append(urlparse.urljoin(base, _fill(media, rep_id, bw, n, t)))
                    n += 1
                    t += d
        elif tpl.get("duration"):
            moi_manh = int(tpl.get("duration")) / thang
            if moi_manh <= 0:
                raise RuntimeError("SegmentTemplate co duration = 0")
            import math
            so_manh = max(1, math.ceil(tong_giay / moi_manh))
            for i in range(so_manh):
                urls.append(urlparse.urljoin(base, _fill(media, rep_id, bw, so_dau + i)))
        else:
            raise RuntimeError("SegmentTemplate khong co SegmentTimeline lan duration")
        return urls, init

    ds = rep.find(DASH_NS + "SegmentList")
    if ds is not None:
        init = None
        i = ds.find(DASH_NS + "Initialization")
        if i is not None and i.get("sourceURL"):
            init = urlparse.urljoin(base, i.get("sourceURL"))
        urls = [urlparse.urljoin(base, u.get("media"))
                for u in ds.findall(DASH_NS + "SegmentURL") if u.get("media")]
        return urls, init

    # Khong co template lan list -> ca Representation la mot file don
    return [base], None


def parse_dash(sess, url):
    """Doc file .mpd. Chon Representation bitrate cao nhat cho ca hinh va tieng."""
    import xml.etree.ElementTree as ET
    resp = sess.get(url, timeout=30)
    resp.raise_for_status()
    goc = ET.fromstring(resp.text)

    tong = iso_duration(goc.get("mediaPresentationDuration"))
    period = goc.find(DASH_NS + "Period")
    if period is None:
        raise RuntimeError("file .mpd khong co Period nao")
    if not tong:
        tong = iso_duration(period.get("duration"))

    base = _base_url([goc, period], url)

    def chon(loai):
        """Lay Representation bitrate cao nhat trong cac AdaptationSet dung loai."""
        tot, tot_bw, tot_set = None, -1, None
        for aset in period.findall(DASH_NS + "AdaptationSet"):
            kieu = (aset.get("contentType") or aset.get("mimeType") or "")
            reps = aset.findall(DASH_NS + "Representation")
            if loai not in kieu:
                # co MPD khong ghi kieu o AdaptationSet ma o Representation
                if not any(loai in (r.get("mimeType") or "") for r in reps):
                    continue
            for r in reps:
                bw = int(r.get("bandwidth", 0))
                if bw > tot_bw:
                    tot, tot_bw, tot_set = r, bw, aset
        return tot, tot_set, tot_bw

    v, v_set, v_bw = chon("video")
    if v is None:
        raise RuntimeError("file .mpd khong co luong video nao")
    print(f"  DASH -> chon video {v_bw // 1000} kbps")
    v_urls, v_init = _segments_of(v, v_set, base, tong)
    hinh = Playlist([Segment(u, i, None) for i, u in enumerate(v_urls)],
                    v_init, tong, kind="DASH")

    a, a_set, a_bw = chon("audio")
    if a is not None and a is not v:
        print(f"  DASH -> chon tieng {a_bw // 1000} kbps")
        a_urls, a_init = _segments_of(a, a_set, base, tong)
        hinh.audio = Playlist([Segment(u, i, None) for i, u in enumerate(a_urls)],
                              a_init, tong, kind="DASH")
    return hinh


def parse_direct(url, tong=0.0):
    """File video tai thang (mp4/mkv/webm), khong chia manh."""
    return Playlist([Segment(url, 0, None)], None, tong, kind="file")


def parse_source(sess, url):
    """Nhan dien nguon roi giao cho bo doc tuong ung: HLS, DASH hay file don."""
    duoi = url.split("?")[0].lower()
    if duoi.endswith(".mpd"):
        return parse_dash(sess, url)
    if duoi.endswith(".m3u8"):
        return parse(sess, url)
    if re.search(r"\.(mp4|mkv|webm|mov|m4v)$", duoi):
        return parse_direct(url)

    # Khong doan duoc tu duoi file thi hoi server xem no tra ve kieu gi
    try:
        r = sess.head(url, timeout=20, allow_redirects=True)
        ct = (r.headers.get("content-type") or "").lower()
    except Exception:  # noqa: BLE001
        ct = ""
    if "mpegurl" in ct:
        return parse(sess, url)
    if "dash+xml" in ct:
        return parse_dash(sess, url)
    if ct.startswith("video/") or ct.startswith("audio/"):
        return parse_direct(url)
    # cuoi cung van cu thu doc nhu HLS, no se bao loi ro neu khong phai
    return parse(sess, url)


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


def fetch_track(sess, pl, work, ten, workers, retries):
    """Tai het cac manh cua MOT luong (hinh hoac tieng). Tra ve (list manh, init)."""
    init_file = None
    if pl.init:
        init_file = os.path.join(work, f"{ten}-init.mp4")
        grab(sess, Segment(pl.init, -1, None), init_file, retries)

    parts = [os.path.join(work, f"{ten}-{s.index:06d}.seg") for s in pl.segments]
    errors = []
    with tqdm(total=len(pl.segments), unit="seg", desc=ten, leave=False) as bar:
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
    return parts, init_file


def _noi(parts, init, dest):
    """Noi init + cac manh thanh mot file lien."""
    with open(dest, "wb") as out:
        for src in ([init] if init else []) + parts:
            with open(src, "rb") as f:
                shutil.copyfileobj(f, out)
    return dest


def merge(parts, init, target, workdir=None, a_parts=None, a_init=None):
    """Noi cac manh roi remux sang mp4 (copy stream - nhanh, khong giam chat luong).

    File noi tam (blob) phai nam o o dia noi bo, KHONG duoc de canh file dich.
    Neu dich la thu muc Google Drive / OneDrive thi de canh dich se thanh: ghi
    ~110MB blob len mang, ffmpeg doc nguoc lai tu mang, roi ghi tiep file mp4.
    Gap ba luot truyen thay vi mot.
    """
    noi = workdir or os.path.dirname(os.path.abspath(target))
    ten = os.path.basename(target)
    blob = _noi(parts, init, os.path.join(noi, ten + ".v.merged"))
    tam = [blob]

    vao = ["-i", blob]
    dat = []
    if a_parts:
        # DASH tach hinh va tieng -> phai dua ffmpeg hai file nguon roi ghep lai
        ablob = _noi(a_parts, a_init, os.path.join(noi, ten + ".a.merged"))
        tam.append(ablob)
        vao += ["-i", ablob]
        dat = ["-map", "0:v:0", "-map", "1:a:0"]

    base = (["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"] + vao
            + dat + ["-c", "copy", "-movflags", "+faststart"])
    if subprocess.run(base + ["-bsf:a", "aac_adtstoasc", target]).returncode != 0:
        # audio khong phai AAC/ADTS -> bo bitstream filter
        subprocess.run(base + [target], check=True)
    for f in tam:
        os.remove(f)


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


def co_luong_tieng(path):
    """File co luong tieng nao khong. None = khong hoi duoc ffprobe."""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a",
             "-show_entries", "stream=codec_type", "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=60)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    return bool(r.stdout.strip())


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

    # Kiem thoi luong TRUOC, vi no la cai duy nhat co the nem loi. Dat phep
    # kiem tieng len truoc thi mot file vua cam tieng vua cut mot nua se chi
    # bao cam tieng roi thoat, khong bao gio ném loi cut.
    canh_bao = []
    lech = abs(thuc - mong_doi)
    nang = max(10.0, mong_doi * 0.05)
    nhe = max(3.0, mong_doi * 0.01)
    mota = (f"dai {thuc:.0f}s nhung playlist noi {mong_doi:.0f}s "
            f"(lech {lech:.0f}s)")
    if lech > nang:
        raise RuntimeError(f"file ghep ra sai nhieu: {mota}")
    if lech > nhe:
        canh_bao.append(mota)

    # Luoi an toan cho tieng: bat MOI nguyen nhan lam video cam, khong chi
    # rieng cai da vá. Thoi luong dung ma khong co tieng thi phep kiem thoi
    # luong khong bao gio phat hien duoc.
    if env_bool("VERIFY_AUDIO", True) and co_luong_tieng(target) is False:
        canh_bao.append("file khong co luong tieng nao"
                        " - co the playlist tach tieng ra rieng")

    for c in canh_bao:
        print(f"  ! canh bao: {c}", file=sys.stderr)
    return "; ".join(canh_bao) if canh_bao else None


def dung_ytdlp():
    return env("ENGINE", "").strip().lower().replace("_", "-") == "yt-dlp"


def lenh_ytdlp():
    """Cach goi yt-dlp tren may nay.

    Cai bang pip tren Windows rat hay roi vao canh: module co day du nhung
    thu muc Scripts khong nam trong PATH, nen lenh 'yt-dlp' khong goi duoc.
    Luc do van con duong goi qua module bang chinh Python dang chay.
    """
    dat = env("YTDLP_PATH")
    if dat:
        return [dat]
    if shutil.which("yt-dlp"):
        return ["yt-dlp"]
    return [sys.executable, "-m", "yt_dlp"]


def cmd_ytdlp(url, target, sess, workers):
    """Dung lenh yt-dlp. Tach rieng khoi viec chay de con test duoc.

    --quiet --no-progress: yt-dlp mac dinh in tien trinh theo tung phan tram,
    chay 59 tap thi log dai hang nghin dong va nuot mat cac dong quan trong.
    Loi van in ra stderr nhu thuong.
    """
    cmd = lenh_ytdlp() + [
        "--no-playlist", "--no-warnings", "--quiet", "--no-progress",
        "--concurrent-fragments", str(workers),
        "--merge-output-format", "mp4",
        # trong -o thi % la ky tu dac biet, nhan doi de giu nguyen ten file
        "-o", target.replace("%", "%%"),
    ]
    for k, v in (sess.headers or {}).items():
        if k.lower() == "referer":
            cmd += ["--referer", v]
        elif k.lower() == "user-agent":
            cmd += ["--user-agent", v]
        elif k.lower() != "accept":
            cmd += ["--add-header", f"{k}:{v}"]
    cmd.append(url)
    return cmd


def run_ytdlp(url, target, sess, workers):
    """Giao viec tai cho yt-dlp, nhung van giu phan dat ten cua minh.

    yt-dlp ho tro khoang 1800 trang va co nguoi bao tri; khong viec gi phai
    dung lai no. Thu no lam do la doc metadata cua server de dat ten, nen ta
    ep -o thanh duong dan da tinh san tu ten tap doc duoc trong DOM.

    Header lay thang tu session, de Referer/Cookie giong het luc tai bang
    bo tai san co - nhieu CDN chan neu thieu Referer.
    """
    cmd = cmd_ytdlp(url, target, sess, workers)
    try:
        ma = subprocess.run(cmd).returncode
    except FileNotFoundError:
        raise RuntimeError(
            f"khong chay duoc '{exe}' - cai bang: pip install yt-dlp"
            " (hoac dat ENGINE= de dung bo tai san co)") from None
    if ma != 0:
        raise RuntimeError(f"yt-dlp tra ve ma loi {ma}")
    if not os.path.exists(target) or os.path.getsize(target) == 0:
        raise RuntimeError("yt-dlp bao xong nhung khong thay file dich")
    return target


def download(url, target, sess, workers=8, retries=5, keep=False):
    if os.path.exists(target) and os.path.getsize(target) > 0:
        print(f"  bo qua (da co): {os.path.basename(target)}")
        return target
    os.makedirs(os.path.dirname(os.path.abspath(target)), exist_ok=True)

    if dung_ytdlp():
        run_ytdlp(url, target, sess, workers)
        # Khong doc playlist nen khong biet phim dai bao nhieu de doi chieu;
        # kiem duoc muc "file co mo ra duoc khong" la het.
        if probe_duration(target) is None:
            os.remove(target)
            raise RuntimeError("yt-dlp cho ra file ma ffprobe khong doc duoc")
        print(f"  -> {os.path.basename(target)} "
              f"({os.path.getsize(target) / 1048576:.1f} MB) [yt-dlp]")
        return target

    pl = parse_source(sess, url)
    work = os.path.join(tempfile.gettempdir(), "hls-dl",
                        safe_name(os.path.splitext(os.path.basename(target))[0], 60))
    os.makedirs(work, exist_ok=True)

    mota = f"  {pl.kind}: {len(pl.segments)} manh"
    if pl.duration:
        mota += f", ~{int(pl.duration // 60)}m{int(pl.duration % 60):02d}s"
    if pl.segments[0].key:
        mota += " [AES-128]"
    if pl.audio:
        mota += f", tieng rieng {len(pl.audio.segments)} manh"
    print(mota)

    parts, init_file = fetch_track(sess, pl, work, "v", workers, retries)
    a_parts = a_init = None
    if pl.audio:
        a_parts, a_init = fetch_track(sess, pl.audio, work, "a", workers, retries)

    merge(parts, init_file, target, work, a_parts, a_init)
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
