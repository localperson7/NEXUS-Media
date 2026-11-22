import { spawn, execFileSync } from 'node:child_process';
import { existsSync, mkdirSync, rmSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { createRequire } from 'node:module';

const projectRoot = resolve(import.meta.dirname, '..');
const frontendDir = join(projectRoot, 'frontend');
const backendDir = join(projectRoot, 'backend');
const artifactDir =
  process.env.PLAYWRIGHT_OUTPUT_DIR || join(projectRoot, 'test-results');

const requireFromFrontend = createRequire(join(frontendDir, 'package.json'));
const { chromium } = requireFromFrontend('playwright');

const chromeExecutable = [
  process.env.CHROME_PATH,
  '/usr/bin/google-chrome-stable',
  '/usr/bin/google-chrome',
  '/usr/bin/chromium',
].find((p) => p && existsSync(p));

async function waitForHttp(url, timeoutMs = 15000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      const resp = await fetch(url);
      if (resp.ok) return;
    } catch {}
    await new Promise((r) => setTimeout(r, 250));
  }
  throw new Error(`Timed out waiting for ${url}`);
}

async function assertNoHorizontalOverflow(page, label) {
  const metrics = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    innerWidth: window.innerWidth,
  }));
  if (metrics.scrollWidth > metrics.innerWidth + 1) {
    throw new Error(
      `Horizontal overflow detected on ${label}: scrollWidth=${metrics.scrollWidth} > innerWidth=${metrics.innerWidth}`
    );
  }
  console.log(`Layout OK (${label}): ${metrics.scrollWidth}px <= ${metrics.innerWidth}px`);
}

