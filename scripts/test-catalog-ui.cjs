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
    const imageRatio = await page.locator('.card__thumb').first().evaluate(img => img.getBoundingClientRect().width / img.getBoundingClientRect().height);
    assert.ok(Math.abs(imageRatio - 1.6) < 0.02, 'Card image should retain the 16:10 layout');
    await page.screenshot({ path: '/tmp/dja-desktop.png' });
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
    assert.equal(await page.locator('#drawer-thumb').isVisible(), Boolean(hurricane.thumb));
    if (hurricane.thumb) {
      await page.locator('#drawer-thumb').evaluate(img => img.decode());
      assert.ok(await page.locator('#drawer-thumb').evaluate(img => img.naturalWidth > 0));
    }
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
    const firstId = await page.locator('#card-grid .card').first().getAttribute('data-id');
    assert.equal(await page.locator('#drawer-thumb').isVisible(), Boolean(entries.find(e => e.id === firstId).thumb));
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
    assert.ok(await page.locator('.card__thumb').count() > 0);
    await page.locator('.card__thumb').first().evaluate(img => img.decode());
    await page.screenshot({ path: '/tmp/dja-mobile.png', fullPage: true });
    await page.locator('.card__detail').first().click();
    await page.locator('#drawer .source-records').waitFor();
    await page.locator('#drawer-thumb').evaluate(img => img.decode());
    assert.ok(await page.locator('#drawer-thumb').evaluate(img => img.naturalWidth > 0));
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

    // Entry-page links: cards link to entry pages, the drawer shows the entry URL, and the catalog URL is restored.
    for (const [prefix, query] of [['', '?year=2024&result=winner&page=2'], ['/dja', '?year=2019&page=2']]) {
      const root = prefix ? `${prefix}/` : '/';
      await visit(`${root}${query}`);
      const first = page.locator('#card-grid .card').first();
      const id = await first.getAttribute('data-id');
      const expected = `${prefix}/entries/${id}/`;
      assert.equal(await first.locator('.card__link').getAttribute('href'), expected);
      assert.equal(await first.locator('.card__detail').getAttribute('href'), expected);
      const listPath = new URL(page.url()).pathname + new URL(page.url()).search;
      await first.locator('.card__detail').click();
      await page.locator('#drawer-body h3').first().waitFor();
      assert.equal(new URL(page.url()).pathname + new URL(page.url()).search + new URL(page.url()).hash, expected);
      assert.ok((await page.locator('#drawer-body').innerText()).length > 50, 'Detail text should load');
      const hasThumb = await page.locator('#drawer-thumb').isVisible();
      if (hasThumb) {
        await page.locator('#drawer-thumb').evaluate(img => img.decode());
        assert.ok(await page.locator('#drawer-thumb').evaluate(img => img.naturalWidth > 0));
      }
      await page.keyboard.press('Escape');
      assert.equal(new URL(page.url()).pathname + new URL(page.url()).search + new URL(page.url()).hash, listPath);
      // Title link opens the drawer too.
      await first.locator('.card__link').click();
      await page.locator('#drawer').waitFor({ state: 'visible' });
      assert.equal(new URL(page.url()).pathname, expected);
      await page.locator('#drawer-close').click();
      assert.equal(new URL(page.url()).pathname + new URL(page.url()).search, listPath);
      // Direct #e= still opens the drawer.
      await page.goto(`${base}${root}#e=${id}`);
      await page.locator('#drawer').waitFor({ state: 'visible' });
      assert.equal(new URL(page.url()).pathname + new URL(page.url()).hash, expected);
      await page.keyboard.press('Escape');
      assert.equal(new URL(page.url()).pathname, root);
      assert.equal(new URL(page.url()).hash, '');
    }

    // Language switch while the drawer is open keeps the entry path; closing restores the new catalog URL.
    await visit('/dja/?year=2019');
    const switchId = await page.locator('#card-grid .card').first().getAttribute('data-id');
    await page.locator('#card-grid .card__detail').first().click();
    await page.locator('#drawer-body p').first().waitFor();
    await page.locator('#locale-chips [data-locale="src"]').evaluate(el => el.click());
    assert.equal(new URL(page.url()).pathname + new URL(page.url()).search, `/dja/entries/${switchId}/`);
    await page.keyboard.press('Escape');
    assert.match(page.url(), /\/dja\/\?.*locale=src/);

    // Keyboard: Tab to the detail link, Enter opens, Escape closes and returns focus.
    await visit('/');
    await page.locator('#card-grid .card__detail').first().focus();
    await page.keyboard.press('Enter');
    await page.locator('#drawer').waitFor({ state: 'visible' });
    await page.keyboard.press('Escape');
    assert.equal(await page.evaluate(() => document.activeElement.className), 'card__detail');
    assert.equal(await page.evaluate(() => document.activeElement.closest('.card').dataset.id === document.querySelector('.card').dataset.id), true);

    // History: push a filter, open a work, go back (drawer closes, URL kept, focus on the same work), then forward.
    await visit('/?year=2026');
    await page.locator('#year-chips [data-year=""]').click();
    const histId = await page.locator('#card-grid .card').first().getAttribute('data-id');
    assert.match(histId, /^2026-/);
    await page.locator('#card-grid .card__detail').first().click();
    await page.locator('#drawer-body p').first().waitFor();
    assert.equal(new URL(page.url()).pathname, `/entries/${histId}/`);
    await page.goBack();
    await page.waitForFunction(() => document.querySelector('#drawer').hidden);
    assert.equal(new URL(page.url()).pathname + new URL(page.url()).search, '/?year=2026');
    await page.locator(`#card-grid .card__detail[data-id="${histId}"]`).waitFor();
    assert.equal(await page.evaluate(() => document.activeElement.dataset.id), histId);
    assert.equal(await page.evaluate(() => document.activeElement.className), 'card__detail');
    await page.goForward();
    await page.locator('#drawer').waitFor({ state: 'visible' });
    assert.equal(new URL(page.url()).pathname, `/entries/${histId}/`);
    assert.equal(await page.locator('#drawer-title').innerText() !== '', true);
    await page.keyboard.press('Escape');

    // Malformed #e= values are ignored without an error banner.
    await visit('/#e=%E0');
    assert.equal(await page.locator('#drawer').isVisible(), false);
    assert.equal(await page.locator('#error').isVisible(), false);

    // Screenshots for visual comparison.
    await page.screenshot({ path: '/tmp/sigma-desktop.png' });
    await page.setViewportSize({ width: 390, height: 844 });
    await visit('/');
    await page.screenshot({ path: '/tmp/sigma-mobile.png' });
    await page.setViewportSize({ width: 1440, height: 1000 });
    await visit('/');
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
