/* ============================================================================
 * sites.js - nap ho so cau hinh theo trang tu thu muc sites/.
 *
 * Y tuong: phan DOM cua moi trang moi khac, con phan con lai thi giong nhau.
 * Thay vi nhoi tat ca vao mot bo heuristic co gang dung cho moi noi, tach rieng
 * ra moi trang mot file JSON. Them trang moi = them mot file, khong dung code.
 *
 * Thu tu uu tien:  .env  >  ho so trang  >  mac dinh trong code
 * Nguoi dung dat gi trong .env thi cai do thang, vi ho biet trang cua ho hon.
 * ==========================================================================*/
const fs = require('fs');
const path = require('path');

/** Doc het cac ho so trong thu muc. File hong thi bo qua, khong lam chet ca script. */
function loadProfiles(dir) {
  const out = [];
  if (!fs.existsSync(dir)) return out;
  for (const f of fs.readdirSync(dir).sort()) {
    // file bat dau bang _ la mau/tai lieu, khong phai ho so that
    if (!f.endsWith('.json') || f.startsWith('_')) continue;
    try {
      const p = JSON.parse(fs.readFileSync(path.join(dir, f), 'utf8'));
      if (p && p.match) out.push(Object.assign({}, p, { file: f }));
      else console.warn(`  ho so ${f} thieu truong "match" - bo qua`);
    } catch (e) {
      console.warn(`  ho so ${f} khong doc duoc: ${e.message} - bo qua`);
    }
  }
  return out;
}

/**
 * Chon ho so hop voi URL. So theo ten mien.
 * "match" khop ca ten mien phu: "pocketfm.com" khop luon "www.pocketfm.com".
 * Neu nhieu ho so cung khop thi lay cai CU THE nhat (chuoi match dai nhat),
 * de mot ho so rieng cho "vn.site.com" thang duoc ho so chung cho "site.com".
 */
function pickProfile(profiles, url) {
  let host;
  try {
    host = new URL(url).hostname.toLowerCase();
  } catch {
    return null;
  }
  let best = null;
  let bestLen = -1;
  for (const p of profiles) {
    for (const m of [].concat(p.match)) {
      const k = String(m).toLowerCase().replace(/^\./, '');
      if ((host === k || host.endsWith('.' + k)) && k.length > bestLen) {
        best = p;
        bestLen = k.length;
      }
    }
  }
  return best;
}

/**
 * Chot mot gia tri theo thu tu:  .env  >  ho so trang  >  mac dinh.
 *
 * Coi chuoi rong va 0 la "khong dat", vi ca hai nguon deu la van ban: mot khoa
 * de trong trong .env hay mot so 0 trong ho so deu co nghia la "dung mac dinh",
 * chu khong phai "dat thanh rong" hay "dat thanh 0".
 */
function resolve(tuEnv, tuHoSo, macDinh) {
  const co = (v) => v !== undefined && v !== null && v !== '' && v !== 0;
  if (co(tuEnv)) return tuEnv;
  if (co(tuHoSo)) return tuHoSo;
  return macDinh;
}

module.exports = { loadProfiles, pickProfile, resolve };
