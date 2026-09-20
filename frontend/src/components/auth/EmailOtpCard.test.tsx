import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it, vi } from "vitest";

import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";

import { EmailOtpCard } from "./EmailOtpCard";

const mount = async (props: Partial<Parameters<typeof EmailOtpCard>[0]> = {}) => {
  const onSignedIn = vi.fn();
  const onCancel = vi.fn();
  const applyEmailOtpSignIn = vi.fn();
  const result = renderPage(
    () => <EmailOtpCard onSignedIn={onSignedIn} onCancel={onCancel} {...props} />,
    { auth: { applyEmailOtpSignIn } }
  );
  await waitFor(() => {
    expect(result.router.state.status).toBe("idle");
  });
  return { onSignedIn, onCancel, applyEmailOtpSignIn };
};

/** Ask for a code at an address and land on the code step. */
const askAt = async (address: string) => {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText(/email/i), address);
  await user.click(screen.getByRole("button", { name: /email me a code/i }));
  await screen.findByLabelText(/^code$/i);
  return user;
};

describe("EmailOtpCard", () => {
  it("signs in when the code belongs to an account", async () => {
    const sent: Record<string, string>[] = [];
    server.use(
      http.post("/api/v1/auth/email-otp/send", () =>
        HttpResponse.json({ status: "sent", challenge: "handle-1" })
      ),
      http.post("/api/v1/auth/email-otp/verify", async ({ request }) => {
        sent.push((await request.json()) as Record<string, string>);
        return HttpResponse.json({ access_token: "a-token", token_type: "bearer" });
      })
    );
    const { onSignedIn, applyEmailOtpSignIn } = await mount();

    const user = await askAt("reader@example.com");
    await user.type(screen.getByLabelText(/^code$/i), "123456");
    await user.click(screen.getByRole("button", { name: /^sign in$/i }));

    await waitFor(() => expect(onSignedIn).toHaveBeenCalled());
    expect(applyEmailOtpSignIn).toHaveBeenCalledWith("a-token");
    expect(sent).toEqual([{ challenge: "handle-1", code: "123456" }]);
  });

  it("asks for a username when the address belongs to nobody yet", async () => {
    server.use(
      http.post("/api/v1/auth/email-otp/send", () =>
        HttpResponse.json({ status: "sent", challenge: "handle-2" })
      ),
      http.post("/api/v1/auth/email-otp/verify", () =>
        HttpResponse.json({ registration_ticket: "ticket-2" }, { status: 202 })
      ),
      http.post("/api/v1/auth/email-otp/register", () =>
        HttpResponse.json({ access_token: "new-token", token_type: "bearer" }, { status: 201 })
      )
    );
    const { onSignedIn, applyEmailOtpSignIn } = await mount();

    const user = await askAt("newcomer@example.com");
    await user.type(screen.getByLabelText(/^code$/i), "654321");
    await user.click(screen.getByRole("button", { name: /^sign in$/i }));

    const username = await screen.findByLabelText(/username/i);
    await user.type(username, "newcomer");
    await user.click(screen.getByRole("button", { name: /create account/i }));

    await waitFor(() => expect(onSignedIn).toHaveBeenCalled());
    expect(applyEmailOtpSignIn).toHaveBeenCalledWith("new-token");
  });

  it("keeps the code step when the code is refused", async () => {
    server.use(
      http.post("/api/v1/auth/email-otp/send", () =>
        HttpResponse.json({ status: "sent", challenge: "handle-3" })
      ),
      http.post("/api/v1/auth/email-otp/verify", () =>
        HttpResponse.json({ detail: "EMAIL_OTP_INVALID" }, { status: 400 })
      )
    );
    const { onSignedIn } = await mount();

    const user = await askAt("wrong@example.com");
    await user.type(screen.getByLabelText(/^code$/i), "000000");
    await user.click(screen.getByRole("button", { name: /^sign in$/i }));

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.getByLabelText(/^code$/i)).toBeInTheDocument();
    expect(onSignedIn).not.toHaveBeenCalled();
  });

  it("goes back to the address when it was typed wrong", async () => {
    server.use(
      http.post("/api/v1/auth/email-otp/send", () =>
        HttpResponse.json({ status: "sent", challenge: "handle-4" })
      )
    );
    await mount();

    const user = await askAt("typo@example.com");
    await user.click(screen.getByRole("button", { name: /wrong address/i }));

    expect(await screen.findByLabelText(/email/i)).toBeInTheDocument();
  });
});
