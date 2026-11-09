import * as React from "react";
import Link from "next/link";
import { FolderSearch, PlusCircle } from "lucide-react";
import { Button } from "@/components/ui/button";

interface EmptyStateProps {
  message: string;
  description?: string;
  actionHref?: string;
  actionLabel?: string;
  icon?: React.ComponentType<{ className?: string }>;
}

export default function EmptyState({
  message,
  description,
  actionHref,
  actionLabel,
  icon: Icon = FolderSearch,
}: EmptyStateProps) {
  return (
    <div
      className="flex flex-col items-center justify-center py-16 px-4 text-center border-2 border-dashed border-border rounded-xl bg-card/50"
      data-testid="empty-state"
    >
      <div className="flex h-12 w-12 items-center justify-center rounded-full bg-muted mb-4">
        <Icon className="h-6 w-6 text-muted-foreground" />
      </div>
      <h3 className="text-base font-semibold text-foreground mb-1">{message}</h3>
      {description && (
        <p className="text-sm text-muted-foreground max-w-sm mb-4">
          {description}
        </p>
      )}
      {actionHref && actionLabel && (
        <Button asChild size="sm" className="mt-2">
          <Link href={actionHref}>
            <PlusCircle className="h-4 w-4 mr-2" />
            {actionLabel}
          </Link>
        </Button>
      )}
    </div>
  );
}
