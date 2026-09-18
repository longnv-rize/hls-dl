/* ============================================================================
 * auto_grab.js - dien SHOW_URL vao .env, chay mot lenh, ra manifest.json.
 *
 * Lam dung viec ma grab.js lam bang tay, nhung khong can ban ngoi bam:
 * mo trinh duyet that, cuon cho muc luc hien ra, bam phat tung tap, nghe o
 * tang network de bat link .m3u8 ngay khoanh khac player goi.
 *
 * Vi sao phai lam vay: link video KHONG nam trong HTML. No chi sinh ra khi
 * player chay JS va goi request.
 *
 * Cau hinh: sua .env, khong sua file nay.
 *
 * Cai dat (mot lan):
 *     npm init -y && npm i playwright
 *     npx playwright install chromium
 *
 * Chay:
 *     node auto_grab.js            (doc .env canh script)
 *     node auto_grab.js khac.env
 *
 * Lan dau trinh duyet dung lai cho ban DANG NHAP bang tay. Phien luu vao
 * BROWSER_PROFILE nen lan sau khoi lam lai.
 * ==========================================================================*/
const fs = require('fs');
const path = require('path');

let chromium;
try {
  ({ chromium } = require('playwright'));
} catch {
  console.error('Chua cai Playwright. Chay 2 lenh nay trong thu muc hls-dl:\n');
  console.error('  npm init -y && npm i playwright');
  console.error('  npx playwright install chromium\n');
  console.error('Hoac bo qua file nay va lam tay bang grab.js.');
  process.exit(1);
}

const PLAYLIST_RE = /\.m3u8(\?|$)|[?&](format|type)=m3u8|\/manifest(\/|\?|$)/i;

/** Doc .env, khong can thu vien ngoai. Bien moi truong that duoc uu tien hon. */
function loadEnv(file) {
  const out = {};
  if (!fs.existsSync(file)) return out;
  for (let line of fs.readFileSync(file, 'utf8').split(/\r?\n/)) {
    line = line.trim();
    if (!line || line.startsWith('#')) continue;
    if (line.startsWith('export ')) line = line.slice(7).trim();
    const i = line.indexOf('=');
    if (i < 0) continue;
    const key = line.slice(0, i).trim();
    let val = line.slice(i + 1).trim();
    if (val.length >= 2 && val[0] === val[val.length - 1] && (val[0] === '"' || val[0] === "'")) {
      val = val.slice(1, -1);
    }
    if (val) out[key] = val;
  }
  return out;
}

const { loadProfiles, pickProfile, resolve } = require('./sites');

// Giua chu va so co the la khoang trang, gach noi hoac dau cham: "EP 2",
// "EP-36", "E.7", "E36". Chi nhan khoang trang thi "EP-36" bi truot.
const EP_RE_MAC_DINH =
  '^(E|Ep|Episode|Tap|Tập|Chuong|Chương|Chapter|Phan|Phần)[\\s\\-\\u2013.]*\\d+\\s*[.:)\\-\\u2013]';

const envFile = path.resolve(process.argv[2] || path.join(__dirname, '.env'));
const FILE_ENV = loadEnv(envFile);
const env = (k, d) => process.env[k] || FILE_ENV[k] || d;
const envInt = (k, d) => (parseInt(env(k, ''), 10) || d);

const showUrls = env('SHOW_URL', env('COURSE_URL', ''))
  .split(/[,\n]/).map((s) => s.trim()).filter(Boolean);

// Ho so cua trang: chi dien nhung gi auto-nhan-dang lam sai. Xem sites/_mau.json
const profiles = loadProfiles(path.join(__dirname, 'sites'));
const prof = showUrls.length ? pickProfile(profiles, showUrls[0]) : null;

// Thu tu uu tien: .env > ho so trang > mac dinh trong code
const pick = (envKey, profKey, macDinh) =>
  resolve(env(envKey, ''), prof && prof[profKey], macDinh);
const pickInt = (envKey, profKey, macDinh) =>
  resolve(envInt(envKey, 0), prof && parseInt(prof[profKey], 10), macDinh);

