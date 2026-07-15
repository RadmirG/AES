import { aesApiBaseUrl } from "./config";
import type { WorkbenchUser } from "./types";

type AuthResponse = {
  user: WorkbenchUser;
};

export async function currentAuthenticatedUser(): Promise<WorkbenchUser | null> {
  const response = await fetch(`${aesApiBaseUrl}/api/auth/me`, {
    credentials: "include",
    headers: { Accept: "application/json" },
  });
  if (response.status === 401) {
    return null;
  }
  return userFromResponse(response);
}

export async function loginUser(
  username: string,
  password: string,
): Promise<WorkbenchUser> {
  const response = await fetch(`${aesApiBaseUrl}/api/auth/login`, {
    method: "POST",
    credentials: "include",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ username, password }),
  });
  return userFromResponse(response);
}

export async function logoutUser(): Promise<void> {
  const response = await fetch(`${aesApiBaseUrl}/api/auth/logout`, {
    method: "POST",
    credentials: "include",
    headers: { Accept: "application/json" },
  });
  if (!response.ok) {
    throw new Error(await responseError(response));
  }
}

async function userFromResponse(response: Response): Promise<WorkbenchUser> {
  if (!response.ok) {
    throw new Error(await responseError(response));
  }
  const payload = (await response.json()) as AuthResponse;
  if (!payload.user?.id || !payload.user.username) {
    throw new Error("Authentication service returned an invalid user.");
  }
  return payload.user;
}

async function responseError(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as { detail?: string };
    if (payload.detail) {
      return payload.detail;
    }
  } catch {
    // Use the generic fallback below when the response is not JSON.
  }
  return response.status === 503
    ? "Authentication service is unavailable."
    : "Authentication request failed.";
}
