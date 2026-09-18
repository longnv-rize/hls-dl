/* ============================================================================
 * auto_grab.js - tu dong duyet het cac tap cua mot tac pham, bat link, xuat manifest.
 *
 * Vi sao can trinh duyet that: link video khong nam trong HTML. No chi sinh ra
 * khi player chay JS va goi request. Nen phai cho trang chay that, bam Play that,
 * roi nghe o tang network - dung viec ma grab.js lam bang tay, nhung tu dong.
 *
 * Ten file lay tu TEN TAP ("E1. Just an Old Book"), thu muc lay tu ten tac pham.
 *
 * Cau hinh: sua file .env, khong sua file nay.
 *
 * Cai dat (mot lan):
 *     npm init -y && npm i playwright
 *     npx playwright install chromium
 *
 * Chay:
 *     node auto_grab.js              (doc .env canh script)
 *     node auto_grab.js khac.env
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
  console.error('Hoac bo qua auto_grab.js va lam tay bang grab.js.');
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

const envFile = path.resolve(process.argv[2] || path.join(__dirname, '.env'));
const FILE_ENV = loadEnv(envFile);
const env = (k, d) => process.env[k] || FILE_ENV[k] || d;
const envInt = (k, d) => parseInt(env(k, d), 10) || d;

const cfg = {
  showUrls: env('SHOW_URL', env('COURSE_URL', '')).split(/[,\n]/).map((s) => s.trim()).filter(Boolean),
  episodeSelector: env('EPISODE_SELECTOR', ''),
  episodeRe: env('EPISODE_TITLE_RE', '^(E|Ep|Episode|Tap|Tập|Chuong|Chương|Chapter)\\s*\\d+\\s*[.:)\\-\\u2013]'),
  seriesSelector: env('SERIES_TITLE_SELECTOR', ''),
  playSelector: env('PLAY_SELECTOR', ''),
  profileDir: env('BROWSER_PROFILE', './browser-profile'),
  output: env('MANIFEST', './manifest.json'),
  headless: String(env('HEADLESS', 'false')).toLowerCase() === 'true',
  waitMs: envInt('WAIT_MS', 20000),
  settleMs: envInt('SETTLE_MS', 1500),
};

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const ask = (q) => new Promise((resolve) => {
  process.stdout.write(q);
  process.stdin.resume();
  process.stdin.once('data', () => { process.stdin.pause(); resolve(); });
});

/**
 * Danh dau cac tap tren trang bang data-hlsdl-ep roi tra ve danh sach.
 * Phai lam lai moi vong lap vi trang SPA co the ve lai DOM sau moi cu bam.
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
      // Tu nhan dang: chi lay the LA. Text cua ca the card cung bat dau bang
      // "E1." nhung keo theo "10:46", "4yr ago", "Play icon"...
      nodes = [...document.querySelectorAll(LEAF_SEL)]
        .filter(isLeaf)
        .filter((el) => { const t = txt(el); return t.length < 150 && re.test(t); });
    }

    // "E1. ..." -> "e|."   |   "Ep 1 - ..." -> "ep|-"
    const shapeOf = (t) => {
      const m = t.match(/^([^\s\d]+)\s*\d+\s*([.:)\-–])/);
      return m ? m[1].toLowerCase() + '|' + m[2] : '?';
    };
    const numOf = (t) => {
      const m = t.match(/^[^\s\d]*\s*(\d+)/);
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
    const seenNum = new Set();
    nodes.forEach((el) => {
      const title = txt(el);
      const n = numOf(title);
      if (!title || n === null || seenNum.has(n)) return;
      seenNum.add(n);
      // cho bam la the <a>/<button> gan nhat, khong thi chinh no
      const target = el.closest('a, button, [role="button"], li') || el;
      target.setAttribute('data-hlsdl-ep', String(out.length));
      out.push({ i: out.length, num: n, title, href: target.href || null });
    });
    out.sort((a, b) => a.num - b.num);
    return out;
  }, { sel: selector, reSrc: reSource });
}

async function readSeries(page, selector) {
  return page.evaluate((sel) => {
    const txt = (el) => (el && el.textContent ? el.textContent.trim().replace(/\s+/g, ' ') : '');
    // <h1> thuong chua CA ten tac pham lan ten tap
    // ("My Vampire System Ep 1 - Just an Old Book") -> phai cat phan ten tap di.
    const strip = (s) => s.replace(
      /\s*[-–|:]?\s*(E|Ep|Episode|Tap|Tập|Chuong|Chương|Chapter|Phan|Phần)\s*\d+\s*[.:)\-–].*$/i,
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
  if (!cfg.showUrls.length) {
    console.error('\nThieu SHOW_URL trong .env - dien URL trang tac pham roi chay lai.');
    console.error('Vi du: SHOW_URL=https://site.com/show/a2fa57d4cb8267b2645f2b588c39951fbf65093a');
    process.exit(1);
  }

  const ctx = await chromium.launchPersistentContext(path.resolve(cfg.profileDir), {
    headless: cfg.headless,
    viewport: { width: 1366, height: 900 },
    args: ['--autoplay-policy=no-user-gesture-required'],
  });
  const page = ctx.pages()[0] || (await ctx.newPage());

  // nghe network o cap context, luon bat duoc du trang co dieu huong hay khong
  let hits = [];
  page.on('request', (req) => {
    const url = req.url();
    if (PLAYLIST_RE.test(url)) hits.push(url);
  });

  await page.goto(cfg.showUrls[0], { waitUntil: 'domcontentloaded' });
  await ask('\n>>> Dang nhap xong (neu can) thi bam Enter de bat dau... ');

  const out = [];
  const failed = [];

  for (const showUrl of cfg.showUrls) {
    await page.goto(showUrl, { waitUntil: 'domcontentloaded' });
    await sleep(2000);

    // keo xuong cuoi de danh sach tap tai het (lazy load)
    for (let s = 0; s < 8; s++) {
      await page.mouse.wheel(0, 3000).catch(() => {});
      await sleep(600);
    }
    await page.evaluate(() => window.scrollTo(0, 0)).catch(() => {});
    await sleep(500);

    const series = await readSeries(page, cfg.seriesSelector);
    let episodes = await tagEpisodes(page, cfg.episodeSelector, cfg.episodeRe);
    console.log(`\n=== ${series} - ${episodes.length} tap ===`);

    if (!episodes.length) {
      console.error('Khong nhan ra tap nao. Kiem tra EPISODE_SELECTOR / EPISODE_TITLE_RE trong .env,');
      console.error('hoac dung grab.js roi go HLS.probe() de xem trang cho ra nhung ten gi.');
      failed.push({ text: showUrl });
      continue;
    }

    for (let i = 0; i < episodes.length; i++) {
      const ep = episodes[i];
      const label = `[${i + 1}/${episodes.length}]`;
      hits = [];

      try {
        if (ep.href) {
          await page.goto(ep.href, { waitUntil: 'domcontentloaded' });
        } else {
          // SPA: bam thang vao tap, trang khong dieu huong
          await page.click(`[data-hlsdl-ep="${ep.i}"]`, { timeout: 8000 });
        }
        await sleep(1200);
        await startPlayback(page);

        const deadline = Date.now() + cfg.waitMs;
        while (!hits.length && Date.now() < deadline) await sleep(250);
        await sleep(cfg.settleMs); // gom them playlist den muon

        if (!hits.length) {
          console.log(`${label} KHONG bat duoc link: ${ep.title}`);
          failed.push(ep);
        } else {
          // nhieu hit -> lay cai dai nhat, thuong la master playlist co token day du
          const url = [...hits].sort((a, b) => b.length - a.length)[0];
          // dung so tap that (E7 -> 007) de neu co tap loi thi so thu tu van dung
          out.push({ index: ep.num || i + 1, series, title: ep.title, url, page: page.url() });
          console.log(`${label} ${ep.title}`);
        }
      } catch (err) {
        console.log(`${label} LOI: ${ep.title} - ${err.message}`);
        failed.push(ep);
      }

      // quay lai trang tac pham va danh dau lai (DOM co the da doi)
      if (i + 1 < episodes.length) {
        if (page.url() !== showUrl) {
          await page.goto(showUrl, { waitUntil: 'domcontentloaded' }).catch(() => {});
          await sleep(1500);
        }
        const again = await tagEpisodes(page, cfg.episodeSelector, cfg.episodeRe);
        if (again.length >= episodes.length) episodes = again;
      }
    }
  }

  fs.writeFileSync(cfg.output, JSON.stringify(out, null, 2), 'utf8');
  console.log(`\nDa xuat ${out.length} tap -> ${cfg.output}`);
  if (failed.length) {
    console.log(`${failed.length} tap that bai (thu tang WAIT_MS, hoac lam tay bang grab.js):`);
    failed.forEach((f) => console.log('  - ' + (f.title || f.text)));
  }
  console.log('\nTiep theo:\n  python hls_dl.py        (tu doc MANIFEST va OUTPUT_DIR trong .env)');

  await ctx.close();
  process.exit(0);
})();