const cfg = {
  showUrls,
  episodeSelector: pick('EPISODE_SELECTOR', 'episodeSelector', ''),
  episodeRe: pick('EPISODE_TITLE_RE', 'episodeRe', EP_RE_MAC_DINH),
  seriesSelector: pick('SERIES_TITLE_SELECTOR', 'seriesTitleSelector', ''),
  playSelector: pick('PLAY_SELECTOR', 'playSelector', ''),
  profileDir: env('BROWSER_PROFILE', './browser-profile'),
  output: env('MANIFEST', './manifest.json'),
  headless: String(env('HEADLESS', 'false')).toLowerCase() === 'true',
  waitMs: pickInt('WAIT_MS', 'waitMs', 25000),
  settleMs: envInt('SETTLE_MS', 1200),
  from: envInt('FROM_EP', 0),
  to: envInt('TO_EP', 0),
  maxEp: envInt('MAX_EP', 100),
  stopAfterFails: pickInt('STOP_AFTER_FAILS', 'stopAfterFails', 3),
};

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const ask = (q) => new Promise((resolve) => {
  process.stdout.write(q);
  process.stdin.resume();
  process.stdin.once('data', () => { process.stdin.pause(); resolve(); });
});

const numOf = (t) => {
  const m = String(t).match(/^[^\s\d]*[\s\-–.]*(\d+)/);
  return m ? parseInt(m[1], 10) : null;
};

/** Thu muc chua file - cac playlist cua CUNG mot tap nam chung mot thu muc. */
const dirOf = (u) => u.split('?')[0].replace(/\/[^/]*$/, '/');

/**
 * Danh dau cac tap tren trang bang data-hlsdl-ep roi tra ve danh sach.
 * Phai lam lai moi vong vi trang SPA co the ve lai DOM sau moi cu bam.
 */
async function tagEpisodes(page, selector, reSource) {
  return page.evaluate(({ sel, reSrc }) => {
    const LEAF_SEL = 'span, h1, h2, h3, h4, p, li, a, div';
    const re = new RegExp(reSrc, 'i');
    const txt = (el) => (el && el.textContent ? el.textContent.trim().replace(/\s+/g, ' ') : '');
    const isLeaf = (el) => el && el.querySelector && !el.querySelector(LEAF_SEL);

    let nodes;
    if (sel) {
      nodes = [...document.querySelectorAll(sel)];
    } else {
      // Chi lay the LA. Text cua ca the card cung bat dau bang "E1." nhung keo
      // theo "10:46", "4yr ago", "Play icon"...
      nodes = [...document.querySelectorAll(LEAF_SEL)]
        .filter(isLeaf)
        .filter((el) => { const t = txt(el); return t.length < 150 && re.test(t); });
    }

    const shapeOf = (t) => {
      const m = t.match(/^([^\s\d]+)[\s\-–.]*\d+\s*([.:)\-–])/);
      return m ? m[1].toLowerCase() + '|' + m[2] : '?';
    };
    const numIn = (t) => {
      const m = t.match(/^[^\s\d]*[\s\-–.]*(\d+)/);
      return m ? parseInt(m[1], 10) : null;
    };

    // Trang co ca header ("Ep 1 - ...") lan muc luc ("E1. ..."). Nhom dong nhat
    // ve dinh dang va dong nhat ve so luong la muc luc; nhom le la header -> bo.
    if (!sel) {
      const byShape = new Map();
      nodes.forEach((el) => {
        const s = shapeOf(txt(el));
        byShape.set(s, [...(byShape.get(s) || []), el]);
      });
      let best = [];
      byShape.forEach((group) => { if (group.length > best.length) best = group; });
      nodes = best;
    }

    const out = [];
    const seen = new Set();
    nodes.forEach((el) => {
      const title = txt(el);
      const n = numIn(title);
      if (!title || n === null || seen.has(n)) return;
      seen.add(n);
      const target = el.closest('a, button, [role="button"], li') || el;
      target.setAttribute('data-hlsdl-ep', String(out.length));
      out.push({ i: out.length, num: n, title, href: target.href || null });
    });
    out.sort((a, b) => a.num - b.num);
    return out;
  }, { sel: selector, reSrc: reSource });
}

