"""HLS tach tieng ra luong rieng, va playlist phat truc tiep.

Vi sao dang mot file rieng: day la loai loi nguy hiem nhat ma du an nay tung
dinh - loi KHONG kem theo dau hieu gi. Mot variant chi-co-hinh ma khong ghep
them luong tieng se cho ra video CAM, trong khi thoi luong van dung y nhu
playlist noi, nen phep kiem thoi luong khong bao gio bat duoc.
"""
import io
import os
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import hls_dl  # noqa: E402


class PhanHoiGia:
    def __init__(self, text):
        self.text = text
        self.content = text.encode()

    def raise_for_status(self):
        pass


class SessionGia:
    def __init__(self, trang):
        self.trang = trang
        self.da_goi = []

    def get(self, url, **_):
        self.da_goi.append(url)
        for duoi, noi_dung in self.trang.items():
            if url.endswith(duoi):
                return PhanHoiGia(noi_dung)
        raise AssertionError(f'test chua chuan bi noi dung cho {url}')


MEDIA = '#EXTM3U\n#EXTINF:6.0,\ns1.ts\n#EXTINF:6.0,\ns2.ts\n#EXT-X-ENDLIST\n'


def master(stream_inf, media_lines=''):
    return f'#EXTM3U\n{media_lines}{stream_inf}\nv.m3u8\n'


AUDIO_MEDIA = ('#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="aud",NAME="vi",'
               'DEFAULT=YES,URI="a.m3u8"\n')


class TachTiengRieng(unittest.TestCase):
    def doc(self, noi_dung):
        s = SessionGia({'master.m3u8': noi_dung, 'v.m3u8': MEDIA, 'a.m3u8': MEDIA})
        with redirect_stdout(io.StringIO()):
            return hls_dl.parse(s, 'https://cdn/a/master.m3u8'), s

    def test_variant_chi_co_hinh_thi_ghep_them_tieng(self):
        pl, s = self.doc(master(
            '#EXT-X-STREAM-INF:BANDWIDTH=2400000,CODECS="avc1.64002a",AUDIO="aud"',
            AUDIO_MEDIA))
        self.assertIsNotNone(pl.audio, 'khong ghep tieng -> video se bi cam')
        self.assertTrue(any(u.endswith('a.m3u8') for u in s.da_goi))

    def test_tieng_da_nam_trong_manh_thi_KHONG_ghep_them(self):
        # CODECS co mp4a = tieng da ghep san; ghep nua thanh hai luong chong nhau
        pl, _ = self.doc(master(
            '#EXT-X-STREAM-INF:BANDWIDTH=2400000,CODECS="avc1.64002a,mp4a.40.2",AUDIO="aud"',
            AUDIO_MEDIA))
        self.assertIsNone(pl.audio)

    def test_cac_ma_tieng_khac_cung_duoc_nhan(self):
        for ma in ['ac-3', 'ec-3', 'opus', 'vorbis', 'dts']:
            pl, _ = self.doc(master(
                f'#EXT-X-STREAM-INF:BANDWIDTH=100,CODECS="avc1.4d401f,{ma}",AUDIO="aud"',
                AUDIO_MEDIA))
            self.assertIsNone(pl.audio, ma)

    def test_variant_khong_khai_AUDIO_thi_thoi(self):
        pl, _ = self.doc(master(
            '#EXT-X-STREAM-INF:BANDWIDTH=2400000,CODECS="avc1.64002a"', AUDIO_MEDIA))
        self.assertIsNone(pl.audio)

    def test_nhom_khong_khop_thi_thoi(self):
        pl, _ = self.doc(master(
            '#EXT-X-STREAM-INF:BANDWIDTH=2400000,CODECS="avc1.64002a",AUDIO="nhom-khac"',
            AUDIO_MEDIA))
        self.assertIsNone(pl.audio)

    def test_uu_tien_ban_DEFAULT_YES(self):
        hai = ('#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="aud",NAME="en",URI="en.m3u8"\n'
               '#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="aud",NAME="vi",DEFAULT=YES,URI="vi.m3u8"\n')
        s = SessionGia({'master.m3u8': master(
            '#EXT-X-STREAM-INF:BANDWIDTH=100,CODECS="avc1.64002a",AUDIO="aud"', hai),
            'v.m3u8': MEDIA, 'vi.m3u8': MEDIA, 'en.m3u8': MEDIA})
        with redirect_stdout(io.StringIO()):
            hls_dl.parse(s, 'https://cdn/a/master.m3u8')
        self.assertTrue(any(u.endswith('vi.m3u8') for u in s.da_goi))
        self.assertFalse(any(u.endswith('en.m3u8') for u in s.da_goi))

    def test_the_MEDIA_khong_co_URI_thi_bo_qua(self):
        # TYPE=AUDIO khong kem URI nghia la tieng nam san trong variant
        pl, _ = self.doc(master(
            '#EXT-X-STREAM-INF:BANDWIDTH=100,CODECS="avc1.64002a",AUDIO="aud"',
            '#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="aud",NAME="vi",DEFAULT=YES\n'))
        self.assertIsNone(pl.audio)


