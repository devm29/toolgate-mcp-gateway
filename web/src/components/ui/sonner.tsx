"use client";

import { useTheme } from "next-themes";
import { Toaster as Sonner, type ToasterProps } from "sonner";

type Theme = "system" | "light" | "dark";

export function Toaster(props: ToasterProps) {
  const { theme } = useTheme();
  const resolved: Theme = theme === "light" || theme === "dark" ? theme : "system";
  return (
    <Sonner
      theme={resolved}
      position="bottom-center"
      toastOptions={{
        classNames: {
          toast:
            "group rounded-2xl border border-border/60 bg-popover text-popover-foreground shadow-lg ring-1 ring-black/5 dark:ring-white/10",
        },
      }}
      {...props}
    />
  );
}
