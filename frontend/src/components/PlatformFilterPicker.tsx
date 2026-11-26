"use client";

/**
 * "Only collect from these platforms" input for a new run.
 *
 * Quick-pick chips for common platforms plus a free-text box for anything
 * else (e.g. "play store"). An empty selection means "collect from everything".
 */
import * as React from "react";
import { useState } from "react";
import { Filter, Plus, X } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";

export const COMMON_PLATFORMS: { value: string; label: string }[] = [
  { value: "instagram", label: "Instagram" },
  { value: "facebook", label: "Facebook" },
  { value: "linkedin", label: "LinkedIn" },
  { value: "google", label: "Google" },
  { value: "tripadvisor", label: "TripAdvisor" },
  { value: "reddit", label: "Reddit" },
  { value: "twitter_x", label: "Twitter / X" },
  { value: "news_blog", label: "News / blogs" },
];

const MAX_ENTRIES = 20;
const MAX_LENGTH = 50;

export function platformLabel(value: string): string {
  return COMMON_PLATFORMS.find((p) => p.value === value)?.label ?? value;
}

interface PlatformFilterPickerProps {
  value: string[];
  onChange: (next: string[]) => void;
}

export default function PlatformFilterPicker({ value, onChange }: PlatformFilterPickerProps) {
  const [draft, setDraft] = useState("");
  const lower = value.map((v) => v.toLowerCase());

  const toggle = (platform: string) => {
    onChange(lower.includes(platform) ? value.filter((v) => v.toLowerCase() !== platform) : [...value, platform]);
  };

  const addDraft = () => {
    const parts = draft
      .split(",")
      .map((p) => p.trim().slice(0, MAX_LENGTH))
      .filter(Boolean);
    const next = [...value];
    for (const p of parts) {
      if (!next.some((v) => v.toLowerCase() === p.toLowerCase()) && next.length < MAX_ENTRIES) next.push(p);
    }
    onChange(next);
    setDraft("");
  };

  const custom = value.filter((v) => !COMMON_PLATFORMS.some((p) => p.value === v.toLowerCase()));

  return (
    <div className="space-y-4" data-testid="platform-filter">
      <div className="flex flex-wrap gap-2" role="group" aria-label="Common platforms">
        {COMMON_PLATFORMS.map((p) => {
          const on = lower.includes(p.value);
          return (
            <button
              key={p.value}
              type="button"
              aria-pressed={on}
              onClick={() => toggle(p.value)}
              data-testid={`platform-chip-${p.value}`}
              className={`rounded-full border px-3 py-1 text-sm transition-colors ${
                on
                  ? "border-primary bg-primary/10 text-foreground font-medium"
                  : "border-border text-muted-foreground hover:text-foreground hover:border-foreground/40"
              }`}
            >
              {p.label}
            </button>
          );
        })}
      </div>

      <div className="flex gap-2">
        <Input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              addDraft();
            }
          }}
          placeholder="Other platform, e.g. play store (comma-separated)"
          aria-label="Other platform"
          data-testid="platform-filter-input"
          maxLength={200}
        />
        <Button type="button" variant="outline" onClick={addDraft} disabled={!draft.trim()} data-testid="platform-filter-add">
          <Plus className="h-4 w-4 mr-1" /> Add
        </Button>
      </div>

      {custom.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {custom.map((c) => (
            <span
              key={c}
              className="inline-flex items-center gap-1 rounded-full border border-primary bg-primary/10 px-3 py-1 text-sm"
              data-testid={`platform-custom-${c}`}
            >
              {c}
              <button
                type="button"
                aria-label={`Remove ${c}`}
                onClick={() => onChange(value.filter((v) => v !== c))}
                className="text-muted-foreground hover:text-foreground"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </span>
          ))}
        </div>
      )}

      <p className="text-xs text-muted-foreground flex items-start gap-1.5" data-testid="platform-filter-hint">
        <Filter className="h-3.5 w-3.5 mt-0.5 shrink-0" />
        {value.length === 0
          ? "No platform chosen: data is collected from every selected source."
          : `Only items from ${value.map(platformLabel).join(", ")} are kept. Sources for other platforms are skipped before they run, so they use no API quota.`}
      </p>
    </div>
  );
}