class PhatTrucTiep(unittest.TestCase):
    def test_thieu_ENDLIST_thi_canh_bao(self):
        s = SessionGia({'i.m3u8': '#EXTM3U\n#EXTINF:6.0,\ns1.ts\n'})
        loi = io.StringIO()
        with redirect_stderr(loi), redirect_stdout(io.StringIO()):
            hls_dl.parse(s, 'https://cdn/a/i.m3u8')
        self.assertIn('ENDLIST', loi.getvalue())

    def test_co_ENDLIST_thi_im_lang(self):
        s = SessionGia({'i.m3u8': MEDIA})
        loi = io.StringIO()
        with redirect_stderr(loi), redirect_stdout(io.StringIO()):
            hls_dl.parse(s, 'https://cdn/a/i.m3u8')
        self.assertEqual(loi.getvalue(), '')


class LuoiAnToanChoTieng(unittest.TestCase):
    """Bat MOI nguyen nhan lam video cam, khong chi rieng cai da vá."""

    def setUp(self):
        self._probe = hls_dl.probe_duration
        self._tieng = hls_dl.co_luong_tieng
        self._env = os.environ.get('VERIFY_AUDIO')
        os.environ['VERIFY_OUTPUT'] = 'true'
        hls_dl.probe_duration = lambda _p: 100.0

    def tearDown(self):
        hls_dl.probe_duration = self._probe
        hls_dl.co_luong_tieng = self._tieng
        if self._env is None:
            os.environ.pop('VERIFY_AUDIO', None)
        else:
            os.environ['VERIFY_AUDIO'] = self._env

    def test_khong_co_tieng_thi_canh_bao_du_thoi_luong_dung(self):
        hls_dl.co_luong_tieng = lambda _p: False
        with redirect_stderr(io.StringIO()):
            cb = hls_dl.verify('x.mp4', 100.0)
        self.assertIsNotNone(cb)
        self.assertIn('tieng', cb)

    def test_co_tieng_thi_khong_keu(self):
        hls_dl.co_luong_tieng = lambda _p: True
        self.assertIsNone(hls_dl.verify('x.mp4', 100.0))

    def test_khong_hoi_duoc_ffprobe_thi_khong_ket_luan_bua(self):
        hls_dl.co_luong_tieng = lambda _p: None
        self.assertIsNone(hls_dl.verify('x.mp4', 100.0))

    def test_tat_duoc_bang_VERIFY_AUDIO(self):
        os.environ['VERIFY_AUDIO'] = 'false'
        hls_dl.co_luong_tieng = lambda _p: False
        self.assertIsNone(hls_dl.verify('x.mp4', 100.0))


if __name__ == '__main__':
    unittest.main()
