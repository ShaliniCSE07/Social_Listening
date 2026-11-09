import * as React from "react";
import { Loader2 } from "lucide-react";

interface LoadingStateProps {
  message?: string;
  className?: string;
}

export default function LoadingState({
  message = "Loading…",
  className = "",
}: LoadingStateProps) {
  return (
    <div
      className={`flex items-center justify-center py-12 text-muted-foreground ${className}`}
      data-testid="loading-state"
    >
      <Loader2 className="animate-spin h-5 w-5 mr-2 text-primary" aria-hidden="true" />
      <span className="text-sm font-medium">{message}</span>
    </div>
  );
}
