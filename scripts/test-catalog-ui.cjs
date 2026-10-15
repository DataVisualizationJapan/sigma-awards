/* Run with Playwright installed and the public/ static server on port 4173. */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const base = process.env.CATALOG_TEST_URL || 'http://127.0.0.1:4173';
const entries = JSON.parse(fs.readFileSync(path.join(__dirname, '../public/data/dja/entries.json'))).entries;

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const errors = [], sourceRequests = [], localFailures = [];
  await context.route('**/*', route => {
    const url = route.request().url();
    if (!url.startsWith(base)) {
      if (/datajournalismawards|globaleditorsnetwork|web\.archive|wizehive/.test(url)) sourceRequests.push(url);
      return route.abort();
    }
    return route.continue();
  });
  const page = await context.newPage();
  page.on('pageerror', error => errors.push(error.message));
  page.on('response', response => {
    if (response.url().startsWith(base) && response.status() >= 400) localFailures.push(response.url());
  });
  async function visit(url) {
    await page.goto(`${base}${url}`);
    await page.waitForLoadState('networkidle');
    await page.locator('#card-grid .card, #empty:not([hidden])').first().waitFor();
  }
  try {
    await visit('/dja/');
    assert.equal(await page.locator('#year-chips [aria-pressed="true"]').innerText(), '2019');
    assert.equal(await page.locator('.card').count(), 24);
    assert.match(await page.locator('#result-count').innerText(), /100件/);
    await page.screenshot({ path: '/tmp/dja-desktop.png', fullPage: true });
    await page.locator('#coverage > summary').click();
    assert.equal(await page.locator('#coverage tbody tr').count(), 8);
    await page.locator('#pager [data-page="2"]').first().click();
    assert.match(page.url(), /page=2/);
    assert.match(await page.locator('#result-count').innerText(), /25–48件/);

    await visit('/dja/?year=2013');
    assert.match(await page.locator('#result-count').innerText(), /73件/);
    await page.locator('#year-chips [data-year=""]').click();
    assert.match(await page.locator('#result-count').innerText(), new RegExp(`${entries.length}件`));
    await page.locator('#q').fill('no-such-project-123456789');
    await page.locator('#empty:not([hidden])').waitFor();
    assert.equal(await page.locator('.card').count(), 0);

    const sample = entries.find(e => e.year === 2017 && e.title.startsWith('Researchers bet on'));
    const shortlisted = sample.awards.find(a => a.result === 'shortlist');
    await visit(`/dja/?year=2017&q=Researchers&category=${encodeURIComponent(shortlisted.category)}&result=winner`);
    assert.equal(await page.locator('.card').count(), 0, 'Result and category must match the same award');
    await page.locator('#result').selectOption('shortlist');
    await page.locator('.card').waitFor();
    assert.equal(await page.locator('.card').count(), 1);
    await page.reload();
    await page.waitForLoadState('networkidle');
    assert.equal(await page.locator('#category').inputValue(), shortlisted.category);

    await visit('/dja/?year=2019&kind=individual');
    assert.ok(await page.locator('.card').count() > 0);
    assert.equal(await page.locator('#kind').inputValue(), 'individual');
    await page.locator('#country').selectOption('Russia');
    assert.equal(await page.locator('.card').count(), 1);
    assert.match(page.url(), /country=Russia/);

    const hurricane = entries.find(e => e.year === 2019 && e.title === 'Hurricane Maria’s Dead');
    await visit(`/dja/?year=2019#e=${hurricane.id}`);
    await page.locator('#drawer .source-list').waitFor();
    assert.equal(await page.locator('#drawer-title').innerText(), hurricane.title);
    assert.match(await page.locator('#drawer-body').innerText(), /プエルトリコ/);
    assert.ok(await page.locator('.source-list a').count() > 0);
    assert.equal(await page.locator('#drawer-thumb').isVisible(), false);
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('#drawer').isVisible(), false);
    await page.locator('#locale-chips [data-locale="src"]').click();
    assert.match(page.url(), /locale=src/);
    await page.reload();
    await page.waitForLoadState('networkidle');
    assert.equal(await page.locator('[data-locale="src"]').getAttribute('aria-pressed'), 'true');
    await page.locator('#card-grid .card__detail').first().click();
    await page.locator('#drawer .source-list').waitFor();
    await page.locator('#drawer .source-records').waitFor();
    await page.locator('#drawer-close').focus();
    await page.keyboard.press('Shift+Tab');
    assert.notEqual(await page.evaluate(() => document.activeElement.id), 'drawer-close');
    assert.equal(await page.evaluate(() => !!document.activeElement.closest('#drawer')), true);
    await page.keyboard.press('Escape');
    assert.equal(await page.evaluate(() => document.activeElement.className), 'card__detail');

    await visit('/dja/?year=9999&page=9999');
    assert.equal(await page.locator('#year-chips [aria-pressed="true"]').innerText(), '2019');
    assert.match(await page.locator('#result-count').innerText(), /97–100件/);

    // A failed detail request must leave the card's title, awards and sources accessible.
    await page.route('**/data/dja/details-2013.json', route => route.abort());
    await visit('/dja/?year=2013');
    await page.locator('.card__detail').first().click();
    await page.getByText('詳細テキストを読み込めませんでした。', { exact: false }).waitFor();
    assert.ok(await page.locator('#drawer .source-list a').count() > 0);
    await page.keyboard.press('Escape');
    await page.unroute('**/data/dja/details-2013.json');

    await page.setViewportSize({ width: 390, height: 844 });
    await visit('/dja/?year=2018');
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await page.screenshot({ path: '/tmp/dja-mobile.png', fullPage: true });
    await page.locator('.card__detail').first().click();
    await page.locator('#drawer .source-records').waitFor();
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await page.screenshot({ path: '/tmp/dja-mobile-detail.png' });
    await page.keyboard.press('Escape');

    await page.setViewportSize({ width: 1440, height: 1000 });
    await visit('/');
    assert.equal(await page.locator('#year-chips [aria-pressed="true"]').innerText(), '2026');
    assert.ok(await page.locator('.card').count() > 0);
    await page.locator('.card__detail').first().click();
    await page.locator('#drawer-body p').first().waitFor();
    assert.equal(await page.locator('#drawer').isVisible(), true);
    await page.keyboard.press('Escape');
    await page.getByRole('link', { name: 'Data Journalism Awards', exact: true }).click();
    await page.waitForLoadState('networkidle');
    assert.equal(new URL(page.url()).pathname, '/dja/');
    assert.deepEqual(errors, []);
    assert.deepEqual(sourceRequests, []);
    assert.deepEqual(localFailures, []);
    console.log('PASS: desktop/mobile filters, same-award matching, URLs, locale, drawer, keyboard, missing details, Sigma regression; no external source requests.');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
