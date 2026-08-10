import * as React from "react";

import { cn } from "@/lib/utils";

export const Textarea = React.forwardRef<HTMLTextAreaElement, React.TextareaHTMLAttributes<HTMLTextAreaElement>>(
  ({ className, ...props }, ref) => (
    <textarea
      ref={ref}
      className={cn(
        "min-h-20 w-full rounded-lg border border-input bg-background px-3 py-2 font-mono text-[13px] leading-relaxed placeholder:text-muted-foreground/70 transition-shadow focus-visible:outline-none focus-visible:border-primary focus-visible:ring-4 focus-visible:ring-ring disabled:opacity-50",
        className,
      )}
      {...props}
    />
  ),
);
Textarea.displayName = "Textarea";
