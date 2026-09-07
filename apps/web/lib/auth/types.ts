/**
 * Frontend Authentication & Identity Types for RiskWise 2.0 (Phase 3 Step 6).
 *
 * Strictly aligned with FastAPI backend Pydantic models in:
 * - apps/api/app/schemas/auth.py
 * - apps/api/app/schemas/session.py
 */

export interface OrganizationSummary {
  id: string;
  name: string;
  slug: string | null;
  plan: string;
  is_active: boolean;
}

export interface UserMeResponse {
  id: string;
  email: string;
  full_name: string | null;
  role: string;
  org_id: string | null;
  organization: OrganizationSummary | null;
  permissions: string[];
}

export interface LogoutResponse {
  status: string;
  message: string;
}

export interface GoogleAuthUrlResponse {
  authorization_url: string;
  state: string;
}

export type AuthStatus =
  | "loading"
  | "unauthenticated"
  | "authenticated"
  | "onboarding-required"
  | "access-pending"
  | "access-denied"
  | "authentication-error";

export interface AuthState {
  status: AuthStatus;
  user: UserMeResponse | null;
  organization: OrganizationSummary | null;
  role: string | null;
  permissions: string[];
  error: string | null;
}

export interface AuthContextType extends AuthState {
  isLoading: boolean;
  isAuthenticated: boolean;
  refreshSession: () => Promise<UserMeResponse | null>;
  logout: () => Promise<void>;
  hasRole: (...roles: string[]) => boolean;
  hasPermission: (permission: string) => boolean;
}
