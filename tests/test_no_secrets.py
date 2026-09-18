"""Canh khong de du lieu rieng tu lot vao cac file duoc commit.

Co that: trong luc lam, mot lenh `cp .env .env.example` da chep ca gia tri
thuc - trong do co ID thu muc Google Drive rieng - vao file nam trong repo.
Lan do phat hien kip truoc khi push. Test nay de lan sau khong con phu thuoc
vao viec co ai do di kiem tra bang mat hay khong.

.env.example chi duoc phep giu gia tri cua cac khoa mac dinh chung chung;
moi khoa con lai phai de rong.
"""
import os
import re
import unittest

GOC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Nhung khoa nay la mac dinh chung, khong dinh gi toi ca nhan hay he thong nao
DUOC_GIU_GIA_TRI = {
    'NAME_TEMPLATE', 'GROUP_BY_SERIES', 'MANIFEST', 'WORKERS', 'RETRIES',
    'VERIFY_OUTPUT', 'BROWSER_PROFILE', 'HEADLESS', 'WAIT_MS', 'SETTLE_MS',
    'FROM_EP', 'MAX_EP', 'STOP_AFTER_FAILS', 'OUTPUT_DIR',
}

# Nhung khoa mang thong tin rieng - BAT BUOC rong trong .env.example
PHAI_RONG = {
    'SHOW_URL', 'SITE_URL', 'COOKIE', 'AUTH_HEADER', 'REFERER',
    'DRIVE_FOLDER_ID', 'UPLOAD_TO', 'UPLOAD_CMD', 'SERIES_NAME',
}

# Dau hieu du lieu that, ap cho MOI file duoc commit
DAU_HIEU_RIENG_TU = [
    (re.compile(r'\b[0-9a-f]{32,}\b'), 'chuoi hex dai giong hash that'),
    (re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}'), 'dia chi email'),
]

# ID that (vd cua Google Drive) trong nhu chuoi ngau nhien: dai, khong co gach
# duoi, va tron ca chu hoa lan chu thuong lan so. Neu chi bat "chuoi dai" thi
# no vo luon nhung ten snake_case binh thuong nhu _generated_vid_mid_seg_00001.
UNG_VIEN_ID = re.compile(r'\b[A-Za-z0-9-]{24,}\b')


def giong_id_that(s):
    return (any(c.isupper() for c in s)
            and any(c.islower() for c in s)
            and any(c.isdigit() for c in s))

# Duong dan tuyet doi chi dang ngo trong .env.example - do la file duoc sinh
# ra tu .env cua mot may cu the, nen "D:/..." o do nhieu kha nang la duong dan
# that bi chep nguyen. Trong README thi "D:/Videos" lai la vi du huong dan
# hoan toan binh thuong. Luat hay bao dong gia thi som muon cung bi tat, nen
# chi ap cho dung file can canh.
DUONG_DAN_TUYET_DOI = re.compile(r'\b[A-Z]:[\\/]', re.I)
FILE_CANH_DUONG_DAN = {'.env.example'}

FILE_TRONG_REPO = ['.env.example', 'README.md', 'hls_dl.py', 'merge_local.py',
                   'grab.js', 'auto_grab.js', 'requirements.txt', '.gitignore']


def doc(ten):
    with open(os.path.join(GOC, ten), encoding='utf-8') as f:
        return f.read()


class FileViDu(unittest.TestCase):
    def test_khoa_rieng_tu_phai_de_rong(self):
        for line in doc('.env.example').splitlines():
            m = re.match(r'^([A-Z_]+)=(.*)$', line)
            if m and m.group(1) in PHAI_RONG:
                self.assertEqual(
                    m.group(2), '',
                    f'{m.group(1)} trong .env.example dang co gia tri that: {m.group(2)!r}')

    def test_khong_co_khoa_la_nao_mang_gia_tri(self):
        for line in doc('.env.example').splitlines():
            m = re.match(r'^([A-Z_]+)=(.+)$', line)
            if m:
                self.assertIn(
                    m.group(1), DUOC_GIU_GIA_TRI,
                    f'{m.group(1)} co gia tri nhung chua duoc duyet la mac dinh chung')

    def test_du_khoa_so_voi_env_that(self):
        """.env.example phai liet ke du moi khoa, khong duoc thieu cai nao."""
        lay = lambda s: {m.group(1) for m in re.finditer(r'^([A-Z_]+)=', s, re.M)}
        thieu = lay(doc('.env')) - lay(doc('.env.example'))
        self.assertFalse(thieu, f'.env.example thieu cac khoa: {sorted(thieu)}')


class KhongLoDuLieuThat(unittest.TestCase):
    def test_quet_toan_bo_file_duoc_commit(self):
        for ten in FILE_TRONG_REPO:
            noi_dung = doc(ten)
            for so, line in enumerate(noi_dung.splitlines(), 1):
                # bo qua cho giu cho va cac vi du da lam chung chung
                if 'XXXX' in line or '<ma-show>' in line or 'example.com' in line:
                    continue
                kiem = list(DAU_HIEU_RIENG_TU)
                if ten in FILE_CANH_DUONG_DAN:
                    kiem.append((DUONG_DAN_TUYET_DOI, 'duong dan tuyet doi tren may ai do'))
                for mau, mo_ta in kiem:
                    tim = mau.search(line)
                    if tim:
                        self.fail(f'{ten}:{so} co {mo_ta}: {tim.group(0)!r}\n    {line.strip()}')
                for ung_vien in UNG_VIEN_ID.findall(line):
                    if giong_id_that(ung_vien):
                        self.fail(f'{ten}:{so} co chuoi giong ID that: {ung_vien!r}'
                                  f'\n    {line.strip()}')


if __name__ == '__main__':
    unittest.main()
