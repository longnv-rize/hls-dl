"""Dong co tai thay the (ENGINE=yt-dlp).

yt-dlp ho tro khoang 1800 trang va co nguoi bao tri, nen thay vi viet lai
tung trang thi giao viec tai cho no - nhung VAN giu phan dat ten cua minh,
vi do moi la cho cong cu nay lam khac.

Test o day chi kiem phan dung lenh va nhan dien cach goi; viec chay that da
duoc thu truc tiep tren mot stream DASH dung lap.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import hls_dl  # noqa: E402


class SessionGia:
    def __init__(self, headers):
        self.headers = headers


class DatBienMoiTruong(unittest.TestCase):
    KHOA = ('ENGINE', 'YTDLP_PATH')

    def setUp(self):
        self._cu = {k: os.environ.get(k) for k in self.KHOA}

    def tearDown(self):
        for k, v in self._cu.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def dat(self, **kw):
        for k, v in kw.items():
            os.environ[k] = v


class ChonDongCo(DatBienMoiTruong):
    def test_cac_cach_viet_deu_nhan(self):
        for v in ['yt-dlp', 'yt_dlp', 'YT-DLP', '  yt-dlp  ']:
            self.dat(ENGINE=v)
            self.assertTrue(hls_dl.dung_ytdlp(), v)

    def test_de_trong_thi_dung_bo_tai_san_co(self):
        self.dat(ENGINE='')
        self.assertFalse(hls_dl.dung_ytdlp())

    def test_gia_tri_la_thi_khong_bat(self):
        for v in ['builtin', 'ffmpeg', 'bua']:
            self.dat(ENGINE=v)
            self.assertFalse(hls_dl.dung_ytdlp(), v)


class TimCachGoi(DatBienMoiTruong):
    def test_YTDLP_PATH_duoc_uu_tien(self):
        self.dat(YTDLP_PATH='/noi/khac/yt-dlp')
        self.assertEqual(hls_dl.lenh_ytdlp(), ['/noi/khac/yt-dlp'])

    def test_khong_dat_thi_tu_tim(self):
        os.environ.pop('YTDLP_PATH', None)
        lenh = hls_dl.lenh_ytdlp()
        # hoac la lenh tren PATH, hoac goi qua module bang chinh Python dang chay
        self.assertTrue(lenh == ['yt-dlp'] or lenh[-2:] == ['-m', 'yt_dlp'], lenh)


class DungLenh(DatBienMoiTruong):
    def setUp(self):
        super().setUp()
        self.dat(YTDLP_PATH='yt-dlp')
        self.sess = SessionGia({
            'User-Agent': 'UA/1.0',
            'Accept': '*/*',
            'Referer': 'https://site.com/show/abc',
            'Cookie': 'sid=xyz',
        })

    def lenh(self, target='/ra/001 - E1. Ten.mp4', url='https://cdn/a.m3u8', workers=8):
        return hls_dl.cmd_ytdlp(url, target, self.sess, workers)

    def test_ep_dung_duong_dan_dich(self):
        c = self.lenh()
        self.assertEqual(c[c.index('-o') + 1], '/ra/001 - E1. Ten.mp4')

    def test_dau_phan_tram_trong_ten_duoc_nhan_doi(self):
        # yt-dlp coi % la ky tu dac biet trong -o; khong nhan doi thi ten bi bien dang
        c = self.lenh(target='/ra/100% Cam giac.mp4')
        self.assertEqual(c[c.index('-o') + 1], '/ra/100%% Cam giac.mp4')

    def test_Referer_thanh_co_rieng(self):
        c = self.lenh()
        self.assertEqual(c[c.index('--referer') + 1], 'https://site.com/show/abc')
        self.assertNotIn('Referer:https://site.com/show/abc', c)

    def test_User_Agent_thanh_co_rieng(self):
        c = self.lenh()
        self.assertEqual(c[c.index('--user-agent') + 1], 'UA/1.0')

    def test_Cookie_di_qua_add_header(self):
        self.assertIn('Cookie:sid=xyz', self.lenh())

    def test_Accept_bi_bo_vi_khong_co_y_nghia_gi(self):
        self.assertFalse(any('Accept' in x for x in self.lenh()))

    def test_url_nam_cuoi_cung(self):
        self.assertEqual(self.lenh()[-1], 'https://cdn/a.m3u8')

    def test_so_luong_song_song_duoc_truyen_sang(self):
        c = self.lenh(workers=3)
        self.assertEqual(c[c.index('--concurrent-fragments') + 1], '3')

    def test_co_lam_im_log(self):
        # khong co hai co nay thi chay 59 tap se ra hang nghin dong tien trinh
        c = self.lenh()
        self.assertIn('--quiet', c)
        self.assertIn('--no-progress', c)

    def test_session_khong_co_header_van_chay(self):
        c = hls_dl.cmd_ytdlp('https://cdn/a.m3u8', '/ra/x.mp4', SessionGia(None), 8)
        self.assertEqual(c[-1], 'https://cdn/a.m3u8')


if __name__ == '__main__':
    unittest.main()
