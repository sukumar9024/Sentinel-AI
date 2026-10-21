// Credentials stay in memory. One refresh promise prevents concurrent token rotation races.
let access = "";
let refresh = "";
let rotating: Promise<void> | null = null;
export function setSession(tokens: {
  access_token: string;
  refresh_token: string;
}) {
  access = tokens.access_token;
  refresh = tokens.refresh_token;
}
export function clearSession() {
  access = "";
  refresh = "";
}
export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}
export async function request(
  path: string,
  options: RequestInit = {},
): Promise<Response> {
  const sentToken = access;
  const send = () =>
    fetch("/api/v1" + path, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${access}`,
        ...options.headers,
      },
    });
  let response = await send();
  if (response.status === 401 && refresh && !path.startsWith("/auth/")) {
    if (access === sentToken) {
      if (!rotating)
        rotating = (async () => {
          const renewal = await fetch("/api/v1/auth/refresh", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ refresh_token: refresh }),
          });
          if (!renewal.ok) {
            clearSession();
            throw new ApiError("Your session expired. Sign in again.", 401);
          }
          setSession(await renewal.json());
        })().finally(() => {
          rotating = null;
        });
      await rotating;
    }
    response = await send();
  }
  if (!response.ok) {
    const data = await response.json();
    throw new ApiError(
      typeof data.detail === "string"
        ? data.detail
        : "Please check the submitted values.",
      response.status,
    );
  }
  return response;
}
