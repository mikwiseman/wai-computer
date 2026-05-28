import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { PersonalizationPanel } from "./PersonalizationPanel";

const mockListPersonalizationTerms = vi.fn();
const mockCreatePersonalizationTerm = vi.fn();
const mockUpdatePersonalizationTerm = vi.fn();
const mockDeletePersonalizationTerm = vi.fn();
const mockImportPersonalizationText = vi.fn();
const mockImportPersonalizationFile = vi.fn();

vi.mock("@/lib/api", () => ({
  listPersonalizationTerms: (...args: unknown[]) => mockListPersonalizationTerms(...args),
  createPersonalizationTerm: (...args: unknown[]) => mockCreatePersonalizationTerm(...args),
  updatePersonalizationTerm: (...args: unknown[]) => mockUpdatePersonalizationTerm(...args),
  deletePersonalizationTerm: (...args: unknown[]) => mockDeletePersonalizationTerm(...args),
  importPersonalizationText: (...args: unknown[]) => mockImportPersonalizationText(...args),
  importPersonalizationFile: (...args: unknown[]) => mockImportPersonalizationFile(...args),
}));

const terms = [
  {
    id: "term-1",
    user_id: "user-1",
    import_job_id: null,
    term: "WaiComputer",
    normalized_term: "waicomputer",
    replacement: null,
    notes: null,
    source: "manual",
    status: "active",
    frequency: 1,
    created_at: "2026-05-28T00:00:00Z",
    updated_at: "2026-05-28T00:00:00Z",
  },
  {
    id: "term-2",
    user_id: "user-1",
    import_job_id: "job-1",
    term: "больничный",
    normalized_term: "больничный",
    replacement: null,
    notes: null,
    source: "import",
    status: "candidate",
    frequency: 2,
    created_at: "2026-05-28T00:00:00Z",
    updated_at: "2026-05-28T00:00:00Z",
  },
] as const;

describe("PersonalizationPanel", () => {
  beforeEach(() => {
    [
      mockListPersonalizationTerms,
      mockCreatePersonalizationTerm,
      mockUpdatePersonalizationTerm,
      mockDeletePersonalizationTerm,
      mockImportPersonalizationText,
      mockImportPersonalizationFile,
    ].forEach((mock) => mock.mockReset());
    mockListPersonalizationTerms.mockResolvedValue(terms);
    mockCreatePersonalizationTerm.mockResolvedValue(terms[0]);
    mockUpdatePersonalizationTerm.mockResolvedValue(terms[0]);
    mockDeletePersonalizationTerm.mockResolvedValue(undefined);
    mockImportPersonalizationText.mockResolvedValue({ status: "succeeded" });
    mockImportPersonalizationFile.mockResolvedValue({ status: "succeeded" });
  });

  it("loads terms and handles term actions", async () => {
    const user = userEvent.setup();
    render(<PersonalizationPanel locale="en" />);

    await waitFor(() => {
      expect(screen.getByText("WaiComputer")).toBeInTheDocument();
      expect(screen.getByText("больничный")).toBeInTheDocument();
    });

    await user.type(screen.getByPlaceholderText("Term"), "Nova-3");
    await user.type(screen.getByPlaceholderText("Preferred spelling"), "Nova 3");
    await user.click(screen.getByRole("button", { name: "Add" }));

    await waitFor(() => {
      expect(mockCreatePersonalizationTerm).toHaveBeenCalledWith({
        term: "Nova-3",
        replacement: "Nova 3",
      });
    });

    await user.click(screen.getByRole("button", { name: "Approve" }));
    await waitFor(() => {
      expect(mockUpdatePersonalizationTerm).toHaveBeenCalledWith("term-2", { status: "active" });
    });

    await user.click(screen.getByRole("button", { name: "Reject" }));
    await waitFor(() => {
      expect(mockUpdatePersonalizationTerm).toHaveBeenCalledWith("term-2", { status: "rejected" });
    });

    await user.click(screen.getByRole("button", { name: "Delete" }));
    await waitFor(() => {
      expect(mockDeletePersonalizationTerm).toHaveBeenCalledWith("term-1");
    });
  });

  it("imports pasted text and text files", async () => {
    const user = userEvent.setup();
    const { container } = render(<PersonalizationPanel locale="en" />);

    await user.type(
      screen.getByPlaceholderText("Paste domain text to extract candidate terms"),
      "WaiComputer больничный",
    );
    await user.click(screen.getByRole("button", { name: "Extract" }));
    await waitFor(() => {
      expect(mockImportPersonalizationText).toHaveBeenCalledWith("WaiComputer больничный");
    });

    const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(["TermOne TermTwo"], "terms.txt", { type: "text/plain" });
    await user.upload(fileInput, file);

    await waitFor(() => {
      expect(mockImportPersonalizationFile).toHaveBeenCalledWith(file);
    });
  });
});
