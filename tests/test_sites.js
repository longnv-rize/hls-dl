/* Ho so cau hinh theo trang (sites/).
 *
 * Fixture nam trong tests/fixtures/sites/ va co ca file hong co y - de test
 * "file hong thi bo qua" la thuc chat chu khong phai gia lap.
 *
 * Chay:  node tests/test_sites.js
 */
const path = require('path');
const assert = require('assert');
const { loadProfiles, pickProfile, resolve } = require('../sites');

const FIXTURE = path.join(__dirname, 'fixtures', 'sites');
const THAT = path.join(__dirname, '..', 'sites');

let hong = 0;
function test(ten, fn) {
  try {
    fn();
    console.log(`  ok    ${ten}`);
  } catch (e) {
    hong += 1;
    console.log(`  HONG  ${ten}\n          ${e.message}`);
  }
}

// file hong in canh bao ra stderr - nuot di cho ket qua test de doc
const canhBaoCu = console.warn;
console.warn = () => {};
const ho_so = loadProfiles(FIXTURE);
console.warn = canhBaoCu;

console.log('\nNap ho so:');

test('doc duoc cac file hop le', () => {
  const ten = ho_so.map((p) => p.file).sort();
  assert.deepStrictEqual(ten, ['a-chung.json', 'b-cu-the.json', 'c-nhieu-mien.json']);
});

test('bo qua file JSON hong, khong lam chet script', () => {
  assert.ok(!ho_so.some((p) => p.file === 'd-json-hong.json'));
});

test('bo qua ho so thieu truong match', () => {
  assert.ok(!ho_so.some((p) => p.file === 'e-thieu-match.json'));
});

test('bo qua file bat dau bang _ (la mau, khong phai ho so that)', () => {
  assert.ok(!ho_so.some((p) => p.file.startsWith('_')));
});

test('thu muc khong ton tai thi tra ve mang rong', () => {
  assert.deepStrictEqual(loadProfiles(path.join(__dirname, 'khong-co-thu-muc-nay')), []);
});

console.log('\nChon ho so theo URL:');

const chon = (u) => pickProfile(ho_so, u);

test('khop dung ten mien', () => {
  assert.strictEqual(chon('https://site.com/show/abc').playSelector, '.chung');
});

test('khop ca ten mien phu', () => {
  assert.strictEqual(chon('https://www.site.com/show/abc').playSelector, '.chung');
});

test('ho so cu the thang ho so chung', () => {
  // vn.site.com khop ca hai, phai lay cai dai hon
  assert.strictEqual(chon('https://vn.site.com/show/abc').playSelector, '.cuthe');
});

test('mot ho so khai nhieu ten mien', () => {
  assert.strictEqual(chon('https://x.com/a').episodeSelector, '.ep');
  assert.strictEqual(chon('https://y.com/a').episodeSelector, '.ep');
});

test('khong trang nao khop thi tra ve null', () => {
  assert.strictEqual(chon('https://khongcotrongdanhsach.com/a'), null);
});

test('ten mien chi trung mot phan thi KHONG khop', () => {
  // "khongphaisite.com" khong duoc coi la mien phu cua "site.com"
  assert.strictEqual(chon('https://khongphaisite.com/a'), null);
});

test('URL hong thi tra ve null, khong nem loi', () => {
  assert.strictEqual(chon('day khong phai url'), null);
  assert.strictEqual(chon(''), null);
});

console.log('\nHo so that trong sites/:');

const that = loadProfiles(THAT);

test('nap duoc va khong co file nao hong', () => {
  assert.ok(that.length >= 1, 'khong nap duoc ho so nao');
});

test('moi ho so that deu co truong match', () => {
  that.forEach((p) => assert.ok(p.match, `${p.file} thieu match`));
});

test('ho so pocketfm khop dung ten mien', () => {
  const p = pickProfile(that, 'https://pocketfm.com/show/abc');
  assert.ok(p, 'khong tim thay ho so cho pocketfm.com');
  assert.strictEqual(p.file, 'pocketfm.json');
});

test('file mau _mau.json khong bao gio duoc chon', () => {
  assert.ok(!that.some((p) => p.file.startsWith('_')));
});

console.log('\nThu tu uu tien (.env > ho so > mac dinh):');

[['.env thang tat ca',        'tu-env', 'tu-ho-so', 'mac-dinh', 'tu-env'],
 ['.env rong -> lay ho so',   '',       'tu-ho-so', 'mac-dinh', 'tu-ho-so'],
 ['ca hai rong -> mac dinh',  '',       '',         'mac-dinh', 'mac-dinh'],
 ['khong co ho so',           '',       null,       'mac-dinh', 'mac-dinh'],
 ['so: .env thang',           25,       10,         5,          25],
 ['so: ho so thang mac dinh', 0,        10,         5,          10],
 ['so 0 nghia la khong dat',  0,        0,          5,          5],
 ['undefined bi bo qua', undefined, 'tu-ho-so', 'mac-dinh', 'tu-ho-so']]
  .forEach(([nhan, e, ho, d, mong]) => {
    test(nhan, () => assert.strictEqual(resolve(e, ho, d), mong));
  });

console.log(hong ? `\n${hong} test HONG\n` : '\nTat ca test deu qua\n');
process.exit(hong ? 1 : 0);
