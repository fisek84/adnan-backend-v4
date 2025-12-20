import { useCallback, useEffect, useRef, useState } from "react";

export const useAutoScroll = () => {
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const [isPinnedToBottom, setPinned] = useState(true);

  const scrollToBottom = useCallback((smooth = false) => {
    const el = viewportRef.current;
    if (!el) return;
    const top = el.scrollHeight;
    el.scrollTo({ top, behavior: smooth ? "smooth" : "auto" });
  }, []);

  useEffect(() => {
    const el = viewportRef.current;
    if (!el) return;

    const onScroll = () => {
      const threshold = 24;
      const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight <= threshold;
      setPinned(atBottom);
    };

    el.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
    return () => el.removeEventListener("scroll", onScroll);
  }, []);

  return { viewportRef, isPinnedToBottom, scrollToBottom };
};

export const useStableNow = () => {
  const ref = useRef<number>(Date.now());
  return ref.current;
};
