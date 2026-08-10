"use client";

import {
  Activity,
  LayoutDashboard,
  LogOut,
  ScrollText,
  Server,
  ShieldCheck,
  SlidersHorizontal,
  Wrench,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import * as React from "react";

import { ThemeToggle } from "@/components/theme-toggle";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useApprovals, useSession } from "@/hooks/queries";
import { signOut } from "@/lib/api";
import { cn } from "@/lib/utils";

const BARE_ROUTES = new Set(["/signed-out"]);

const NAV = [
  { href: "/", label: "Overview", icon: LayoutDashboard },
  { href: "/servers", label: "Servers", icon: Server },
  { href: "/tools", label: "Tools", icon: Wrench },
  { href: "/approvals", label: "Approvals", icon: ShieldCheck, badge: true },
  { href: "/policies", label: "Policies", icon: SlidersHorizontal },
  { href: "/activity", label: "Activity", icon: Activity },
] as const;

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  if (BARE_ROUTES.has(pathname)) return <>{children}</>;
  return <ConsoleShell pathname={pathname}>{children}</ConsoleShell>;
}

function ConsoleShell({ pathname, children }: { pathname: string; children: React.ReactNode }) {
  const approvals = useApprovals();
  const session = useSession();
  const pending = approvals.data?.length ?? 0;

  return (
    <div className="grid min-h-dvh grid-cols-1 md:grid-cols-[240px_1fr]">
      <a
        href="#main"
        className="sr-only z-50 rounded-md bg-primary px-3 py-2 text-[13px] font-medium text-primary-foreground focus:not-sr-only focus:fixed focus:left-3 focus:top-3"
      >
        Skip to content
      </a>
      <aside className="material sticky top-0 hidden h-dvh flex-col border-r border-border/60 bg-sidebar/80 backdrop-blur-2xl backdrop-saturate-150 md:flex">
        <div className="flex h-14 items-center gap-2.5 px-5">
          <div
            aria-hidden
            className="grid size-7 place-items-center rounded-md bg-primary font-mono text-[13px] font-medium text-primary-foreground"
          >
            tg
          </div>
          <div className="flex flex-col leading-none">
            <span className="text-[15px] font-semibold tracking-tight">Toolgate</span>
            <span className="text-[11px] text-muted-foreground">MCP gateway</span>
          </div>
        </div>
        <nav aria-label="Console" className="flex flex-1 flex-col gap-0.5 px-3 py-2">
          {NAV.map((item) => {
            const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "flex h-8 items-center gap-2.5 rounded-md px-2.5 text-[13px] font-medium transition-colors",
                  active
                    ? "bg-sidebar-accent text-sidebar-accent-foreground"
                    : "text-muted-foreground hover:bg-sidebar-accent/60 hover:text-foreground",
                )}
              >
                <item.icon className="size-4" strokeWidth={1.75} aria-hidden />
                <span className="flex-1">{item.label}</span>
                {"badge" in item && item.badge && pending > 0 ? (
                  <Badge variant="danger" className="tabular" aria-label={`${pending} awaiting review`}>
                    {pending}
                  </Badge>
                ) : null}
              </Link>
            );
          })}
        </nav>
        <div className="flex items-center gap-2 border-t border-border/60 px-4 py-3 text-[12px] text-muted-foreground">
          <ScrollText className="size-3.5" strokeWidth={1.75} aria-hidden />
          Append-only audit
        </div>
      </aside>

      <div className="flex min-w-0 flex-col">
        <header className="material sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-border/60 bg-background/72 px-5 backdrop-blur-xl backdrop-saturate-[1.8]">
          <MobileNav pathname={pathname} pending={pending} />
          <div className="ml-auto flex items-center gap-1">
            {session.data ? (
              <span className="mr-2 hidden text-[12px] text-muted-foreground sm:inline" title="Signed in">
                {session.data.subject}
              </span>
            ) : null}
            <ThemeToggle />
            <Tooltip>
              <TooltipTrigger asChild>
                <Button variant="ghost" size="icon" aria-label="Sign out" onClick={() => void signOut()}>
                  <LogOut strokeWidth={1.75} />
                </Button>
              </TooltipTrigger>
              <TooltipContent>Sign out</TooltipContent>
            </Tooltip>
          </div>
        </header>
        <main id="main" tabIndex={-1} className="mx-auto w-full max-w-7xl flex-1 px-4 py-7 outline-none sm:px-5 md:px-8">
          {children}
        </main>
      </div>
    </div>
  );
}

function MobileNav({ pathname, pending }: { pathname: string; pending: number }) {
  return (
    <nav aria-label="Console" className="flex items-center gap-1 overflow-x-auto md:hidden">
      {NAV.map((item) => {
        const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
        return (
          <Link
            key={item.href}
            href={item.href}
            aria-label={item.label}
            aria-current={active ? "page" : undefined}
            className={cn(
              "relative grid size-9 shrink-0 place-items-center rounded-md",
              active ? "bg-sidebar-accent text-foreground" : "text-muted-foreground",
            )}
          >
            <item.icon className="size-4" strokeWidth={1.75} aria-hidden />
            {"badge" in item && item.badge && pending > 0 ? (
              <span className="absolute right-1.5 top-1.5 size-1.5 rounded-full bg-destructive" aria-hidden />
            ) : null}
          </Link>
        );
      })}
    </nav>
  );
}
