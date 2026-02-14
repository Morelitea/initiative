import { http, HttpResponse } from "msw";
import { buildUser } from "@/__tests__/factories";

export const authHandlers = [
  http.post("/api/v1/auth/token", () => {
    return HttpResponse.json({ access_token: "test-token" });
  }),

  http.post("/api/v1/auth/register", () => {
    return HttpResponse.json(
      buildUser({ is_active: true, email_verified: true }),
    );
  }),

  http.get("/api/v1/auth/bootstrap", () => {
    return HttpResponse.json({
      has_users: true,
      public_registration_enabled: true,
    });
  }),

  http.get("/api/v1/auth/oidc/status", () => {
    return HttpResponse.json({ enabled: false });
  }),
];
