"use client";

import * as React from "react";

import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

/** Confirmation for destructive actions; optionally asks for a reason that is kept in the record. */
export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel,
  onConfirm,
  reasonLabel,
  reasonPlaceholder,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: React.ReactNode;
  confirmLabel: string;
  onConfirm: (reason: string) => Promise<void> | void;
  reasonLabel?: string;
  reasonPlaceholder?: string;
}) {
  const [reason, setReason] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const reasonId = React.useId();

  React.useEffect(() => {
    if (open) setReason("");
  }, [open]);

  async function confirm() {
    setBusy(true);
    try {
      await onConfirm(reason.trim());
      onOpenChange(false);
    } finally {
      setBusy(false);
    }
  }

  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          <AlertDialogDescription>{description}</AlertDialogDescription>
        </AlertDialogHeader>
        {reasonLabel ? (
          <div className="flex flex-col gap-1.5">
            <Label htmlFor={reasonId}>{reasonLabel}</Label>
            <Textarea
              id={reasonId}
              value={reason}
              maxLength={500}
              onChange={(event) => setReason(event.target.value)}
              placeholder={reasonPlaceholder}
              className="min-h-16 font-sans"
            />
          </div>
        ) : null}
        <AlertDialogFooter>
          <AlertDialogCancel disabled={busy}>Cancel</AlertDialogCancel>
          <Button
            className="bg-destructive text-white hover:bg-destructive/90"
            onClick={() => void confirm()}
            disabled={busy}
          >
            {confirmLabel}
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
