"use client";

import React, { createContext, useContext, useEffect, useState, useCallback, useMemo } from "react";
import { useRouter, usePathname } from "next/navigation";
import { apiClient, ApiClientError } from "../api/client";
import { AuthContextType, AuthState, UserMeResponse } from "./types";

const initialAuthState: AuthState = {
  status: "loading",
  user: null,
  organization: null,
  role: null,
  permissions: [],
  error: null,
};

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<AuthState>(initialAuthState);
  const router = useRouter();
  const pathname = usePathname();

  const resolveAuthState = (user: UserMeResponse): AuthState => {
    // Determine granular enterprise authentication state
    if (!user.org_id || !user.organization) {
      return {
        status: "onboarding-required",
        user,
        organization: null,
        role: user.role,
        permissions: user.permissions || [],
        error: null,
      };
    }

    if (!user.organization.is_active) {
      return {
        status: "access-pending",
        user,
        organization: user.organization,
        role: user.role,
        permissions: user.permissions || [],
        error: null,
      };
    }

    return {
      status: "authenticated",
      user,
      organization: user.organization,
      role: user.role,
      permissions: user.permissions || [],
      error: null,
    };
  };

  const refreshSession = useCallback(async (): Promise<UserMeResponse | null> => {
    try {
      const user = await apiClient.auth.getMe();
      const nextState = resolveAuthState(user);
      setState(nextState);
      return user;
    } catch (err) {
      if (err instanceof ApiClientError) {
        if (err.status === 401) {
          setState({
            status: "unauthenticated",
            user: null,
            organization: null,
            role: null,
            permissions: [],
            error: null,
          });
          return null;
        }

        if (err.status === 403) {
          setState({
            status: "access-denied",
            user: null,
            organization: null,
            role: null,
            permissions: [],
            error: err.detail,
          });
          return null;
        }
      }

      setState({
        status: "authentication-error",
        user: null,
        organization: null,
        role: null,
        permissions: [],
        error: err instanceof Error ? err.message : "Unable to verify authentication session",
      });
      return null;
    }
  }, []);

  // Initial session restoration on application mount using subscription callbacks
  useEffect(() => {
    let isMounted = true;

    apiClient.auth
      .getMe()
      .then((user) => {
        if (isMounted) {
          setState(resolveAuthState(user));
        }
      })
      .catch((err) => {
        if (!isMounted) return;

        if (err instanceof ApiClientError && err.status === 401) {
          setState({
            status: "unauthenticated",
            user: null,
            organization: null,
            role: null,
            permissions: [],
            error: null,
          });
        } else if (err instanceof ApiClientError && err.status === 403) {
          setState({
            status: "access-denied",
            user: null,
            organization: null,
            role: null,
            permissions: [],
            error: err.detail,
          });
        } else {
          setState({
            status: "authentication-error",
            user: null,
            organization: null,
            role: null,
            permissions: [],
            error: err instanceof Error ? err.message : "Unable to verify authentication session",
          });
        }
      });

    return () => {
      isMounted = false;
    };
  }, []);

  // Global 401 listener from API client (graceful session expiration)
  useEffect(() => {
    const unsubscribe = apiClient.onUnauthorized(() => {
      setState((prev) => {
        if (prev.status === "unauthenticated") return prev;
        return {
          status: "unauthenticated",
          user: null,
          organization: null,
          role: null,
          permissions: [],
          error: "Your session has expired. Please sign in again.",
        };
      });

      if (pathname && pathname !== "/auth") {
        router.replace(`/auth?error=session_expired&return_to=${encodeURIComponent(pathname)}`);
      }
    });

    return unsubscribe;
  }, [pathname, router]);

  const logout = useCallback(async (): Promise<void> => {
    try {
      await apiClient.auth.logout();
    } catch {
      // Even if server session removal fails, client state is cleared
    } finally {
      setState({
        status: "unauthenticated",
        user: null,
        organization: null,
        role: null,
        permissions: [],
        error: null,
      });
      router.replace("/auth");
    }
  }, [router]);

  const hasRole = useCallback(
    (...roles: string[]): boolean => {
      if (!state.role) return false;
      const normalizedCurrent = state.role.trim().toUpperCase();
      return roles.some((r) => r.trim().toUpperCase() === normalizedCurrent);
    },
    [state.role]
  );

  const hasPermission = useCallback(
    (permission: string): boolean => {
      return state.permissions.includes(permission);
    },
    [state.permissions]
  );

  const contextValue: AuthContextType = useMemo(
    () => ({
      ...state,
      isLoading: state.status === "loading",
      isAuthenticated: state.status === "authenticated",
      refreshSession,
      logout,
      hasRole,
      hasPermission,
    }),
    [state, refreshSession, logout, hasRole, hasPermission]
  );

  return <AuthContext.Provider value={contextValue}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextType {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}
