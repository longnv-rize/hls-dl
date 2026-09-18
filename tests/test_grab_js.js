/* Nhan dien ten tap trong grab.js.
 *
 * Du lieu test lay tu mot lan chay that tren trang, khong phai bia ra - do la
 * ly do no bat duoc may loi that: muc luc lan ca header vao, va ten tap viet
 * "EP-36" co gach noi trong khi cho khac viet "EP 2".
 *
 * Chay:  node tests/test_grab_js.js
 */
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const GOC = path.join(__dirname, '..');
const src = fs.readFileSync(path.join(GOC, 'grab.js'), 'utf8');

/** Trich mot khai bao const tu grab.js de test dung code that, khong go lai. */
function trich(ten) {
  const khoi = src.match(new RegExp('  const ' + ten + ' = [\\s\\S]*?\\n  \\};', 'm'));
  if (khoi) return khoi[0];
  const dong = src.match(new RegExp('  const ' + ten + ' = .*?;$', 'm'));
  if (dong) return dong[0];
  throw new Error('khong trich duoc ' + ten + ' tu grab.js');
}

// eslint-disable-next-line no-eval
eval(['EPISODE_RE', 'NGAN', 'TU_TAP', 'shapeOf', 'numOf', 'pickEpisodes',
  'episodeNumIn', 'stripEpisode', 'dirOf', 'demLyDoLoai']
  .map(trich).join('\n').replace(/\bconst /g, 'var '));

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

// --- du lieu that tu mot lan chay tren trang --------------------------------
const MUC_LUC_THAT = [
  'Ep 1 - Just an Old Book',      // header, lap 2 lan
  'Ep 1 - Just an Old Book',
  'E1. Just an Old Book', 'E2. Daily Quest', 'E3. Military School',
  'E4. Ability Level', 'E5. No Ability', 'E6. Result', 'E7. Same Ability',
  'E8. Fate', 'E9. What system?', 'E10. New Quest', 'E11. New Skill',
  'E12. A second test', 'E13. School hierarchy', 'E14. Unwritten rules',
  'E15. Finding my next target', 'E16. A new look', 'E17. Level up',
  'E18. Im a Vampire', 'E19. Running out of time!', 'E20. A Problem',
];

console.log('\nLoc muc luc tap:');

test('22 muc that -> 20 tap, loai header', () => {
  const ra = pickEpisodes(MUC_LUC_THAT);
  assert.strictEqual(ra.length, 20);
  assert.strictEqual(ra[0], 'E1. Just an Old Book');
  assert.strictEqual(ra[19], 'E20. A Problem');
  assert.ok(!ra.some((t) => t.startsWith('Ep ')), 'con sot header');
});

test('nhom dong nhat thang, khong phai nhom dau tien', () => {
  // header dung truoc trong DOM nhung it hon -> phai bi bo
  const ra = pickEpisodes(['Ep 9 - X', 'E1. A', 'E2. B', 'E3. C']);
  assert.deepStrictEqual(ra, ['E1. A', 'E2. B', 'E3. C']);
});

test('trung so tap thi chi giu mot', () => {
  assert.strictEqual(pickEpisodes(['E1. A', 'E1. A', 'E2. B']).length, 2);
});

console.log('\nNhan dien dong nao la ten tap:');
[['E1. Just an Old Book', true],
  ['E10. Blood Moon', true],
  ['Ep 2 - The Awakening', true],
  ['Episode 3: Trial', true],
  ['Tập 4. Khởi đầu', true],
  ['My Vampire System', false],
  ['1.5B plays', false],
  ['Every day', false],
  ['E1', false]].forEach(([chuoi, mong]) => {
  test(`${mong ? 'nhan   ' : 'bo qua '} ${JSON.stringify(chuoi)}`, () => {
    assert.strictEqual(EPISODE_RE.test(chuoi), mong);
  });
});

console.log('\nCat ten tap khoi ten tac pham:');
[['My Vampire System EP-36 Escape', 'My Vampire System'],   // ca tung gay loi that
  ['My Vampire System EP 2 - Daily Quest', 'My Vampire System'],
  ['My Vampire System - E1. Just an Old Book', 'My Vampire System'],
  ['My Vampire System', 'My Vampire System'],
  ['Tuyệt Đỉnh – Tập 4. Khởi đầu', 'Tuyệt Đỉnh']]
  .forEach(([vao, mong]) => {
    test(JSON.stringify(vao), () => assert.strictEqual(stripEpisode(vao), mong));
  });

console.log('\nMoc so tap ra khoi chuoi bat ky:');
[['My Vampire System EP-36 Escape', 36],   // gach noi, khong phai khoang trang
  ['My Vampire System EP 2 - Daily Quest', 2],
  ['E10. New Quest', 10],
  ['E.7 Something', 7],
  ['My Vampire System', null],
  ['1.5B plays', null]].forEach(([vao, mong]) => {
  test(`${JSON.stringify(vao)} -> ${mong}`, () => {
    assert.strictEqual(episodeNumIn(vao), mong);
  });
});

console.log('\nChi giu master playlist, bo playlist con:');
test('nhieu url mot tap -> gom con mot theo thu muc', () => {
  const CDN = 'https://cdn.example';
  const A = 'a'.repeat(40);
  const B = 'b'.repeat(40);
  const urls = [
    `${CDN}/${A}/Default/QVBR/${A}.m3u8`,        // master tap A
    `${CDN}/${A}/Default/QVBR/${A}_1.m3u8`,      // con
    `${CDN}/${B}/Default/QVBR/${B}.m3u8`,        // master tap B
    `${CDN}/${B}/Default/QVBR/${B}_audio.m3u8`,  // con
  ];
  const giu = new Map();
  urls.forEach((u) => { if (!giu.has(dirOf(u))) giu.set(dirOf(u), u); });
  assert.strictEqual(giu.size, 2);
  assert.ok([...giu.values()].every((u) => /\/[0-9a-z]{40}\.m3u8$/.test(u)),
    'giu nham playlist con');
});

test('bo qua tham so query khi so thu muc', () => {
  assert.strictEqual(dirOf('https://cdn/x/y/z.m3u8?token=abc'), 'https://cdn/x/y/');
});

console.log('');
console.log('So tap khi co tien to mua:');
[['E7. Ten', 7],
 ['S2E5. Ten', 5],        // so dau la MUA, so sau moi la tap
 ['S2 E5. Ten', 5],
 ['2x05 Ten', 5],
 ['E10. Ten', 10],
 ['Prologue', null],      // khong co so -> bi loai, nhung co dem lai
].forEach(([s, mong]) => {
  test(`${JSON.stringify(s)} -> ${mong}`, () => assert.strictEqual(numOf(s), mong));
});

console.log('');
console.log('Dem cac muc bi loai va ly do:');
test('tach rieng "khong co so" va "trung so"', () => {
  const vao = ['E1. A', 'E2. B', 'E2. Trung', 'Prologue', 'Ngoai truyen'];
  assert.strictEqual(pickEpisodes(vao).length, 2);
  const d = demLyDoLoai(vao);
  assert.strictEqual(d.trung, 1, 'phai dem duoc 1 muc trung so');
  assert.strictEqual(d.khongSo, 2, 'phai dem duoc 2 muc khong co so');
});

console.log(hong ? `\n${hong} test HONG\n` : '\nTat ca test deu qua\n');
process.exit(hong ? 1 : 0);
