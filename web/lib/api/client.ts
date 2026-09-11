/**
 * Unified API Client for RiskWise 2.0 (Phase 3 Step 6).
 *
 * Centralizes:
 * - Base URL resolution from NEXT_PUBLIC_API_URL
 * - Strict credentials: "include" for HttpOnly session cookie transmission
 * - Standardized error parsing & ApiClientError normalization
 * - Session expiration (401) event subscription
 */

import { LogoutResponse, UserMeResponse } from "../auth/types";

export class ApiClientError extends Error {
  public status: number;
  public statusText: string;
  public detail: string;
  public code?: string;

  constructor(status: number, statusText: string, detail: string, code?: string) {
    super(detail || `API Error ${status}: ${statusText}`);
    this.name = "ApiClientError";
    this.status = status;
    this.statusText = statusText;
    this.detail = detail;
    this.code = code;
  }
}

type UnauthorizedListener = (error: ApiClientError) => void;

class ApiClient {
  private baseUrl: string;
  private unauthorizedListeners: Set<UnauthorizedListener> = new Set();

  constructor() {
    this.baseUrl = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/+$/, "");
  }

  public getBaseUrl(): string {
    return this.baseUrl;
  }

  /**
   * Subscribe to 401 Unauthorized responses to trigger global session expiration.
   */
  public onUnauthorized(listener: UnauthorizedListener): () => void {
    this.unauthorizedListeners.add(listener);
    return () => {
      this.unauthorizedListeners.delete(listener);
    };
  }

  private notifyUnauthorized(error: ApiClientError): void {
    for (const listener of this.unauthorizedListeners) {
      try {
        listener(error);
      } catch (e) {
        console.error("Error in onUnauthorized listener:", e);
      }
    }
  }

  /**
   * Core credentialed fetch wrapper.
   */
  public async request<T = unknown>(path: string, options: RequestInit = {}): Promise<T> {
    const url = path.startsWith("http://") || path.startsWith("https://")
      ? path
      : `${this.baseUrl}${path.startsWith("/") ? "" : "/"}${path}`;

    const headers = new Headers(options.headers || {});
    if (!headers.has("Accept")) {
      headers.set("Accept", "application/json");
    }
    if (options.body && typeof options.body === "string" && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }

    const response = await fetch(url, {
      ...options,
      headers,
      credentials: "include", // Enforce HttpOnly cookie inclusion
    });

    if (!response.ok) {
      let detail = response.statusText;
      let code: string | undefined;

      try {
        const errorBody = await response.json();
        if (typeof errorBody === "object" && errorBody !== null) {
          if (typeof errorBody.detail === "string") {
            detail = errorBody.detail;
          } else if (Array.isArray(errorBody.detail)) {
            detail = errorBody.detail.map((d: { msg?: string }) => d.msg || JSON.stringify(d)).join(", ");
          }
          if (typeof errorBody.code === "string") {
            code = errorBody.code;
          }
        }
      } catch {
        // Non-JSON response body
      }

      const clientError = new ApiClientError(response.status, response.statusText, detail, code);

      if (response.status === 401) {
        this.notifyUnauthorized(clientError);
      }

      throw clientError;
    }

    // 204 No Content
    if (response.status === 204) {
      return null as T;
    }

    return (await response.json()) as T;
  }

  public get<T = unknown>(path: string, options?: RequestInit): Promise<T> {
    return this.request<T>(path, { ...options, method: "GET" });
  }

  public post<T = unknown>(path: string, body?: unknown, options?: RequestInit): Promise<T> {
    return this.request<T>(path, {
      ...options,
      method: "POST",
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  }

  public put<T = unknown>(path: string, body?: unknown, options?: RequestInit): Promise<T> {
    return this.request<T>(path, {
      ...options,
      method: "PUT",
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  }

  public delete<T = unknown>(path: string, options?: RequestInit): Promise<T> {
    return this.request<T>(path, { ...options, method: "DELETE" });
  }

  /**
   * RiskWise Authentication Subsystem
   */
  public readonly auth = {
    getMe: (): Promise<UserMeResponse> => {
      return this.get<UserMeResponse>("/api/v1/auth/me");
    },

    logout: (): Promise<LogoutResponse> => {
      return this.post<LogoutResponse>("/api/v1/auth/logout");
    },

    getGoogleAuthUrl: (returnTo: string = "/"): string => {
      const sanitizedReturnTo = returnTo.startsWith("/") && !returnTo.startsWith("//") ? returnTo : "/";
      const targetUrl = new URL("/api/v1/auth/google", this.baseUrl);
      targetUrl.searchParams.set("return_to", sanitizedReturnTo);
      return targetUrl.href;
    },
  };
}

export const apiClient = new ApiClient();
