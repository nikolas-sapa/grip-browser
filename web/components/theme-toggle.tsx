"use client";

import { useSyncExternalStore } from "react";
import { useTheme } from "next-themes";
import { ThemeToggleAscii } from "@/components/ui/toggle-theme-ascii";

// The server cannot know the stored theme. useSyncExternalStore gives the
// server and the hydrating client the same snapshot and re-renders once
// hydration is done — the registry toggle's suppressHydrationWarning only
// covers the button itself, not the glyph children, so gating here is what
// actually removes the mismatch.
const subscribe = () => () => {};
const useMounted = () =>
  useSyncExternalStore(
    subscribe,
    () => true,
    () => false,
  );

/**
 * The registry toggle in controlled mode. `syncDocument` stays off so
 * next-themes remains the single writer of the `dark` class and of storage:
 * two writers would fight over the first paint after a reload.
 */
export function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme();
  const mounted = useMounted();

  return (
    <ThemeToggleAscii
      dark={mounted ? resolvedTheme === "dark" : false}
      syncDocument={false}
      onDarkChange={(next) => setTheme(next ? "dark" : "light")}
    />
  );
}
