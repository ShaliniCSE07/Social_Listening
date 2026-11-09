import * as React from "react";
import { AlertCircle, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";

interface ErrorBoxProps {
  message: string;
  onRetry?: () => void;
  className?: string;
}

export default function ErrorBox({ message, onRetry, className }: ErrorBoxProps) {
  return (
    <div
      className={`rounded-xl bg-destructive/10 border border-destructive/20 p-4 text-sm text-destructive flex items-start justify-between gap-3 ${className || ""}`}
      role="alert"
      data-testid="error-box"
    >
      <div className="flex items-start gap-3">
        <AlertCircle className="h-5 w-5 shrink-0 mt-0.5 text-destructive" />
        <div>
          <p className="font-medium">Error</p>
          <p className="text-destructive/90 mt-0.5">{message}</p>
        </div>
      </div>
      {onRetry && (
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={onRetry}
          className="shrink-0 border-destructive/30 hover:bg-destructive/10 text-destructive text-xs"
        >
          <RotateCcw className="h-3.5 w-3.5 mr-1" />
          Retry
        </Button>
      )}
    </div>
  );
}
