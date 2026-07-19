import { expect, test } from '@playwright/test';

test('imports, saves, and runs a trusted flow through the native bridge', async ({ page }) => {
  await page.addInitScript(() => {
    window.__bridgeCalls = [];
    const record = (method, result) => (...args) => {
      window.__bridgeCalls.push({ method, args });
      return Promise.resolve(result);
    };
    const flow = {
      name: 'E2E flow',
      entry: 'delay_1',
      nodes: {
        delay_1: {
          type: 'delay',
          params: { ms: 1 },
          position: { x: 100, y: 100 },
          next: null,
        },
      },
      variables: {},
      breakpoints: [],
    };
    window.pywebview = {
      api: {
        fetch_notice: record('fetch_notice', { ok: true, notice: null }),
        check_for_update: record('check_for_update', {
          ok: true,
          update_available: false,
        }),
        import_flow: record('import_flow', {
          ok: true,
          import_token: 'preview-token',
          name: 'E2E flow',
          risks: {
            capabilities: [],
            unknown_types: [],
            needs_strong_warning: false,
          },
        }),
        commit_import_flow: record('commit_import_flow', {
          ok: true,
          flow,
          path: 'E2E.flow.json',
        }),
        save_flow: record('save_flow', {
          ok: true,
          path: 'E2E.flow.json',
          name: 'E2E flow',
        }),
        run_flow: record('run_flow', { ok: true }),
      },
    };
  });

  await page.goto('/');
  await page.getByTitle('从文件导入流程').click();
  await page
    .getByRole('button', { name: '我信任此来源，继续导入' })
    .click();

  await expect.poll(async () =>
    page.evaluate(() =>
      window.__bridgeCalls.some((call) => call.method === 'commit_import_flow'),
    ),
  ).toBe(true);

  await page.getByTitle('保存').click();
  await expect.poll(async () =>
    page.evaluate(() => window.__bridgeCalls.some((call) => call.method === 'save_flow')),
  ).toBe(true);

  await page.getByTitle(/^运行（/).click();
  await expect.poll(async () =>
    page.evaluate(() => window.__bridgeCalls.some((call) => call.method === 'run_flow')),
  ).toBe(true);
});
