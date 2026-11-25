import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";
import * as React from "react";
import PlatformFilterPicker from "@/components/PlatformFilterPicker";

function Harness({ onChange }: { onChange: (v: string[]) => void }) {
  const [value, setValue] = React.useState<string[]>([]);
  return (
    <PlatformFilterPicker
      value={value}
      onChange={(v) => {
        setValue(v);
        onChange(v);
      }}
    />
  );
}

describe("PlatformFilterPicker", () => {
  it("starts empty and says everything is collected", () => {
    render(<Harness onChange={vi.fn()} />);
    expect(screen.getByTestId("platform-filter-hint")).toHaveTextContent("every selected source");
  });

  it("toggles chips and adds comma-separated custom platforms without duplicates", () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);

    fireEvent.click(screen.getByTestId("platform-chip-instagram"));
    fireEvent.click(screen.getByTestId("platform-chip-google"));
    expect(screen.getByTestId("platform-chip-instagram")).toHaveAttribute("aria-pressed", "true");

    fireEvent.change(screen.getByTestId("platform-filter-input"), { target: { value: "Play Store, play store, Google" } });
    fireEvent.click(screen.getByTestId("platform-filter-add"));
    expect(onChange).toHaveBeenLastCalledWith(["instagram", "google", "Play Store"]);
    expect(screen.getByTestId("platform-custom-Play Store")).toBeInTheDocument();
    expect(screen.getByTestId("platform-filter-hint")).toHaveTextContent("Only items from Instagram, Google, Play Store");

    fireEvent.click(screen.getByTestId("platform-chip-instagram"));
    fireEvent.click(screen.getByLabelText("Remove Play Store"));
    expect(onChange).toHaveBeenLastCalledWith(["google"]);
  });

  it("adds a custom platform with Enter", () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    const input = screen.getByTestId("platform-filter-input");
    fireEvent.change(input, { target: { value: "zomato" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onChange).toHaveBeenLastCalledWith(["zomato"]);
  });
});
