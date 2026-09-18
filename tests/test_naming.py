"""Dat ten file: ten tap -> duong dan tren dia.

Day la cho de sai ma kho thay: ten sai chi lo ra khi di mo thu muc,
chu khong lam chuong trinh bao loi.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import hls_dl  # noqa: E402
import merge_local  # noqa: E402


class TenFileAnToan(unittest.TestCase):
    def test_bo_ky_tu_cam_tren_windows(self):
        self.assertEqual(hls_dl.safe_name('E1: Cung/cau?'), 'E1 Cung cau')

    def test_gop_khoang_trang_thua(self):
        self.assertEqual(hls_dl.safe_name('E1.   Just   an  Old Book'),
                         'E1. Just an Old Book')

    def test_giu_dau_tieng_viet(self):
        self.assertEqual(hls_dl.safe_name('Tập 4. Khởi đầu'), 'Tập 4. Khởi đầu')

    def test_ten_danh_rieng_cua_windows(self):
        # CON.mp4 khong tao duoc tren Windows -> phai doi di
        self.assertTrue(hls_dl.safe_name('CON').startswith('_'))
        self.assertTrue(hls_dl.safe_name('NUL.txt').startswith('_'))

    def test_khong_de_lai_dau_cham_cuoi(self):
        self.assertFalse(hls_dl.safe_name('E1. Het roi...').endswith('.'))

    def test_cat_bot_khi_qua_dai(self):
        self.assertLessEqual(len(hls_dl.safe_name('x' * 300)), 120)

    def test_chuoi_rong_van_ra_ten_dung_duoc(self):
        self.assertEqual(hls_dl.safe_name('///'), 'untitled')


class DuongDanRa(unittest.TestCase):
    def setUp(self):
        self._cu = {k: os.environ.get(k) for k in
                    ('NAME_TEMPLATE', 'GROUP_BY_SERIES', 'SERIES_NAME')}

    def tearDown(self):
        for k, v in self._cu.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_mac_dinh_co_so_thu_tu_zero_pad(self):
        # Khong co tien to nay thi File Explorer sap E1, E10, E11, E2
        os.environ['NAME_TEMPLATE'] = '{index:03d} - {title}'
        os.environ['GROUP_BY_SERIES'] = 'false'
        p = hls_dl.out_path('/out', 'E7. Same Ability', 7)
        self.assertEqual(os.path.basename(p), '007 - E7. Same Ability.mp4')

    def test_mau_chi_co_ten(self):
        os.environ['NAME_TEMPLATE'] = '{title}'
        os.environ['GROUP_BY_SERIES'] = 'false'
        p = hls_dl.out_path('/out', 'E7. Same Ability', 7)
        self.assertEqual(os.path.basename(p), 'E7. Same Ability.mp4')

    def test_gom_theo_tac_pham_thanh_thu_muc_rieng(self):
        os.environ['NAME_TEMPLATE'] = '{index:03d} - {title}'
        os.environ['GROUP_BY_SERIES'] = 'true'
        p = hls_dl.out_path('/out', 'E1. Just an Old Book', 1, series='My Vampire System')
        self.assertIn('My Vampire System', p.replace('\\', '/').split('/'))

    def test_mau_hong_thi_quay_ve_ten_goc_chu_khong_chet(self):
        os.environ['NAME_TEMPLATE'] = '{khong_ton_tai}'
        os.environ['GROUP_BY_SERIES'] = 'false'
        p = hls_dl.out_path('/out', 'E1. Just an Old Book', 1)
        self.assertEqual(os.path.basename(p), 'E1. Just an Old Book.mp4')

    def test_ky_tu_cam_trong_ten_tac_pham_cung_bi_loc(self):
        os.environ['GROUP_BY_SERIES'] = 'true'
        p = hls_dl.out_path('/out', 'E1. A', 1, series='Phim: Phan 1/2')
        self.assertNotIn(':', p[2:])   # bo qua "C:" neu co
        self.assertNotIn('?', p)


class ThuTuManhTaiSan(unittest.TestCase):
    """merge_local sap xep theo SO CUOI trong ten, nen hash o dau khong anh huong."""

    def test_lay_so_cuoi_bo_qua_hash(self):
        self.assertEqual(
            merge_local.seq_number('50d6c3f040126e1af16d1d66bf71346e5178f45d_vid_seg_00005.ts'), 5)

    def test_sap_xep_tu_nhien_khong_phai_theo_chu_cai(self):
        ten = ['seg10.ts', 'seg2.ts', 'seg1.ts']
        self.assertEqual(sorted(ten, key=merge_local.natural_key),
                         ['seg1.ts', 'seg2.ts', 'seg10.ts'])

    def test_phat_hien_thieu_manh(self):
        # ghep thieu manh ra video nhay coc, phai bao truoc
        self.assertEqual(merge_local.report_gaps(['a_1.ts', 'a_5.ts']), [2, 3, 4])

    def test_khong_thieu_thi_khong_bao(self):
        self.assertEqual(merge_local.report_gaps(['a_1.ts', 'a_2.ts', 'a_3.ts']), [])


if __name__ == '__main__':
    unittest.main()
