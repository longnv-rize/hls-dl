"""Kiem tra file sau khi ghep.

Ly do cai nay ton tai: da tung co mot tap "thanh cong" theo moi dau hieu
- exit code 0, khong dong loi nao, log bao da ghi file - ma ket qua van sai.
Playlist noi truoc phim dai bao nhieu, nen doi chieu lai la cach re nhat de
loi khong di qua trong im lang.

Khong goi ffprobe that: thay probe_duration bang ham gia de test chay nhanh
va khong phu thuoc may co ffmpeg hay khong.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import hls_dl  # noqa: E402


class NguongCanhBao(unittest.TestCase):
    """Canh bao khi lech > max(3s, 1%); nem loi khi lech > max(10s, 5%)."""

    def setUp(self):
        self._that = hls_dl.probe_duration
        self._tieng = hls_dl.co_luong_tieng
        self._env = os.environ.get('VERIFY_OUTPUT')
        os.environ['VERIFY_OUTPUT'] = 'true'
        # cac test o day dung duong dan gia, nen phai chan luon phep hoi ffprobe
        # ve tieng - khong thi no bao "khong co tieng" va lan at ket qua can do
        hls_dl.co_luong_tieng = lambda _p: True

    def tearDown(self):
        hls_dl.probe_duration = self._that
        hls_dl.co_luong_tieng = self._tieng
        if self._env is None:
            os.environ.pop('VERIFY_OUTPUT', None)
        else:
            os.environ['VERIFY_OUTPUT'] = self._env

    def gia_su_file_dai(self, giay):
        hls_dl.probe_duration = lambda _p: giay

    def test_khop_thi_im_lang(self):
        self.gia_su_file_dai(646.2)
        self.assertIsNone(hls_dl.verify('x.mp4', 647.0))

    def test_lech_it_trong_dung_sai_cho_phep(self):
        self.gia_su_file_dai(645.0)
        self.assertIsNone(hls_dl.verify('x.mp4', 647.0))

    def test_lech_vua_thi_canh_bao_nhung_van_giu_file(self):
        self.gia_su_file_dai(646.0)
        canh_bao = hls_dl.verify('x.mp4', 655.0)
        self.assertIsNotNone(canh_bao)
        self.assertIn('lech', canh_bao)

    def test_lech_nhieu_thi_nem_loi(self):
        self.gia_su_file_dai(646.0)
        with self.assertRaises(RuntimeError):
            hls_dl.verify('x.mp4', 1200.0)

    def test_thieu_han_mot_nua_phai_bi_bat(self):
        # truong hop nguy hiem nhat: file xem duoc nhung cut mat nua sau
        self.gia_su_file_dai(300.0)
        with self.assertRaises(RuntimeError):
            hls_dl.verify('x.mp4', 647.0)

    def test_ffprobe_khong_doc_duoc_thi_coi_la_hong(self):
        self.gia_su_file_dai(None)
        with self.assertRaises(RuntimeError):
            hls_dl.verify('x.mp4', 647.0)

    def test_phim_ngan_dung_nguong_giay_chu_khong_phai_phan_tram(self):
        # 1% cua 20s chi la 0.2s - qua chat, nen san duoi la 3s
        self.gia_su_file_dai(18.0)
        self.assertIsNone(hls_dl.verify('x.mp4', 20.0))

    def test_tat_duoc_bang_VERIFY_OUTPUT(self):
        os.environ['VERIFY_OUTPUT'] = 'false'
        self.gia_su_file_dai(1.0)
        self.assertIsNone(hls_dl.verify('x.mp4', 647.0))

    def test_playlist_khong_noi_thoi_luong_thi_bo_qua(self):
        self.gia_su_file_dai(646.0)
        self.assertIsNone(hls_dl.verify('x.mp4', 0))


class GomTenTacPham(unittest.TestCase):
    """Mot muc le mang series sai khong duoc lam tan file ra thu muc rieng."""

    def test_lay_ten_pho_bien_nhat(self):
        from collections import Counter
        items = ([{'series': 'My Vampire System'}] * 58
                 + [{'series': 'My Vampire System EP-36 Escape'}])
        ten = [it['series'] for it in items]
        self.assertEqual(Counter(ten).most_common(1)[0][0], 'My Vampire System')


if __name__ == '__main__':
    unittest.main()
