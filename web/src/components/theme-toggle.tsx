"use client";

import { Monitor, Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import * as React from "react";

import { Button } from "@/components/ui/button";

const ORDER = ["system", "light", "dark"] as const;
const ICON = { system: Monitor, light: Sun, dark: Moon } as const;

export function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = React.useState(false);
  React.useEffect(() => setMounted(true), []);
  const current = (mounted ? theme : "system") as (typeof ORDER)[number];
  const Icon = ICON[current] ?? Monitor;
  return (
    <Button
      variant="ghost"
      size="icon"
      aria-label={`Theme: ${current}. Click to change.`}
      onClick={() => {
        const next = ORDER[(ORDER.indexOf(current) + 1) % ORDER.length] ?? "system";
        setTheme(next);
      }}
    >
      <Icon strokeWidth={1.75} />
    </Button>
  );
}
