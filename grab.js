/* ============================================================================
 * grab.js - dan vao Console cua trinh duyet (F12) tren trang dang xem video.
 *
 * Link video KHONG co san trong HTML. No chi xuat hien khi ban bam Play, luc
 * player goi fetch()/XHR. Script nay hook vao dung 2 cho do tu truoc, nen bat
 * duoc ngay khoanh khac frontend gui request - ke ca khi URL co token het han.
 *
 * Ten file lay tu TEN TAP trong DOM (vd "E1. Just an Old Book"), khong lay tu
 * ten manh .ts tren server (vd "50d6c3f0..._seg_00001.ts").
 *
 * Cach dung:
 *   1. Mo trang, dan toan bo file nay vao Console, Enter.  <-- TRUOC khi bam Play
 *   2. Bam vao tung tap de phat -> moi tap bat duoc se log mot dong xanh.
 *   3. Xong: go  HLS.save()  -> tai ve manifest.json
 * ==========================================================================*/
(() => {
  const VERSION = 8;

  // Dan lai ban MOI de len ban cu thi phai go ban cu ra truoc, khong thi hook
  // cua ban cu van con nguyen va ban moi khong bao gio duoc cai.
  if (window.HLS && window.HLS.__installed) {
    if (window.HLS.__version === VERSION) {
      console.log('%cgrab.js v' + VERSION + ' da chay roi. Dung HLS.list() / HLS.probe()', 'color:#fa0');
      return;
    }
    console.log('%cGo ban cu (v' + (window.HLS.__version || '?') + ') -> cai v' + VERSION, 'color:#fa0');
    try { window.HLS.__restore(); } catch { /* co gang thoi */ }
  }

  // Ham go hook, de lan sau con nang cap duoc.
  const restores = [];

  // Trang video tai hang tram manh .ts; bo dem Resource Timing mac dinh chi 250
  // muc nen ban ghi cua file .m3u8 bi day ra tu lau. Noi rong ra.
  try { performance.setResourceTimingBufferSize(2000); } catch { /* khong sao */ }

  // Ten tap gan nhu luon co dang "E1. ...", "Ep 2 - ...", "Tap 3: ...".
  // Bam theo mau nay chac hon bam theo class, vi the <span> thuong khong co class.
  const EPISODE_RE = /^(E|Ep|Episode|Tap|Tập|Chuong|Chương|Chapter|Phan|Phần)\s*\d+\s*[.:)\-–]/i;

  // Du phong khi khong nhan ra dang "E1." nao.
  const TITLE_SELECTORS = [
    '.lesson-title', '.video-title', '[class*="episode"][class*="active"]',
    '[class*="playing"]', 'h1', 'h2',
  ];

  const PLAYLIST_RE = /\.m3u8(\?|$)|[?&](format|type)=m3u8|\/manifest(\/|\?|$)/i;
  const SEGMENT_RE = /\.(ts|m4s|mp4|aac|cmf[vat])(\?|$)/i;
  // De moc URL ra tu chuoi van ban (log cua player...). Loai luon ky tu … vi
  // do la dau DevTools chen khi rut gon URL -> URL cut, tai se hong.
  const URL_IN_TEXT_RE = /https?:\/\/[^\s"'<>\\)…]+?\.m3u8[^\s"'<>\\)…]*/gi;

  // URL do chinh player log ra la master playlist - dang tin hon URL bat duoc
  // o tang network, vi o do co ca cac playlist con lan vao.
  const FROM_LOG = 'lay tu log cua player';

  const playlists = new Map(); // url -> {index, series, title, url, page, fromLog}
  const segments = new Map();  // thu muc goc -> {count, sample}

  const txt = (el) => (el && el.textContent ? el.textContent.trim().replace(/\s+/g, ' ') : '');

  // --- ten tap ---------------------------------------------------------------

  const LEAF_SEL = 'span, h1, h2, h3, h4, p, div, li, a';

  /** The "la" = khong boc the nao khac. Text cua no la ten sach, khong lan metadata. */
  const isLeaf = (el) => el && el.querySelector && !el.querySelector(LEAF_SEL);

  /**
   * Tim ten tap ben TRONG mot khoi.
   * Phai tim xuong la, khong duoc lay text ca khoi: text cua ca the card cung
   * bat dau bang "E1." nhung keo theo ca "10:46", "4yr ago", "Play icon"...
   */
  const leafEpisodeIn = (root) => {
    if (!root || !root.querySelectorAll) return '';
    for (const el of [root, ...root.querySelectorAll(LEAF_SEL)]) {
      if (!el.matches || !el.matches(LEAF_SEL) || !isLeaf(el)) continue;
      const t = txt(el);
      if (t.length < 150 && EPISODE_RE.test(t)) return t;
    }
    return '';
  };

  // Ban bam vao tap nao thi tap do la tap dang phat - chac chan hon moi suy doan.
  let lastClicked = '';
  document.addEventListener('click', (e) => {
    let el = e.target;
    for (let hop = 0; el && hop < 8; hop++, el = el.parentElement) {
      const t = leafEpisodeIn(el);
      if (t) { lastClicked = t; return; }
    }
  }, true); // capture: chay truoc khi trang kip doi DOM

  /** Cac the la co text dang "E1. ...". */
  const episodeNodes = () =>
    [...document.querySelectorAll(LEAF_SEL)]
      .filter(isLeaf)
      .filter((el) => { const t = txt(el); return t.length < 150 && EPISODE_RE.test(t); });

  // "E1. ..." -> "e|."   |   "Ep 1 - ..." -> "ep|-"
  const shapeOf = (t) => {
    const m = t.match(/^([^\s\d]+)\s*\d+\s*([.:)\-–])/);
    return m ? m[1].toLowerCase() + '|' + m[2] : '?';
  };
  const numOf = (t) => {
    const m = t.match(/^[^\s\d]*\s*(\d+)/);
    return m ? parseInt(m[1], 10) : null;
  };

  /**
   * Danh sach tap "that".
   * Trang co ca header ("Ep 1 - Just an Old Book") lan muc luc ("E1. Just an Old
   * Book"). Nhom nao dong nhat ve dinh dang VA dong nhat ve so luong thi la muc
   * luc; nhom le vai cai la header -> bo. Sau do bo trung theo so tap.
   */
  const pickEpisodes = (all) => {
    const byShape = new Map();
    all.forEach((t) => {
      const s = shapeOf(t);
      byShape.set(s, [...(byShape.get(s) || []), t]);
    });
    let best = [];
    byShape.forEach((group) => { if (group.length > best.length) best = group; });

    const seen = new Set();
    return best.filter((t) => {
      const n = numOf(t);
      if (n === null || seen.has(n)) return false;
      seen.add(n);
      return true;
    });
  };

  const episodeTitles = () => pickEpisodes(episodeNodes().map(txt));

  // Giua chu va so co the la khoang trang, gach noi, hoac dau cham:
  // "EP 2", "EP-36", "E.7", "E36". Truoc chi nhan khoang trang nen "EP-36" truot.
  const NGAN = '[\\s\\-\\u2013.]*';
  const TU_TAP = '(E|Ep|Episode|Tap|Tập|Chuong|Chương|Chapter|Phan|Phần)';

  /** Moc so tap ra khoi chuoi bat ky: "My Vampire System EP-36 Escape" -> 36 */
  const episodeNumIn = (s) => {
    const m = String(s || '').match(new RegExp(`\\b${TU_TAP}${NGAN}(\\d+)\\b`, 'i'));
    return m ? parseInt(m[2], 10) : null;
  };

  /** Doi so tap thanh ten chuan lay tu muc luc: 2 -> "E2. Daily Quest" */
  const canonicalTitle = (num) =>
    (num === null ? '' : episodeTitles().find((t) => numOf(t) === num) || '');

  /**
   * Ten tap dang phat.
   * Cach chac nhat khong phai la doc mot cho nao do tren trang, ma la xac dinh
   * SO TAP truoc (tu cu click, tu document.title, tu khoi dang active), roi tra
   * nguoc ve ten chuan trong muc luc. Nho vay ten luon dong nhat "E2. Daily
   * Quest" du trang goi no la "EP 2 - Daily Quest" o cho khac.
   */
  const currentTitle = () => {
    const box = document.querySelector(
      '[class*="active"], [class*="playing"], [class*="current"], [class*="selected"], [aria-current]');
    const inBox = leafEpisodeIn(box);

    for (const hint of [lastClicked, document.title, inBox]) {
      const canon = canonicalTitle(episodeNumIn(hint));
      if (canon) return canon;
    }
    if (lastClicked) return lastClicked;
    if (inBox) return inBox;

    const titles = episodeTitles();
    if (titles.length === 1) return titles[0];

    for (const sel of TITLE_SELECTORS) {
      const t = txt(document.querySelector(sel));
      if (t && t.length > 1 && t.length < 200) return t;
    }
    return document.title.trim();
  };

  /**
   * Cat phan ten tap ra khoi chuoi: "X Ep 1 - Y" -> "X".
   * Khong doi hoi dau cau ngay sau so: "My Vampire System EP-36 Escape" viet
   * lien tuc, khong co dau gi sau "36". Truoc kia doi hoi nen no khong cat duoc,
   * the la ca cum thanh ten tac pham va tap do bi nem sang mot thu muc rieng.
   */
  const stripEpisode = (s) => s
    .replace(new RegExp(`\\s*[-\\u2013|:]?\\s*\\b${TU_TAP}${NGAN}\\d+\\b.*$`, 'i'), '')
    .trim();

  /** Ten tac pham - dung lam ten thu muc. */
  const seriesTitle = () => {
    const card = document.querySelector('a[href^="/show/"][aria-label], [aria-label][class*="hero"]');
    if (card && card.getAttribute('aria-label')) return stripEpisode(card.getAttribute('aria-label').trim());
    for (const sel of ['h1', 'h2']) {
      const raw = txt(document.querySelector(sel));
      const t = stripEpisode(raw);
      if (t && t.length < 150) return t;
    }
    return stripEpisode(document.title.split(/[|–]/)[0].trim());
  };

  // --- bat request -----------------------------------------------------------

  // Moi tap sinh ra NHIEU file .m3u8: mot master playlist va cac playlist con
  // (video rieng, audio rieng). Chi duoc lay master - hls_dl.py tu doc master
  // roi chon variant chat luong cao nhat. Cac URL cua cung mot tap nam chung
  // mot thu muc, nen gom theo thu muc va chi giu mot.
  const byDir = new Map(); // thu muc -> url da chon
  const dirOf = (u) => u.split('?')[0].replace(/\/[^/]*$/, '/');

  const addPlaylist = (abs, note) => {
    if (playlists.has(abs)) return;
    const dir = dirOf(abs);
    const fromLog = note === FROM_LOG;

    if (byDir.has(dir)) {
      const oldUrl = byDir.get(dir);
      const old = playlists.get(oldUrl);
      // URL do chinh player log ra la master that su -> thay cai doan truoc do
      if (!fromLog || !old || old.fromLog) return;
      playlists.delete(oldUrl);
      playlists.set(abs, { ...old, url: abs, fromLog: true });
      byDir.set(dir, abs);
      console.log(`%c[${old.index}] ${old.title} - doi sang master`, 'color:#fa0');
      return;
    }

    const title = currentTitle();
    const entry = {
      index: episodeNumIn(title) || playlists.size + 1,
      series: seriesTitle(),
      title,
      url: abs,
      page: location.href,
      fromLog,
    };
    playlists.set(abs, entry);
    byDir.set(dir, abs);
    console.log(`%c[${entry.index}] ${entry.title}`, 'color:#0c0;font-weight:bold',
      note ? `(${note})` : '');
    lastClicked = ''; // tranh gan nham ten nay cho tap ke tiep
  };

  const addSegment = (abs) => {
    const base = abs.split('?')[0].replace(/\/[^/]*$/, '/');
    const g = segments.get(base) || { count: 0, sample: abs };
    g.count += 1;
    segments.set(base, g);
  };

  const record = (url) => {
    if (!url || typeof url !== 'string' || url.startsWith('blob:') || url.startsWith('data:')) return;
    let abs;
    try { abs = new URL(url, location.href).href; } catch { return; }
    if (PLAYLIST_RE.test(abs)) addPlaylist(abs);
    else if (SEGMENT_RE.test(abs)) addSegment(abs);
  };

  performance.getEntriesByType('resource').forEach((e) => record(e.name));

  const origFetch = window.fetch;
  window.fetch = function (input, ...rest) {
    record(typeof input === 'string' ? input : input && input.url);
    return origFetch.call(this, input, ...rest).then((res) => {
      const ct = res.headers.get('content-type') || '';
      if (/mpegurl/i.test(ct) && res.url) addPlaylist(res.url, 'nhan qua content-type');
      return res;
    });
  };

  restores.push(() => { window.fetch = origFetch; });

  const origOpen = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function (method, url, ...rest) {
    record(url);
    this.addEventListener('load', () => {
      const ct = this.getResponseHeader && this.getResponseHeader('content-type');
      if (ct && /mpegurl/i.test(ct) && this.responseURL) {
        addPlaylist(this.responseURL, 'nhan qua content-type');
      }
    });
    return origOpen.call(this, method, url, ...rest);
  };
  restores.push(() => { XMLHttpRequest.prototype.open = origOpen; });

  // --- lop bat du phong ------------------------------------------------------
  //
  // Hook fetch/XHR o tren se TRUOT trong may truong hop that:
  //   - player chay trong <iframe> khac origin (hook o trang cha khong voi toi)
  //   - player tai playlist trong Web Worker
  //   - player da tai xong TRUOC khi ban kip dan script
  // Nen bat them tu 3 nguon nua duoi day.

  /** 1. Nhieu player tu console.log ra URL. Moc URL ra tu text cua log. */
  ['log', 'info', 'debug', 'warn'].forEach((level) => {
    const orig = console[level];
    console[level] = function (...args) {
      try {
        const text = args.map((a) => (typeof a === 'string' ? a : '')).join(' ');
        const found = text.match(URL_IN_TEXT_RE);
        if (found) found.forEach((u) => addPlaylist(u, FROM_LOG));
      } catch { /* khong duoc lam hong console */ }
      return orig.apply(this, args);
    };
    restores.push(() => { console[level] = orig; });
  });

  /** 2. Quet Resource Timing dinh ky - bat duoc ca cai tai truoc khi dan script. */
  let scanned = 0;
  const poll = setInterval(() => {
    const all = performance.getEntriesByType('resource');
    for (let i = scanned; i < all.length; i++) record(all[i].name);
    scanned = all.length;
  }, 1000);
  setTimeout(() => clearInterval(poll), 30 * 60 * 1000); // tu tat sau 30 phut
  restores.push(() => clearInterval(poll));

  /** 3. Phat hien DRM that su - de biet co tai duoc hay khong. */
  let drm = null;
  if (navigator.requestMediaKeySystemAccess) {
    const origEme = navigator.requestMediaKeySystemAccess;
    navigator.requestMediaKeySystemAccess = function (keySystem, ...rest) {
      if (!/clearkey/i.test(keySystem)) {
        drm = keySystem;
        console.warn(`%c[DRM] player yeu cau key system: ${keySystem}`, 'color:#f60');
      }
      return origEme.call(navigator, keySystem, ...rest);
    };
    restores.push(() => { navigator.requestMediaKeySystemAccess = origEme; });
  }

  /** 4. Canh bao neu player nam trong iframe - hook nay khong voi toi do. */
  setTimeout(() => {
    const frames = [...document.querySelectorAll('iframe')]
      .filter((f) => f.offsetWidth > 200 && f.offsetHeight > 150);
    if (frames.length && !playlists.size) {
      console.warn(
        '%cCo ' + frames.length + ' iframe tren trang.%c Neu player nam trong do thi phai '
        + 'chay grab.js BEN TRONG iframe: o Console, dung o chon frame (canh chu "top") '
        + 'de doi sang frame cua player, roi dan lai script.',
        'color:#f60;font-weight:bold', 'color:inherit');
    }
  }, 4000);

  // --- tu dong bam het cac tap -----------------------------------------------

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  const waitUntil = async (cond, ms, step = 200) => {
    const het = Date.now() + ms;
    while (Date.now() < het) {
      if (cond()) return true;
      await sleep(step);
    }
    return cond();
  };

  /** Cac khung cuon co the chua muc luc tap (co the la window, co the la div). */
  const scrollers = () => {
    const set = new Set([document.scrollingElement || document.documentElement]);
    episodeNodes().forEach((n) => {
      let el = n.parentElement;
      for (let i = 0; el && i < 12; i++, el = el.parentElement) {
        const st = getComputedStyle(el);
        if (/(auto|scroll)/.test(st.overflowY) && el.scrollHeight > el.clientHeight + 50) {
          set.add(el);
          break;
        }
      }
    });
    return [...set];
  };

  /**
   * The se bam cho mot ten tap. Phai tim lai moi lan vi trang ve lai DOM.
   *
   * Di nguoc len tim the bam duoc gan nhat. NHUNG neu the do om tu hai ten tap
   * tro len thi no qua rong - bam vao do khong biet se trung tap nao - luc do
   * quay ve bam chinh the chua ten tap.
   *
   * Day la cho de bam nham nhat: chu va nut bam khong nhat thiet nam cung mot
   * the. Go HLS.probeClicks() de xem truoc no dinh bam vao dau.
   */
  const clickableFor = (title) => {
    const el = episodeNodes().find((n) => txt(n) === title);
    if (!el) return null;
    const rong = el.closest('a, button, [role="button"], li');
    if (!rong || rong === el) return el;
    const soTapBenTrong = [...rong.querySelectorAll(LEAF_SEL)]
      .filter(isLeaf)
      .filter((x) => EPISODE_RE.test(txt(x))).length;
    return soTapBenTrong > 1 ? el : rong;
  };

  /** Mo ta ngan gon mot the, de doc trong bang chan doan. */
  const taThe = (el) => {
    if (!el) return '(khong co)';
    const cls = (typeof el.className === 'string' && el.className.trim())
      ? '.' + el.className.trim().split(/\s+/).slice(0, 2).join('.') : '';
    return el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') + cls;
  };

  // --- lenh cho ban ----------------------------------------------------------

  window.HLS = {
    __installed: true,
    __version: VERSION,
    /** Go het hook ra. Duoc goi tu dong khi ban dan de mot ban grab.js moi hon. */
    __restore() {
      restores.forEach((f) => { try { f(); } catch { /* co gang thoi */ } });
      this.__installed = false;
    },

    /** Xem da bat duoc gi. */
    list() {
      const data = [...playlists.values()];
      console.table(data.map(({ index, series, title }) => ({ index, series, title })));
      if (!data.length && segments.size) {
        console.warn('Chua bat duoc .m3u8 nhung CO thay cac manh - xem HLS.segments()');
      }
      return data;
    },

    /** Cac nhom manh .ts da thay - dung khi khong bat duoc .m3u8 nao. */
    segments() {
      const rows = [...segments.entries()].map(([base, g]) => ({ base, ...g }));
      console.table(rows);
      return rows;
    },

    /** Xem script nhan ra nhung gi tren trang hien tai. */
    probe() {
      const nodes = episodeTitles();
      const raw = episodeNodes().length;
      console.log('Tac pham   :', seriesTitle());
      console.log('Ten tap    :', nodes.length ? nodes : '(khong nhan ra dang "E1. ...")');
      if (raw > nodes.length) console.log(`             (loc bo ${raw - nodes.length} muc trung/header)`);
      console.log('Se dung    :', currentTitle());
      console.log('Da bat     :', playlists.size + ' playlist, ' + segments.size + ' nhom manh');
      console.log('DRM        :', drm
        ? drm + ' -> stream co the duoc bao ve, hls_dl.py se bao loi neu dung vay'
        : 'khong thay player goi DRM');
      if (!playlists.size) {
        console.log('%cChua bat duoc link. Thu: Network -> filter "m3u8" -> chuot phai -> '
          + 'Copy link address -> HLS.add("<url>")', 'color:#f60');
      }
      return nodes;
    },

    /**
     * Xem TRUOC no dinh bam vao the nao, khong bam gi ca.
     * Chay cai nay truoc HLS.auto() de tu mat kiem tra, thay vi tin.
     *
     *   HLS.probeClicks()              chi in bang
     *   HLS.probeClicks({ to: true })  to vien mau len trang de nhin thay
     */
    probeClicks({ to = false } = {}) {
      document.querySelectorAll('[data-hlsdl-to]').forEach((el) => {
        el.style.outline = '';
        el.removeAttribute('data-hlsdl-to');
      });

      const bang = episodeTitles().map((ten) => {
        const el = clickableFor(ten);
        if (!el) return { tap: ten, bam: '(khong tim thay)', canhBao: 'khong co the nao' };

        const o = el.getBoundingClientRect();
        const laNut = /^(a|button)$/i.test(el.tagName)
          || el.getAttribute('role') === 'button'
          || typeof el.onclick === 'function';
        let canhBao = '';
        if (o.width < 8 || o.height < 8) canhBao = 'the gan nhu khong co kich thuoc';
        else if (!laNut) canhBao = 'khong phai the bam duoc ro rang';

        if (to) {
          el.style.outline = canhBao ? '3px solid #f60' : '2px solid #0c0';
          el.setAttribute('data-hlsdl-to', '1');
        }
        return {
          tap: ten,
          bam: taThe(el),
          href: el.href ? el.href.slice(-40) : '',
          rong: Math.round(o.width),
          cao: Math.round(o.height),
          canhBao,
        };
      });

      console.table(bang);
      const ngo = bang.filter((r) => r.canhBao);
      const rieng = new Set(bang.map((r) => r.bam + '|' + r.href)).size;
      console.log(`${bang.length} tap -> ${rieng} the khac nhau`
        + (rieng < bang.length ? '  <- CO THE TRUNG NHAU, xem ky' : '  (khong trung)'));
      console.log(ngo.length
        ? `${ngo.length} muc dang ngo - xem cot canhBao`
        : 'Khong muc nao dang ngo');
      if (to) console.log('Da to vien: xanh = on, cam = dang ngo. Go HLS.probeClicks() de xoa vien.');
      return bang;
    },

    /**
     * Cuon cho muc luc hien HET cac tap (trang chi tai dan khi cuon toi).
     * Dung rieng de dem thu xem co du so tap khong truoc khi chay HLS.auto().
     */
    async loadAll({ den = 0, maxVong = 400 } = {}) {
      let truoc = -1;
      let yen = 0;
      // 6 vong x 1000ms: mang khuc khuyu mot nhip khong lam no tuong la het tap
      for (let i = 0; i < maxVong && yen < 6; i++) {
        scrollers().forEach((el) => { el.scrollTop = el.scrollHeight; });
        window.scrollTo(0, document.body.scrollHeight);
        await sleep(1000);
        const titles = episodeTitles();
        const n = titles.length;

        // da cuon toi tap can lay roi thi thoi, khong cuon het 1000+ tap lam gi
        if (den && titles.some((t) => numOf(t) >= den)) {
          console.log(`  ...${n} tap - da thay tap ${den}, dung cuon`);
          break;
        }
        if (n === truoc) { yen += 1; } else { yen = 0; console.log(`  ...${n} tap`); }
        truoc = n;
      }
      const titles = episodeTitles().sort((a, b) => numOf(a) - numOf(b));
      const so = titles.map(numOf);
      console.log(`%cTim thay ${titles.length} tap`, 'color:#0c0;font-weight:bold',
        titles.length ? `(E${so[0]} -> E${so[so.length - 1]})` : '');
      return titles;
    },

    /**
     * Tu dong bam phat lan luot TAT CA cac tap va bat link tung tap.
     * Tap nao da bat duoc roi thi bo qua, nen dut giua chung cu goi lai.
     *
     *   await HLS.auto()          // roi cuoi cung: HLS.save()
     */
    async auto({ tu = 0, den = 0, waitMs = 25000, nghi = 900, toiDa = 100, dungSauNLoi = 3 } = {}) {
      const all = await this.loadAll({ den });
      if (!all.length) return console.warn('khong thay tap nao - thu HLS.probe()');

      const titles = all.filter((t) => {
        const n = numOf(t);
        return n !== null && (!tu || n >= tu) && (!den || n <= den);
      });

      // Chan chay vo toi va: bo truyen nay hon 1000 tap, bam het se mat vai tieng
      // va tai ve hang tram GB. Phai noi ro muon lay tu dau den dau.
      if (titles.length > toiDa) {
        console.warn(
          `%cCo ${titles.length} tap - qua nhieu de chay mot lan.%c\n`
          + `Hay noi ro khoang can lay, vi du:\n`
          + `  await HLS.auto({ tu: 1, den: 38 })\n`
          + `Hoac nang tran neu that su muon: await HLS.auto({ tu: 1, den: ${titles.length}, toiDa: ${titles.length} })`,
          'color:#f60;font-weight:bold', 'color:inherit');
        return 0;
      }

      const so = titles.map(numOf);
      console.log(`%cSe lay ${titles.length} tap: E${so[0]} -> E${so[so.length - 1]}`,
        'color:#0c0;font-weight:bold');

      const hong = [];
      let loiLienTiep = 0;
      for (let i = 0; i < titles.length; i++) {
        const title = titles[i];
        const nhan = `[${i + 1}/${titles.length}]`;

        // so sanh bang SO TAP, khong bang chuoi ten - chuoi de lech
        const num = numOf(title);
        if ([...playlists.values()].some((v) => v.index === num)) {
          console.log(`${nhan} bo qua (da co): ${title}`);
          continue;
        }
        const el = clickableFor(title);
        if (!el) {
          console.warn(`${nhan} khong tim thay cho bam: ${title}`);
          hong.push(title);
          continue;
        }

        const truoc = playlists.size;
        el.scrollIntoView({ block: 'center' });
        await sleep(250);
        lastClicked = title;          // chot ten truoc khi bam, khoi doan lai
        el.click();

        const duoc = await waitUntil(() => playlists.size > truoc, waitMs);
        await sleep(nghi);

        if (duoc) {
          loiLienTiep = 0;
        } else {
          console.warn(`${nhan} khong phat duoc: ${title} (nhieu kha nang la tap tra phi)`);
          hong.push(title);
          loiLienTiep += 1;
          // dong hop thoai moi mua goi neu no vua hien ra, khong thi cu bam tiep
          document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
          await sleep(400);

          // Tap free nam lien nhau o dau, tra phi nam sau. May tap lien tiep
          // khong phat duoc = da qua ranh gioi -> dung, khoi doi vo ich.
          if (loiLienTiep >= dungSauNLoi) {
            console.warn(`%cDung lai: ${loiLienTiep} tap lien tiep khong phat duoc.%c\n`
              + 'Nhieu kha nang het phan mien phi tu day tro di.',
              'color:#f60;font-weight:bold', 'color:inherit');
            break;
          }
        }

        if (!episodeNodes().length) {
          console.warn('Muc luc bien mat sau khi bam - dung lai. Quay ve trang tac pham roi goi lai HLS.auto()');
          break;
        }
      }

      const daCo = [...playlists.values()].map((v) => v.index).sort((a, b) => a - b);
      console.log(`%cXong: ${daCo.length} tap da co link`, 'color:#0c0;font-weight:bold',
        daCo.length ? `(E${daCo[0]} -> E${daCo[daCo.length - 1]})` : '');
      if (hong.length) console.log(`${hong.length} tap khong lay duoc:`, hong);
      console.log('Gio go: HLS.save()');
      return daCo.length;
    },

    /** Them URL bang tay (copy tu tab Network). HLS.add('https://.../x.m3u8') */
    add(url, title) {
      if (!url) return console.warn('thieu url');
      const before = playlists.size;
      addPlaylist(new URL(url, location.href).href);
      if (playlists.size === before) return console.warn('url nay da co roi');
      if (title) {
        [...playlists.values()][playlists.size - 1].title = title;
        console.log('  ten =', title);
      }
    },

    /** Mang URL day du - go  copy(HLS.urls())  de chep vao clipboard. */
    urls() { return [...playlists.values()].map((v) => v.url); },

    /** Sua ten bat sai: HLS.rename(3, 'E3. The Cave') */
    rename(index, title) {
      const it = [...playlists.values()].find((v) => v.index === index);
      if (!it) return console.warn('khong co muc', index);
      it.title = title;
      console.log(`[${index}] -> ${title}`);
    },

    /** Doi ten tac pham cho tat ca (dung lam ten thu muc). */
    setSeries(name) {
      playlists.forEach((v) => { v.series = name; });
      console.log('series =', name);
    },

    /** Bo muc bat nham (quang cao, trailer...). */
    drop(index) {
      for (const [k, v] of playlists) {
        if (v.index !== index) continue;
        playlists.delete(k);
        byDir.delete(dirOf(k));
      }
      // khong danh so lai: index chinh la so tap that (E7 -> 7)
    },

    /** Tai manifest.json ve may. */
    save(filename = 'manifest.json') {
      // sap theo so tap, khong theo thu tu ban bam
      const data = [...playlists.values()].sort((a, b) => a.index - b.index);
      if (!data.length) return console.warn('chua bat duoc playlist nao - thu bam Play');
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = filename;
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 1000);
      console.log(`%cDa xuat ${data.length} tap -> ${filename}`, 'color:#0c0;font-weight:bold');
    },

    /** Cookie hien tai, dien vao COOKIE trong .env neu site can dang nhap. */
    cookie() { console.log(document.cookie); return document.cookie; },
  };

  console.log(
    '%cgrab.js v' + VERSION + ' san sang.%c\n'
    + '  await HLS.loadAll({ den: 38 })     cuon toi tap 38, dem thu\n'
    + '  await HLS.auto({ tu: 1, den: 38 }) bam lan luot tap 1..38\n'
    + '  HLS.save()                         xuat manifest.json\n'
    + '  HLS.probe()                        xem no doc ra ten gi\n'
    + 'Nen noi ro khoang (tu/den) - bo truyen dai co the hon 1000 tap.',
    'color:#0c0;font-weight:bold', 'color:inherit',
  );
})();
