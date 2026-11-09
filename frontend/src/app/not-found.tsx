import Link from "next/link";
import { AlertCircle, Home } from "lucide-react";
import { Button } from "@/components/ui/button";

export default function NotFound() {
  return (
    <div className="flex flex-col items-center justify-center min-h-[60vh] text-center px-4">
      <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-muted mb-6">
        <AlertCircle className="h-8 w-8 text-muted-foreground" />
      </div>
      <h1 className="text-3xl font-bold tracking-tight text-foreground sm:text-4xl mb-2">
        Page Not Found
      </h1>
      <p className="text-muted-foreground max-w-md mb-6 text-sm">
        The page you are looking for does not exist or has been moved.
      </p>
      <Button asChild>
        <Link href="/">
          <Home className="h-4 w-4 mr-2" />
          Back to Dashboard
        </Link>
      </Button>
    </div>
  );
}

