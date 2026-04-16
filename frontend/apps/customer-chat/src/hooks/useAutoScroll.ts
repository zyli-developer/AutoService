import { useCallback, useEffect, useState } from 'react';

export function useAutoScroll(
  containerRef: React.RefObject<HTMLElement>,
  deps: unknown[],
): { isAtBottom: boolean; scrollToBottom: () => void } {
  const [isAtBottom, setIsAtBottom] = useState(true);

  const scrollToBottom = useCallback(() => {
    const el = containerRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
    setIsAtBottom(true);
  }, [containerRef]);

  // Track whether user is near bottom on scroll
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const handleScroll = () => {
      const nearBottom = el.scrollTop + el.clientHeight >= el.scrollHeight - 50;
      setIsAtBottom(nearBottom);
    };

    el.addEventListener('scroll', handleScroll, { passive: true });
    return () => el.removeEventListener('scroll', handleScroll);
  }, [containerRef]);

  // Auto-scroll when deps change and user is near bottom
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const nearBottom = el.scrollTop + el.clientHeight >= el.scrollHeight - 50;
    if (nearBottom) {
      el.scrollTop = el.scrollHeight;
      setIsAtBottom(true);
    } else {
      setIsAtBottom(false);
    }
  // deps is intentionally spread here to trigger on any change
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return { isAtBottom, scrollToBottom };
}