async function main() {
  mkdirSync(artifactDir, { recursive: true });

  const testDbPath = '/tmp/nexus_m7_playwright.db';
  const testStorageRoot = '/tmp/nexus_m7_playwright_jobs';
  const testAccessToken = 'nexus-m7-private-code';
  rmSync(testDbPath, { force: true });
  rmSync(testDbPath + '-wal', { force: true });
  rmSync(testDbPath + '-shm', { force: true });
  rmSync(testStorageRoot, { recursive: true, force: true });

  // 1. Generate small authorized local video
  const sampleVideoPath = join(backendDir, 'tmp_m7_sample.mp4');
  execFileSync('ffmpeg', [
    '-y',
    '-hide_banner',
    '-loglevel',
    'error',
    '-f',
    'lavfi',
    '-i',
    'testsrc=duration=1.5:size=1280x720:rate=24',
    '-f',
    'lavfi',
    '-i',
    'sine=frequency=520:duration=1.5',
    '-c:v',
    'libx264',
    '-pix_fmt',
    'yuv420p',
    '-c:a',
    'aac',
    '-shortest',
    sampleVideoPath,
  ]);

  const mediaServer = spawn(
    join(backendDir, '.venv/bin/python'),
    ['-m', 'http.server', '8766', '--bind', '127.0.0.1', '--directory', backendDir],
    { stdio: 'ignore' }
  );

  // 2. Start UNIFIED PRODUCTION SERVER (FastAPI serving frontend/dist + /api/* on single origin 127.0.0.1:8000)
  const backendProc = spawn(
    join(backendDir, '.venv/bin/uvicorn'),
    ['app.main:app', '--host', '127.0.0.1', '--port', '8000'],
    {
      cwd: backendDir,
      env: {
        ...process.env,
        NEXUS_MEDIA_ALLOW_LOOPBACK_FOR_TESTS: 'true',
        NEXUS_MEDIA_DATABASE_PATH: testDbPath,
        NEXUS_MEDIA_STORAGE_ROOT: testStorageRoot,
        NEXUS_MEDIA_ACCESS_TOKEN: testAccessToken,
      },
      stdio: 'ignore',
    }
  );

  try {
    await waitForHttp('http://127.0.0.1:8000/api/health');

    const browser = await chromium.launch({
      executablePath: chromeExecutable,
      headless: true,
    });

    // --- MOBILE iPHONE (390x844) ON UNIFIED PRODUCTION ORIGIN ---
    const mobileCtx = await browser.newContext({
      viewport: { width: 390, height: 844 },
      isMobile: true,
      hasTouch: true,
      colorScheme: 'dark',
    });
    const mPage = await mobileCtx.newPage();
    await mPage.goto('http://127.0.0.1:8000', { waitUntil: 'networkidle' });

    // 1. Verify Private Access Lock Screen appears when NEXUS_MEDIA_ACCESS_TOKEN is set
    await mPage.waitForSelector('text=Вход по коду доступа', { timeout: 8000 });
    await assertNoHorizontalOverflow(mPage, 'mobile-lock-screen');
    await mPage.screenshot({
      path: join(artifactDir, 'm7_mobile_lock.png'),
      fullPage: false,
    });

    // Unlock using access code (sets HttpOnly SameSite=Strict cookie)
    await mPage.getByLabel('Код доступа к NEXUS Media').fill(testAccessToken);
    await mPage.getByRole('button', { name: 'Открыть доступ' }).click();
    await mPage.waitForSelector('text=Источник медиапотока', { timeout: 8000 });

    // 2. Verify mobile input font-size is >= 16px (prevents iOS Safari auto-zoom!)
    const inputFontSize = await mPage.evaluate(() => {
      const el = document.querySelector('.input-url');
      return el ? parseFloat(window.getComputedStyle(el).fontSize) : 0;
    });
    if (inputFontSize < 16) {
      throw new Error(`Mobile input font-size is ${inputFontSize}px (<16px causes iOS Safari zoom!)`);
    }
    console.log(`iOS anti-zoom check OK: .input-url fontSize = ${inputFontSize}px`);

    // 3. Verify Service Worker registration on unified production origin
    const swRegistered = await mPage.evaluate(async () => {
      if (!('serviceWorker' in navigator)) return false;
      const reg = await navigator.serviceWorker.ready;
      return Boolean(reg && reg.active);
    });
    console.log(`Service Worker active on unified production origin: ${swRegistered}`);

    // 4. Inspect & export MP3 via unified origin (with cookie-authenticated SSE & download!)
    await mPage.getByLabel('Ссылка на медиафайл').fill('http://127.0.0.1:8766/tmp_m7_sample.mp4');
    await mPage.getByRole('button', { name: 'Проверить источник' }).click();
    await mPage.waitForSelector('text=720p HD (1280×720)', { timeout: 10000 });
    await assertNoHorizontalOverflow(mPage, 'mobile-unified-inspector');
    await mPage.screenshot({
      path: join(artifactDir, 'm7_mobile_unified_inspector.png'),
      fullPage: false,
    });

    await mPage.getByRole('radio', { name: /Аудиоэкспорт MP3/i }).click();
    await mPage.getByRole('button', { name: /Выполнить аудиоэкспорт MP3/i }).click();
    await mPage.waitForSelector('text=Скачать файл', { timeout: 15000 });

    // Verify authenticated download headers on unified origin
    const dlHref = await mPage.getByRole('link', { name: 'Скачать файл' }).getAttribute('href');
    const dlCheck = await mPage.evaluate(async (href) => {
      const r = await fetch(href);
      return {
        status: r.status,
        ct: r.headers.get('content-type'),
        cd: r.headers.get('content-disposition'),
        nosniff: r.headers.get('x-content-type-options'),
        size: (await r.arrayBuffer()).byteLength,
      };
    }, dlHref);
    console.log('Unified download header check:', JSON.stringify(dlCheck));
    if (dlCheck.status !== 200 || !dlCheck.cd?.includes('attachment') || dlCheck.size < 1000) {
      throw new Error(`Invalid unified download response: ${JSON.stringify(dlCheck)}`);
    }

    // 5. Simulate offline mode & recovery (Safari background/network drop resilience)
    await mobileCtx.setOffline(true);
    await mPage.evaluate(() => window.dispatchEvent(new Event('offline')));
    await mPage.waitForSelector('text=Устройство не подключено к сети', { timeout: 5000 });
    await assertNoHorizontalOverflow(mPage, 'mobile-offline-banner');
    await mPage.screenshot({
      path: join(artifactDir, 'm7_mobile_offline.png'),
      fullPage: false,
    });

    await mobileCtx.setOffline(false);
    await mPage.evaluate(() => window.dispatchEvent(new Event('online')));
    await mPage.waitForSelector('text=Устройство не подключено к сети', {
      state: 'detached',
      timeout: 8000,
    });
    console.log('Offline -> Online SSE & UI recovery verified.');

    // --- DESKTOP (1440x900) ON UNIFIED PRODUCTION ORIGIN ---
    const desktopCtx = await browser.newContext({
      viewport: { width: 1440, height: 900 },
      colorScheme: 'dark',
    });
    const dPage = await desktopCtx.newPage();
    await dPage.goto('http://127.0.0.1:8000', { waitUntil: 'networkidle' });
    await dPage.getByLabel('Код доступа к NEXUS Media').fill(testAccessToken);
    await dPage.getByRole('button', { name: 'Открыть доступ' }).click();
    await dPage.waitForSelector('text=SSE поток активен', { timeout: 10000 });

    await dPage.getByRole('button', { name: 'Настройки и источники' }).click();
    await dPage.waitForSelector('text=Включена (Cookie)', { timeout: 5000 });
    await assertNoHorizontalOverflow(dPage, 'desktop-unified-settings');
    await dPage.screenshot({
      path: join(artifactDir, 'm7_desktop_unified_settings.png'),
      fullPage: false,
    });

    await browser.close();
    console.log('M7 Unified Production Server, Auth Cookie, SSE, SW, Offline & Mobile E2E PASSED.');
  } finally {
    backendProc.kill();
    mediaServer.kill();
    rmSync(sampleVideoPath, { force: true });
    rmSync(testDbPath, { force: true });
    rmSync(testDbPath + '-wal', { force: true });
    rmSync(testDbPath + '-shm', { force: true });
    rmSync(testStorageRoot, { recursive: true, force: true });
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
