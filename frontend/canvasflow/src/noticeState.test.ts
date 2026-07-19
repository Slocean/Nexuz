import { describe, expect, it } from 'vitest';
import { getUnreadNoticeId } from './noticeState';

describe('startup notice state', () => {
  it('shows a valid notice that has not been read', () => {
    expect(getUnreadNoticeId({ id: 42, body: 'maintenance' }, '41')).toBe('42');
  });

  it('hides a notice whose persisted ID matches', () => {
    expect(getUnreadNoticeId({ id: '42', body: 'maintenance' }, 42)).toBeNull();
  });

  it('rejects incomplete notice payloads', () => {
    expect(getUnreadNoticeId({ id: '42' }, '')).toBeNull();
    expect(getUnreadNoticeId({ body: 'maintenance' }, '')).toBeNull();
    expect(getUnreadNoticeId(null, '')).toBeNull();
  });
});
