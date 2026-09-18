"""Doc file .mpd (DASH).

MPD co nhieu cach mo ta danh sach manh - SegmentTemplate dem theo so, theo
dong ho, SegmentList liet ke thang, hoac ca Representation la mot file. Moi
cach mot nhanh code, nen day la cho de sot nhat.

Khong cham mang: session gia tra ve noi dung dung san.
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
        self.headers = {}

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

    def head(self, url, **_):
        return PhanHoiGia('')


def mpd(body, tong="PT1M0.0S", base=""):
    return (f'<?xml version="1.0"?>\n'
            f'<MPD xmlns="urn:mpeg:dash:schema:mpd:2011" '
            f'mediaPresentationDuration="{tong}">\n'
            f'{base}<Period>\n{body}\n</Period>\n</MPD>\n')


def video(inner, bw=2400000):
    return (f'<AdaptationSet mimeType="video/mp4">'
            f'<Representation id="v1" bandwidth="{bw}">{inner}</Representation>'
            f'</AdaptationSet>')


class DocThoiLuong(unittest.TestCase):
    def test_cac_dang_thuong_gap(self):
        for chuoi, mong in [('PT10M47.5S', 647.5), ('PT1H2M3S', 3723.0),
                            ('PT30S', 30.0), ('PT2M', 120.0)]:
            self.assertAlmostEqual(hls_dl.iso_duration(chuoi), mong, msg=chuoi)

    def test_chuoi_hong_tra_ve_0_chu_khong_chet(self):
        for chuoi in ['', None, 'bua bai', 'P']:
            self.assertEqual(hls_dl.iso_duration(chuoi), 0.0)


class MauUrl(unittest.TestCase):
    def test_thay_cac_bien(self):
        self.assertEqual(hls_dl._fill('s-$RepresentationID$-$Number$.m4s', 'v1', '900', 7),
                         's-v1-7.m4s')

    def test_giu_dinh_dang_zero_pad(self):
        self.assertEqual(hls_dl._fill('s-$Number%05d$.m4s', 'v1', '900', 42), 's-00042.m4s')

    def test_bien_Time(self):
        self.assertEqual(hls_dl._fill('s-$Time$.m4s', 'v1', '900', None, 90000), 's-90000.m4s')

    def test_hai_dola_lien_nhau_la_dau_dola_that(self):
        self.assertEqual(hls_dl._fill('gia$$.m4s', 'v1', '900'), 'gia$.m4s')


class SegmentTemplateTheoSo(unittest.TestCase):
    def test_dem_so_manh_tu_duration(self):
        # tong 60s, moi manh 6s -> 10 manh
        body = video('<SegmentTemplate initialization="init.mp4" media="s-$Number$.m4s"'
                     ' startNumber="1" duration="6000" timescale="1000"/>')
        s = SessionGia({'x.mpd': mpd(body)})
        pl = hls_dl.parse_dash(s, 'https://cdn/a/x.mpd')
        self.assertEqual(len(pl.segments), 10)
        self.assertEqual(pl.init, 'https://cdn/a/init.mp4')
        self.assertEqual(pl.segments[0].url, 'https://cdn/a/s-1.m4s')
        self.assertEqual(pl.segments[9].url, 'https://cdn/a/s-10.m4s')
        self.assertEqual(pl.kind, 'DASH')

    def test_startNumber_khac_1(self):
        body = video('<SegmentTemplate media="s-$Number$.m4s" startNumber="100"'
                     ' duration="30000" timescale="1000"/>')
        s = SessionGia({'x.mpd': mpd(body)})
        pl = hls_dl.parse_dash(s, 'https://cdn/a/x.mpd')
        self.assertEqual(pl.segments[0].url, 'https://cdn/a/s-100.m4s')

    def test_le_ra_thi_lam_tron_len(self):
        # 60s / 7s = 8.57 -> phai la 9 manh, khong duoc cat mat doan cuoi
        body = video('<SegmentTemplate media="s-$Number$.m4s" duration="7" timescale="1"/>')
        s = SessionGia({'x.mpd': mpd(body)})
        pl = hls_dl.parse_dash(s, 'https://cdn/a/x.mpd')
        self.assertEqual(len(pl.segments), 9)


class SegmentTimeline(unittest.TestCase):
    def test_the_S_co_r_nghia_la_lap_them(self):
        # r="4" = them 4 lan nua, tong 5 manh
        body = video('<SegmentTemplate media="s-$Number$.m4s" startNumber="1" timescale="1000">'
                     '<SegmentTimeline><S t="0" d="6000" r="4"/></SegmentTimeline>'
                     '</SegmentTemplate>')
        s = SessionGia({'x.mpd': mpd(body)})
        pl = hls_dl.parse_dash(s, 'https://cdn/a/x.mpd')
        self.assertEqual(len(pl.segments), 5)

    def test_nhieu_the_S_noi_tiep(self):
        body = video('<SegmentTemplate media="s-$Number$.m4s" startNumber="1" timescale="1000">'
                     '<SegmentTimeline><S t="0" d="6000" r="1"/><S d="3000"/></SegmentTimeline>'
                     '</SegmentTemplate>')
        s = SessionGia({'x.mpd': mpd(body)})
        pl = hls_dl.parse_dash(s, 'https://cdn/a/x.mpd')
        self.assertEqual(len(pl.segments), 3)

    def test_bien_Time_lay_moc_thoi_gian_cong_don(self):
        body = video('<SegmentTemplate media="s-$Time$.m4s" timescale="1000">'
                     '<SegmentTimeline><S t="0" d="6000" r="2"/></SegmentTimeline>'
                     '</SegmentTemplate>')
        s = SessionGia({'x.mpd': mpd(body)})
        pl = hls_dl.parse_dash(s, 'https://cdn/a/x.mpd')
        self.assertEqual([x.url.rsplit('/', 1)[-1] for x in pl.segments],
                         ['s-0.m4s', 's-6000.m4s', 's-12000.m4s'])


class CacDangKhac(unittest.TestCase):
    def test_SegmentList_liet_ke_thang(self):
        body = video('<SegmentList><Initialization sourceURL="i.mp4"/>'
                     '<SegmentURL media="a.m4s"/><SegmentURL media="b.m4s"/></SegmentList>')
        s = SessionGia({'x.mpd': mpd(body)})
        pl = hls_dl.parse_dash(s, 'https://cdn/a/x.mpd')
        self.assertEqual(len(pl.segments), 2)
        self.assertEqual(pl.init, 'https://cdn/a/i.mp4')

    def test_khong_template_khong_list_thi_la_mot_file(self):
        body = video('<BaseURL>phim.mp4</BaseURL>')
        s = SessionGia({'x.mpd': mpd(body)})
        pl = hls_dl.parse_dash(s, 'https://cdn/a/x.mpd')
        self.assertEqual(len(pl.segments), 1)
        self.assertEqual(pl.segments[0].url, 'https://cdn/a/phim.mp4')

    def test_BaseURL_noi_chuoi_tu_MPD_xuong(self):
        body = video('<SegmentTemplate media="s-$Number$.m4s" duration="60" timescale="1"/>')
        s = SessionGia({'x.mpd': mpd(body, base='<BaseURL>https://cdn2/video/</BaseURL>')})
        pl = hls_dl.parse_dash(s, 'https://cdn/a/x.mpd')
        self.assertEqual(pl.segments[0].url, 'https://cdn2/video/s-1.m4s')


class ChonLuong(unittest.TestCase):
    MULTI = (
        '<AdaptationSet mimeType="video/mp4">'
        '<Representation id="lo" bandwidth="300000">'
        '<SegmentTemplate media="lo-$Number$.m4s" duration="60" timescale="1"/></Representation>'
        '<Representation id="hi" bandwidth="2400000">'
        '<SegmentTemplate media="hi-$Number$.m4s" duration="60" timescale="1"/></Representation>'
        '<Representation id="mid" bandwidth="900000">'
        '<SegmentTemplate media="mid-$Number$.m4s" duration="60" timescale="1"/></Representation>'
        '</AdaptationSet>'
        '<AdaptationSet mimeType="audio/mp4">'
        '<Representation id="a-lo" bandwidth="64000">'
        '<SegmentTemplate media="alo-$Number$.m4s" duration="60" timescale="1"/></Representation>'
        '<Representation id="a-hi" bandwidth="128000">'
        '<SegmentTemplate media="ahi-$Number$.m4s" duration="60" timescale="1"/></Representation>'
        '</AdaptationSet>')

    def test_lay_video_bitrate_cao_nhat_khong_phai_cai_cuoi(self):
        s = SessionGia({'x.mpd': mpd(self.MULTI)})
        pl = hls_dl.parse_dash(s, 'https://cdn/a/x.mpd')
        self.assertIn('hi-1.m4s', pl.segments[0].url)

    def test_tieng_tach_rieng_va_cung_lay_cao_nhat(self):
        s = SessionGia({'x.mpd': mpd(self.MULTI)})
        pl = hls_dl.parse_dash(s, 'https://cdn/a/x.mpd')
        self.assertIsNotNone(pl.audio)
        self.assertIn('ahi-1.m4s', pl.audio.segments[0].url)

    def test_khong_co_video_thi_bao_loi_ro_rang(self):
        body = ('<AdaptationSet mimeType="audio/mp4"><Representation id="a" bandwidth="1">'
                '<SegmentTemplate media="a-$Number$.m4s" duration="60" timescale="1"/>'
                '</Representation></AdaptationSet>')
        s = SessionGia({'x.mpd': mpd(body)})
        with self.assertRaises(RuntimeError):
            hls_dl.parse_dash(s, 'https://cdn/a/x.mpd')

    def test_chi_co_video_thi_audio_de_None(self):
        body = video('<SegmentTemplate media="s-$Number$.m4s" duration="60" timescale="1"/>')
        s = SessionGia({'x.mpd': mpd(body)})
        pl = hls_dl.parse_dash(s, 'https://cdn/a/x.mpd')
        self.assertIsNone(pl.audio)


class NhanDienNguon(unittest.TestCase):
    def test_duoi_m3u8_thi_doc_kieu_HLS(self):
        s = SessionGia({'i.m3u8': '#EXTM3U\n#EXTINF:6.0,\nseg.ts\n'})
        pl = hls_dl.parse_source(s, 'https://cdn/a/i.m3u8')
        self.assertEqual(pl.kind, 'HLS')

    def test_duoi_mpd_thi_doc_kieu_DASH(self):
        body = video('<SegmentTemplate media="s-$Number$.m4s" duration="60" timescale="1"/>')
        s = SessionGia({'x.mpd': mpd(body)})
        self.assertEqual(hls_dl.parse_source(s, 'https://cdn/a/x.mpd').kind, 'DASH')

    def test_file_video_truc_tiep(self):
        s = SessionGia({})
        for u in ['https://cdn/a/phim.mp4', 'https://cdn/a/phim.mkv?token=x']:
            pl = hls_dl.parse_source(s, u)
            self.assertEqual(pl.kind, 'file', u)
            self.assertEqual(len(pl.segments), 1)


if __name__ == '__main__':
    unittest.main()
