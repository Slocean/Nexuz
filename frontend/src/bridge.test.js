import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { bridge } from './bridge';

describe('Python bridge contract', () => {
  let api;

  beforeEach(() => {
    api = {
      download_update: vi.fn().mockResolvedValue({ ok: true }),
      run_flow: vi.fn().mockResolvedValue({ ok: true }),
      save_flow: vi.fn().mockResolvedValue({ ok: true }),
      commit_import_flow: vi.fn().mockResolvedValue({ ok: true }),
    };
    globalThis.window = { pywebview: { api } };
  });

  afterEach(() => {
    vi.restoreAllMocks();
    delete globalThis.window;
  });

  it('does not expose an update URL argument', async () => {
    await bridge.downloadUpdate();
    expect(api.download_update).toHaveBeenCalledWith();
  });

  it('serializes flow payloads and preserves run controls', async () => {
    const flow = { entry: 'a', nodes: { a: { type: 'delay' } }, breakpoints: ['a'] };
    await bridge.runFlow(flow, true, false, true);
    expect(api.run_flow).toHaveBeenCalledWith(
      JSON.stringify(flow),
      true,
      false,
      true,
      ['a'],
    );

    await bridge.saveFlow(flow, 'demo.flow.json', 'demo');
    expect(api.save_flow).toHaveBeenCalledWith(
      JSON.stringify(flow),
      'demo.flow.json',
      'demo',
    );
  });

  it('commits imports only with the preview token', async () => {
    await bridge.commitImportFlow('preview-token');
    expect(api.commit_import_flow).toHaveBeenCalledWith('preview-token');
  });

  it('normalizes native bridge exceptions into visible failures', async () => {
    api.save_flow.mockRejectedValueOnce(new Error('disk full'));
    await expect(bridge.saveFlow({ nodes: {} })).resolves.toMatchObject({
      ok: false,
      error: 'disk full',
      message: 'disk full',
    });
  });
});
