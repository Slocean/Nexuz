export type NoticePayload = {
  id?: unknown;
  body?: unknown;
};

/** Returns the unread notice ID, or null when the payload is invalid/already read. */
export function getUnreadNoticeId(
  notice: NoticePayload | null | undefined,
  persistedReadId: unknown,
): string | null {
  if (!notice?.id || !notice?.body) return null;
  const noticeId = String(notice.id);
  return noticeId === String(persistedReadId || '') ? null : noticeId;
}