/** Cuon cho muc luc hien het (hoac hien toi tap `den` thi dung). */
async function loadAll(page, den) {
  let truoc = -1;
  let yen = 0;
  let eps = [];
  for (let i = 0; i < 400 && yen < 6; i++) {
    await page.evaluate(() => {
      window.scrollTo(0, document.body.scrollHeight);
      // muc luc co the nam trong mot khung cuon rieng, khong phai window
      document.querySelectorAll('*').forEach((el) => {
        const st = getComputedStyle(el);
        if (/(auto|scroll)/.test(st.overflowY) && el.scrollHeight > el.clientHeight + 50) {
          el.scrollTop = el.scrollHeight;
        }
      });
    }).catch(() => {});
    await sleep(1000);

    eps = await tagEpisodes(page, cfg.episodeSelector, cfg.episodeRe);
    if (den && eps.some((e) => e.num >= den)) {
      console.log(`  ...${eps.length} tap - da thay tap ${den}, dung cuon`);
      break;
    }
    if (eps.length === truoc) { yen += 1; } else { yen = 0; console.log(`  ...${eps.length} tap`); }
    truoc = eps.length;
  }
  return eps;
}

async function readSeries(page, selector) {
  return page.evaluate((sel) => {
    const txt = (el) => (el && el.textContent ? el.textContent.trim().replace(/\s+/g, ' ') : '');
    // <h1> thuong chua CA ten tac pham lan ten tap ("My Vampire System EP-36
    // Escape") -> phai cat phan ten tap. Khong doi hoi dau cau ngay sau so.
    const strip = (s) => s.replace(
      /\s*[-–|:]?\s*\b(E|Ep|Episode|Tap|Tập|Chuong|Chương|Chapter|Phan|Phần)[\s\-–.]*\d+\b.*$/i,
      '').trim();

    if (sel) {
      const t = strip(txt(document.querySelector(sel)));
      if (t) return t;
    }
    const card = document.querySelector('[aria-label][class*="hero"], a[href^="/show/"][aria-label]');
    if (card && card.getAttribute('aria-label')) return strip(card.getAttribute('aria-label').trim());
    for (const s of ['h1', 'h2']) {
      const t = strip(txt(document.querySelector(s)));
      if (t && t.length < 150) return t;
    }
    return strip(document.title.split(/[|–]/)[0].trim());
  }, selector);
}

/** Bam Play: uu tien PLAY_SELECTOR, khong thi goi .play() tren <video>. */
async function startPlayback(page) {
  if (cfg.playSelector) {
    const btn = page.locator(cfg.playSelector).first();
    if (await btn.count()) {
      await btn.click({ timeout: 5000 }).catch(() => {});
      return;
    }
  }
  await page.evaluate(() => {
    const v = document.querySelector('video');
    if (v) { v.muted = true; const p = v.play(); if (p) p.catch(() => {}); }
  }).catch(() => {});
}

