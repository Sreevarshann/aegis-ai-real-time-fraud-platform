import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AuthProvider } from "../lib/auth";
import Login from "./Login";

function renderLogin() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <AuthProvider><Login /></AuthProvider>
    </QueryClientProvider>,
  );
}

afterEach(() => vi.restoreAllMocks());

describe("Login", () => {
  it("shows the server's error message on failed sign-in", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ detail: "Invalid email or password" }), { status: 401 }));
    renderLogin();
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "wrong" } });
    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Invalid email or password"));
  });

  it("posts credentials to the login endpoint and stores the token", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({
      access_token: "tkn", user: { user_id: "u", email: "analyst@meridian.demo", full_name: "A", role: "analyst", tenant_id: "meridian" },
    }), { status: 200 }));
    renderLogin();
    fireEvent.click(screen.getByText("Meridian · Analyst"));
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "pw" } });
    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));
    await waitFor(() => expect(localStorage.getItem("aegis.token")).toBe("tkn"));
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/auth/login");
    expect(JSON.parse(String(init?.body))).toEqual({ email: "analyst@meridian.demo", password: "pw" });
  });
});
