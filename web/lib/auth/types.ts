/**
 * Frontend Authentication & Identity Types for ChainSentinel.
 *
 * Strictly aligned with FastAPI backend Pydantic models in:
 * - api/app/schemas/auth.py
 * - api/app/schemas/session.py
 */

export interface OrganizationSummary {
  id: string;
  name: string;
  slug: string | null;
  plan: string;
  is_active: boolean;
}

export interface OrganizationMembershipSummary {
  org_id: string;
  organization_name: string;
  organization_slug?: string | null;
  role: string;
  is_active: boolean;
}

export interface UserMeResponse {
  id: string;
  email: string;
  full_name: string | null;
  role: string;
  org_id: string | null;
  organization_id?: string | null;
  organization: OrganizationSummary | null;
  organizations?: OrganizationMembershipSummary[];
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

export interface CompanyRegisterRequest {
  full_name: string;
  company_name: string;
  email: string;
  password: string;
  confirm_password: string;
  terms_accepted: boolean;
}

export interface LoginRequest {
  email: string;
  password: string;
}

export interface ForgotPasswordRequest {
  email: string;
}

export interface ForgotPasswordResponse {
  status: string;
  message: string;
}

export interface ResetPasswordRequest {
  token: string;
  new_password: string;
  confirm_password: string;
}

export interface ResetPasswordResponse {
  status: string;
  message: string;
}

export interface InviteEmployeeRequest {
  email: string;
  role?: string;
}

export interface InvitationResponse {
  id: string;
  email: string;
  role: string;
  status: string;
  org_id: string;
  organization_name?: string | null;
  expires_at: string;
  invitation_link?: string | null;
  created_at: string;
}

export interface InvitationDetailsResponse {
  email: string;
  role: string;
  organization_name: string;
  organization_slug?: string | null;
  expires_at: string;
}

export interface AcceptInvitationRequest {
  full_name: string;
  password: string;
  confirm_password: string;
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

export interface SwitchOrgRequest {
  org_id: string;
}

export interface SwitchOrgResponse {
  status: string;
  active_organization_id: string;
  role: string;
  user: UserMeResponse;
}

export interface AuthContextType extends AuthState {
  isLoading: boolean;
  isAuthenticated: boolean;
  refreshSession: () => Promise<UserMeResponse | null>;
  switchOrg: (orgId: string) => Promise<UserMeResponse | null>;
  logout: () => Promise<void>;
  hasRole: (...roles: string[]) => boolean;
  hasPermission: (permission: string) => boolean;
}
