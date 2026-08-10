import { LogOut } from "lucide-react";

import { Button } from "@/components/ui/button";

export const metadata = { title: "Signed out · Toolgate Console" };

export default function SignedOutPage() {
  return (
    <div className="grid min-h-dvh place-items-center bg-secondary px-4">
      <div className="flex w-full max-w-sm flex-col items-center gap-4 rounded-2xl border border-border/60 bg-card p-8 text-center shadow-lg">
        <LogOut className="size-10 text-muted-foreground/70" strokeWidth={1.5} aria-hidden />
        <div className="flex flex-col gap-1">
          <h1 className="text-[22px] font-semibold tracking-tight">You&apos;re signed out</h1>
          <p className="text-[13px] text-muted-foreground">
            Your console session and its tokens were revoked. Sign in again to manage the gateway.
          </p>
        </div>
        <Button asChild className="w-full">
          <a href="/api/auth/login">Sign in</a>
        </Button>
      </div>
    </div>
  );
}