(async () => {
  console.log(`Doc cau hinh: ${envFile}`);
  if (prof) {
    const dien = ['episodeSelector', 'episodeRe', 'seriesTitleSelector', 'playSelector']
      .filter((k) => prof[k]);
    console.log(`Ho so trang: sites/${prof.file}`
      + (dien.length ? ` (dat: ${dien.join(', ')})` : ' (chi dung mac dinh)'));
  } else if (showUrls.length) {
    console.log('Ho so trang: khong co - dung auto-nhan-dang.'
      + ' Sai o dau thi chep sites/_mau.json thanh ho so rieng.');
  }
  if (!cfg.showUrls.length) {
    console.error('\nThieu SHOW_URL trong .env. Vi du:');
    console.error('  SHOW_URL=https://pocketfm.com/show/<ma-show>');
    process.exit(1);
  }

  const ctx = await chromium.launchPersistentContext(path.resolve(cfg.profileDir), {
    headless: cfg.headless,
    viewport: { width: 1366, height: 900 },
    args: ['--autoplay-policy=no-user-gesture-required'],
  });
  const page = ctx.pages()[0] || (await ctx.newPage());

  // Nghe o tang network: bat duoc moi request, ke ca cai fetch/XHR hook bo sot.
  let hits = [];
  page.on('request', (req) => {
    const url = req.url();
    if (PLAYLIST_RE.test(url)) hits.push(url);
  });

  await page.goto(cfg.showUrls[0], { waitUntil: 'domcontentloaded' });
  await ask('\n>>> Dang nhap xong (neu can) thi bam Enter de bat dau... ');

  const out = [];
  const hong = [];
  const daCoDir = new Set();  // thu muc da lay -> khong lay playlist con cua no

  for (const showUrl of cfg.showUrls) {
    await page.goto(showUrl, { waitUntil: 'domcontentloaded' });
    await sleep(2000);

    const eps0 = await loadAll(page, cfg.to);
    const series = await readSeries(page, cfg.seriesSelector);

    let eps = eps0.filter((e) => (!cfg.from || e.num >= cfg.from) && (!cfg.to || e.num <= cfg.to));
    if (!eps.length) {
      console.error(`\n${series}: khong nhan ra tap nao.`);
      console.error('Kiem tra EPISODE_SELECTOR / EPISODE_TITLE_RE trong .env, hoac dan grab.js');
      console.error('vao Console roi go HLS.probe() de xem trang cho ra nhung ten gi.');
      hong.push({ title: showUrl });
      continue;
    }

    // Bo dai co the hon 1000 tap. Khong gioi han thi chay vai tieng, tai hang tram GB.
    if (eps.length > cfg.maxEp) {
      console.error(`\n${series}: ${eps.length} tap - qua nhieu de chay mot lan.`);
      console.error(`Dat khoang trong .env, vi du FROM_EP=1 va TO_EP=${cfg.maxEp},`);
      console.error(`hoac nang MAX_EP neu that su muon lay het.`);
      continue;
    }

    console.log(`\n=== ${series} - lay ${eps.length} tap (E${eps[0].num} -> E${eps[eps.length - 1].num}) ===`);

    let loiLienTiep = 0;
    for (let i = 0; i < eps.length; i++) {
      const ep = eps[i];
      const nhan = `[${i + 1}/${eps.length}]`;
      hits = [];

      try {
        if (ep.href) {
          await page.goto(ep.href, { waitUntil: 'domcontentloaded' });
        } else {
          await page.click(`[data-hlsdl-ep="${ep.i}"]`, { timeout: 8000 });
        }
        await sleep(1200);
        await startPlayback(page);

        const het = Date.now() + cfg.waitMs;
        while (!hits.length && Date.now() < het) await sleep(250);
        await sleep(cfg.settleMs);

        // Moi tap sinh ra master playlist + vai playlist con, tat ca cung mot
        // thu muc. Master duoc goi TRUOC -> lay cai dau tien, bo phan con lai.
        const moi = hits.filter((u) => !daCoDir.has(dirOf(u)));
        if (!moi.length) {
          console.warn(`${nhan} khong phat duoc: ${ep.title} (nhieu kha nang la tap tra phi)`);
          hong.push(ep);
          loiLienTiep += 1;
          await page.keyboard.press('Escape').catch(() => {});
          await sleep(400);
          // Tap free nam lien nhau o dau. May tap lien tiep khong phat duoc
          // = da qua ranh gioi tra phi -> dung, khoi doi vo ich.
          if (loiLienTiep >= cfg.stopAfterFails) {
            console.warn(`Dung: ${loiLienTiep} tap lien tiep khong phat duoc - het phan mien phi.`);
            break;
          }
        } else {
          const url = moi[0];
          daCoDir.add(dirOf(url));
          out.push({ index: ep.num, series, title: ep.title, url, page: page.url() });
          console.log(`${nhan} E${ep.num}. ${ep.title.replace(/^[^\s]*\s*/, '')}`.slice(0, 90));
          loiLienTiep = 0;
        }
      } catch (err) {
        console.log(`${nhan} LOI: ${ep.title} - ${err.message}`);
        hong.push(ep);
        loiLienTiep += 1;
      }

      // Quay lai trang tac pham va danh dau lai (DOM co the da doi).
      if (i + 1 < eps.length && page.url() !== showUrl) {
        await page.goto(showUrl, { waitUntil: 'domcontentloaded' }).catch(() => {});
        await sleep(1500);
        const lai = await tagEpisodes(page, cfg.episodeSelector, cfg.episodeRe);
        const map = new Map(lai.map((e) => [e.num, e]));
        eps = eps.map((e) => map.get(e.num) || e);
      }
    }
  }

  out.sort((a, b) => a.index - b.index);
  fs.writeFileSync(cfg.output, JSON.stringify(out, null, 2), 'utf8');

  console.log(`\nDa xuat ${out.length} tap -> ${cfg.output}`
    + (out.length ? `  (E${out[0].index} -> E${out[out.length - 1].index})` : ''));
  if (hong.length) {
    console.log(`${hong.length} tap khong lay duoc:`);
    hong.slice(0, 10).forEach((f) => console.log('  - ' + (f.title || f.text)));
  }
  console.log('\nTiep theo:\n  python hls_dl.py');

  await ctx.close();
  process.exit(0);
})();
