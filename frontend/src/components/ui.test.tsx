import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { EmptyState, ErrorState, RiskBadge, ScoreBar } from "./ui";

describe("UI primitives", () => {
  it("renders a risk badge with score and category", () => {
    render(<RiskBadge category="critical" score={97} />);
    expect(screen.getByText("97")).toBeInTheDocument();
    expect(screen.getByText("critical")).toBeInTheDocument();
  });
  it("labels unscored transactions", () => {
    render(<RiskBadge category={null} />);
    expect(screen.getByText("unscored")).toBeInTheDocument();
  });
  it("derives the score bar band from the score", () => {
    render(<ScoreBar score={72} />);
    expect(screen.getByTitle("Risk score 72/100 (high)")).toBeInTheDocument();
  });
  it("shows error and empty states", () => {
    render(<><ErrorState error={new Error("boom")} /><EmptyState title="Nothing here" /></>);
    expect(screen.getByRole("alert")).toHaveTextContent("boom");
    expect(screen.getByText("Nothing here")).toBeInTheDocument();
  });
});
