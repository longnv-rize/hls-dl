"""Doc file .m3u8.

Khong cham mang: dung mot session gia tra ve noi dung dung san, nho vay
test chay duoc offline va khong phu thuoc vao server con song hay khong.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import hls_dl  # noqa: E402


class PhanHoiGia:
    def __init__(self, text):
        self.text = text
        self.content = text.encode()

    def raise_for_status(self):
        pass


class SessionGia:
    """Tra ve noi dung theo URL. Ghi lai da goi nhung URL nao."""

    def __init__(self, trang):
        self.trang = trang
        self.da_goi = []

    def get(self, url, **_):
        self.da_goi.append(url)
        for duoi, noi_dung in self.trang.items():
            if url.endswith(duoi):
                return PhanHoiGia(noi_dung)
        raise AssertionError(f'test chua chuan bi noi dung cho {url}')


MEDIA = """#EXTM3U
#EXT-X-VERSION:3
#EXT-X-TARGETDURATION:6
#EXTINF:6.0,
seg_00001.ts
#EXTINF:6.0,
seg_00002.ts
#EXTINF:4.5,
seg_00003.ts
#EXT-X-ENDLIST
"""


class DocPlaylistThuong(unittest.TestCase):
    def test_lay_du_manh_va_cong_dung_thoi_luong(self):
        s = SessionGia({'index.m3u8': MEDIA})
        pl = hls_dl.parse(s, 'https://cdn/abc/index.m3u8')
        self.assertEqual(len(pl.segments), 3)
        self.assertAlmostEqual(pl.duration, 16.5)

    def test_url_manh_duoc_noi_thanh_tuyet_doi(self):
        s = SessionGia({'index.m3u8': MEDIA})
        pl = hls_dl.parse(s, 'https://cdn/abc/index.m3u8')
        self.assertEqual(pl.segments[0].url, 'https://cdn/abc/seg_00001.ts')

    def test_khong_co_manh_nao_thi_bao_loi_ro_rang(self):
        s = SessionGia({'index.m3u8': '#EXTM3U\n#EXT-X-ENDLIST\n'})
        with self.assertRaises(RuntimeError):
            hls_dl.parse(s, 'https://cdn/abc/index.m3u8')


MASTER = """#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=225600,RESOLUTION=144x144
low.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=2440490,RESOLUTION=720x720
mid.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=1162090,RESOLUTION=480x480
med.m3u8
"""


class DocMasterPlaylist(unittest.TestCase):
    def test_tu_chon_variant_bitrate_cao_nhat(self):
        # cao nhat khong phai cai cuoi cung trong danh sach -> phai so, khong duoc lay bua
        s = SessionGia({'master.m3u8': MASTER, 'mid.m3u8': MEDIA})
        pl = hls_dl.parse(s, 'https://cdn/abc/master.m3u8')
        self.assertEqual(len(pl.segments), 3)
        self.assertTrue(any(u.endswith('mid.m3u8') for u in s.da_goi))
        self.assertFalse(any(u.endswith('low.m3u8') for u in s.da_goi))


class MaHoaVaDinhDangKhac(unittest.TestCase):
    def test_doc_duoc_the_AES_128(self):
        noi_dung = ('#EXTM3U\n'
                    '#EXT-X-KEY:METHOD=AES-128,URI="key.bin",IV=0x0123456789abcdef0123456789abcdef\n'
                    '#EXTINF:6.0,\nseg1.ts\n')
        s = SessionGia({'index.m3u8': noi_dung})
        pl = hls_dl.parse(s, 'https://cdn/abc/index.m3u8')
        k = pl.segments[0].key
        self.assertEqual(k.method, 'AES-128')
        self.assertEqual(k.uri, 'https://cdn/abc/key.bin')
        self.assertEqual(len(k.iv), 16)

    def test_METHOD_NONE_nghia_la_tu_day_tro_di_khong_ma_hoa(self):
        noi_dung = ('#EXTM3U\n'
                    '#EXT-X-KEY:METHOD=AES-128,URI="key.bin"\n'
                    '#EXTINF:6.0,\nseg1.ts\n'
                    '#EXT-X-KEY:METHOD=NONE\n'
                    '#EXTINF:6.0,\nseg2.ts\n')
        s = SessionGia({'index.m3u8': noi_dung})
        pl = hls_dl.parse(s, 'https://cdn/abc/index.m3u8')
        self.assertIsNotNone(pl.segments[0].key)
        self.assertIsNone(pl.segments[1].key)

    def test_fmp4_co_doan_khoi_tao(self):
        noi_dung = ('#EXTM3U\n#EXT-X-MAP:URI="init.mp4"\n'
                    '#EXTINF:6.0,\nseg1.m4s\n')
        s = SessionGia({'index.m3u8': noi_dung})
        pl = hls_dl.parse(s, 'https://cdn/abc/index.m3u8')
        self.assertEqual(pl.init, 'https://cdn/abc/init.mp4')

    def test_byterange_ngam_dinh_noi_tiep_manh_truoc(self):
        noi_dung = ('#EXTM3U\n'
                    '#EXT-X-BYTERANGE:1000@0\n#EXTINF:6.0,\nall.ts\n'
                    '#EXT-X-BYTERANGE:500\n#EXTINF:6.0,\nall.ts\n')
        s = SessionGia({'index.m3u8': noi_dung})
        pl = hls_dl.parse(s, 'https://cdn/abc/index.m3u8')
        self.assertEqual(pl.segments[0].byterange, (1000, 0))
        self.assertEqual(pl.segments[1].byterange, (500, 1000))

    def test_ma_hoa_khac_AES_128_thi_bao_loi_chu_khong_cho_ra_file_hong(self):
        class K:
            method, uri, iv = 'SAMPLE-AES', '', None
        with self.assertRaises(RuntimeError):
            hls_dl.decrypt(b'x' * 16, K(), None, 0)


class DocENV(unittest.TestCase):
    def test_bien_moi_truong_that_duoc_uu_tien_hon_file(self):
        os.environ['WORKERS'] = '3'
        try:
            self.assertEqual(hls_dl.env_int('WORKERS', 8), 3)
        finally:
            os.environ.pop('WORKERS', None)

    def test_gia_tri_hong_thi_quay_ve_mac_dinh(self):
        os.environ['WORKERS'] = 'khong-phai-so'
        try:
            self.assertEqual(hls_dl.env_int('WORKERS', 8), 8)
        finally:
            os.environ.pop('WORKERS', None)

    def test_env_bool(self):
        for v, mong in [('true', True), ('1', True), ('yes', True),
                        ('false', False), ('0', False), ('bua', False)]:
            os.environ['X_TEST'] = v
            try:
                self.assertEqual(hls_dl.env_bool('X_TEST', True), mong, v)
            finally:
                os.environ.pop('X_TEST', None)


if __name__ == '__main__':
    unittest.main()
