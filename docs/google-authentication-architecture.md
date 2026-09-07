# RiskWise Google Authentication Architecture

> **Phase:** Phase 3 — Google Authentication: Step 1  
> **Status:** Architectural Specification & Identity Mapping Complete  
> **Target Services:** `apps/api` (FastAPI), `apps/web` (Next.js 16 App Router), PostgreSQL 16 (AWS RDS)  
> **Scope:** Architecture, Identity & Tenant Mapping, Security Contracts, API Design  
> **Database Execution:** **INSPECTION ONLY** (0 DDL, 0 DML, 0 migrations executed)

---

## 1. Authentication Goals

The primary goal of the RiskWise 2.0 authentication architecture is to provide an enterprise-grade, secure, multi-tenant authentication foundation centered on Google OAuth 2.0. The architecture strictly enforces the distinction between **Authentication** ("Who is this user?") and **Authorization** ("What is this user allowed to do?"):

1. **Deterministic Identity Resolution:** Validate identity using cryptographically signed OpenID Connect (OIDC) ID tokens from Google Accounts, extracting immutable subject identifiers (`sub`) and verified emails.
2. **Strict Multi-Tenant Isolation:** Every authenticated user is bound to an `Organization` boundary via `users.org_id` -> `organizations.id`. All database queries, telemetry, simulations, and incident triage are strictly scoped to the tenant.
3. **Zero Token Exposure to Client-Side Storage:** Authentication credentials, tokens, and session secrets must **never** be stored in client-accessible JavaScript storage (`localStorage` or `sessionStorage`). Sessions rely entirely on hardened, `HttpOnly`, `Secure`, `SameSite=Lax` browser cookies.
4. **Resilient Account Linking & Deduplication:** Support existing users who transition to Google Single Sign-On (SSO) by safely linking identity using verified email matching without creating duplicate accounts or breaking audit trails.
5. **Decoupled Authorization:** Google OAuth only verifies identity. It never directly grants administrative privileges or elevates user roles; permissions are strictly determined by internal RiskWise Role-Based Access Control (RBAC).
6. **Comprehensive Audit Logging:** Every authentication lifecycle event (successful sign-in, account linking, failed login, account deactivation, logout) emits a structured record to `audit_logs`.

---

## 2. Existing User Model

### 2.1 Database & SQLAlchemy Model Inspection
Inspection of the actual PostgreSQL database schema and SQLAlchemy 2.0 model in `apps/api/app/models/tenancy.py`:

```python
class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    org_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("organizations.id"), nullable=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    full_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(String(50), default="ANALYST")
    sso_provider: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_active_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    # Relationships
    organization: Mapped[Optional["Organization"]] = relationship("Organization", back_populates="users")
```

### 2.2 Field Inventory & Analysis

| Field Name | Type | Nullable | Constraints / Defaults | Purpose & Auth Role |
|---|---|---|---|---|
| `id` | `VARCHAR(64)` | No | `PRIMARY KEY`, default UUID4 | Internal immutable user identifier. Storing Google's numeric `sub` here is prohibited to preserve UUID consistency. |
| `org_id` | `VARCHAR(64)` | Yes | `FOREIGN KEY (organizations.id)` | Multi-tenant boundary anchor linking user to an Organization. |
| `email` | `VARCHAR(255)` | No | `UNIQUE` | Normalized email address used as human identifier and login handle. |
| `full_name` | `VARCHAR(255)` | Yes | None | User display name, populated from Google ID token `name` claim. |
| `role` | `VARCHAR(50)` | No | `DEFAULT 'ANALYST'` | Assigned RBAC role determining platform capabilities. |
| `sso_provider` | `VARCHAR(50)` | Yes | None | Identity provider tag (`'google'`, `'credentials'`, etc.). |
| `is_active` | `BOOLEAN` | No | `DEFAULT TRUE` | Global account active toggle. If `False`, authentication is rejected. |
| `last_active_at`| `TIMESTAMP WITH TIME ZONE` | Yes | None | Updated on each successful authentication and API session refresh. |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | No | `server_default=now()` | Account creation timestamp. |
| `updated_at` | `TIMESTAMP WITH TIME ZONE` | Yes | `onupdate=now()` | Timestamp of last user profile modification. |

### 2.3 Provider User ID Inspection & Identified Gaps
- **Provider Identification:** The `sso_provider` column exists and can store `'google'`.
- **Provider User ID Status:** **NOT PRESENT**. The current `users` table lacks an immutable provider subject identifier column (e.g., `sso_subject_id` or `google_sub`).
- **Identified Gap:** Relying solely on `email` is fragile because a user's corporate email alias may change in Google Workspace. A dedicated column `sso_subject_id VARCHAR(255) NULLABLE UNIQUE` is required for production-grade OAuth mapping.
- **Optional Attributes:** Google ID tokens also provide profile picture URLs (`picture`). Adding `avatar_url VARCHAR(512) NULLABLE` will enhance UI customization.

---

## 3. Existing Organization Model

### 3.1 Database & SQLAlchemy Model Inspection
Inspection of `organizations` in `apps/api/app/models/tenancy.py`:

```python
class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[Optional[str]] = mapped_column(String(255), unique=True, nullable=True)
    plan: Mapped[str] = mapped_column(String(50), default="ENTERPRISE")
    settings_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    # Relationships
    users: Mapped[list["User"]] = relationship("User", back_populates="organization", cascade="all, delete-orphan")
```

### 3.2 Tenant Association Mechanism
1. **Direct 1:N Relationship:** A user is associated with an organization strictly through `users.org_id -> organizations.id`.
2. **No Membership Intermediary:** The existing schema contains **no** separate membership join table (e.g., `organization_members` or `user_organizations`). A user belongs directly to a single organization.
3. **Strict Compliance:** In accordance with the system specification, **no membership system will be invented**. Google-authenticated users map directly to the `organizations` table via `users.org_id`.

---

## 4. Existing Roles

### 4.1 Schema Verification
Inspection of the PostgreSQL database enum inventory and SQLAlchemy model:
- The `User.role` column defaults to `'ANALYST'`.
- The PostgreSQL domain enum `user_role` defined in the database schema contains 5 values:
  1. `Viewer`
  2. `Analyst`
  3. `OpsManager`
  4. `RiskManager`
  5. `Admin`

### 4.2 Comparison with Original Plan
The preliminary high-level project plan referenced four roles: `ADMIN`, `ANALYST`, `MANAGER`, `VIEWER`.

**Discrepancies Noted:**
1. **Granular Manager Roles:** The actual PostgreSQL schema refines `MANAGER` into two dedicated governance roles:
   - `OpsManager`: Operational execution (rerouting shipments, updating carrier allocations).
   - `RiskManager`: Risk governance (approving critical mitigations, overriding agent recommendations, inspecting audit trails).
2. **Casing:** The PostgreSQL enum values are PascalCase (`Viewer`, `Analyst`, `OpsManager`, `RiskManager`, `Admin`), while the model column default is uppercase `'ANALYST'`.

**Action Taken:** In accordance with the prompt's instructions: **DO NOT change the database**. The existing schema roles are preserved exactly as defined.

---

## 5. Google Identity Mapping

### 5.1 Conceptual Identity Pipeline

```
Google Accounts (OIDC)
        ↓
Google ID Token (sub, email, email_verified, name, picture)
        ↓
Google Subject ID (sub: "109823746198273645120")
        ↓
RiskWise User (users.id, email, sso_provider='google', sso_subject_id)
        ↓
Organization Boundary (users.org_id -> organizations.id)
        ↓
RBAC Role (users.role: 'Analyst' / 'Admin')
```

### 5.2 Provider Identity Storage Analysis
- **Current State:** The `users` table contains `sso_provider` (`VARCHAR(50)`), which can store `'google'`. However, it lacks a dedicated column for Google's immutable OpenID Connect subject identifier (`sub`).
- **Risk of Email-Only Mapping:** Google account emails can change (e.g., corporate domain migrations or renames in Google Workspace), but the `sub` identifier is guaranteed permanent and immutable by Google.
- **Documented Schema Requirement:**
  - Add `sso_subject_id VARCHAR(255) NULLABLE UNIQUE` to `users`.
  - Add index on `sso_subject_id` for $O(1)$ authentication lookup.
  - *Note:* In accordance with Step 1 instructions, this gap is documented here only; no database schema modifications or Alembic migrations are executed in this step.

---

## 6. First Login Flow

When an unauthenticated Google user signs in for the first time, the system executes the following resolution pipeline:

```mermaid
sequenceDiagram
    autonumber
    actor User as User Browser
    participant API as FastAPI (apps/api)
    participant Google as Google Accounts
    participant DB as PostgreSQL 16

    User->>API: Initiates Google OAuth (GET /api/v1/auth/google)
    API-->>User: 302 Redirect to Google OAuth Consent
    User->>Google: Authenticates and grants consent
    Google-->>User: 302 Redirect to /api/v1/auth/google/callback?code=...&state=...
    User->>API: GET /api/v1/auth/google/callback?code=...&state=...
    Note over API: 1. Validate anti-CSRF state token<br/>2. Exchange code for tokens at Google Token Endpoint<br/>3. Cryptographically verify Google ID Token
    API->>DB: Query user by sso_subject_id
    alt User Found by sso_subject_id
        Note over API: Existing Google User
    else Not Found by sso_subject_id
        API->>DB: Query user by normalized email
        alt User Found by Email
            Note over API: Existing User -> Link Account (sso_subject_id, sso_provider='google')
        else Not Found (True First Login)
            Note over API: 4. Resolve Organization Boundary:<br/>- If invite token present: Link to invited org<br/>- If domain matching configured: Link to corporate org<br/>- Else: Provision personal Organization ("Jane Doe's Org", plan='ENTERPRISE')
            API->>DB: INSERT into organizations (id, name, slug, plan, is_active)
            Note over API: 5. Provision New User Record:<br/>- role='Admin' (if org creator) or 'Analyst' (if joining existing)<br/>- sso_provider='google', sso_subject_id=sub<br/>- is_active=True
            API->>DB: INSERT into users (id, org_id, email, full_name, role, sso_provider, sso_subject_id, is_active)
        end
    end
    API->>DB: Update last_active_at = now()
    Note over API: 6. Mint session token & issue HttpOnly cookie
    API-->>User: Set-Cookie: riskwise_session=...; HttpOnly; Secure; SameSite=Lax<br/>302 Redirect to / (or validated return_to)
```

### 6.1 Role Assignment Rules on First Login
1. **Self-Service Organization Provisioning:** If a new Google user provisions a brand-new organization, they are designated the initial tenant administrator: `role = 'Admin'`.
2. **Joining an Existing Organization (via Invite or Domain Match):** If a user joins an existing organization, they are assigned the default standard role: `role = 'Analyst'`.
3. **No Automatic Privilege Escalation:** Under no circumstances is `Admin` granted to users joining an existing tenant without explicit administrative promotion.

---

## 7. Existing Account Linking

If a user already exists in RiskWise (e.g., created by an admin or previously registered) and logs in via Google:

1. **Verified Email Requirement:** The Google ID token claim `email_verified` **must be `true`**. Unverified Google accounts are rejected immediately.
2. **Email Normalization:**
   ```python
   normalized_email = google_claims["email"].strip().lower()
   ```
3. **Lookup & Linking Sequence:**
   - **Step A:** Query `User` by `sso_subject_id == sub`. If match found, authentication proceeds.
   - **Step B:** If not found by `sub`, query `User` by `email == normalized_email`.
   - **Step C:** If matched by email, verify account status:
     - If `user.is_active == False`: **Reject** with `HTTP 403 Forbidden` (`Account deactivated. Contact your organization administrator.`).
     - If `user.is_active == True`: Update the user record to link Google SSO:
       - `user.sso_provider = 'google'`
       - `user.sso_subject_id = sub`
       - `user.last_active_at = func.now()`
       - Commit transaction and log account link event in `audit_logs`.
4. **Duplicate Prevention:** The database enforces a `UNIQUE` constraint on `users.email`. Attempting to create a duplicate user with the same email will fail at the database level.

---

## 8. Google OAuth Configuration

### 8.1 Google Cloud Platform Setup & Application Type
- **Application Type:** **Web application** (registered in Google Cloud Console under *APIs & Services > Credentials*).
- **Client Type:** **Google OAuth 2.0 Client ID**.
- **Authorized JavaScript Origins:**
  - Development: `http://localhost:3000` (Next.js frontend)
  - Production: `https://app.riskwise.io`
- **Authorized Redirect URIs:**
  - Development: `http://localhost:8000/api/v1/auth/google/callback`
  - Production: `https://api.riskwise.io/api/v1/auth/google/callback` (or configured value of `GOOGLE_REDIRECT_URI`)

### 8.2 Required OAuth Scopes
RiskWise requires only minimal standard OpenID Connect (OIDC) identity scopes:
1. **`openid`**: Authenticates the user and issues the signed ID token containing the immutable subject identifier (`sub`).
2. **`email`**: Provides access to the user's primary email address and `email_verified` boolean claim.
3. **`profile`**: Provides access to the user's display name (`name`) and profile image (`picture`).

> [!IMPORTANT]
> **No Unnecessary Scopes:** In compliance with the principle of least privilege, RiskWise does **not** request access to sensitive Google scopes (e.g., Google Drive, Gmail, Calendar, Contacts, or YouTube).

### 8.3 Required Environment Variables
The application consumes OAuth credentials strictly through environment variables configured in `apps/api`:

```env
# Google OAuth 2.0 Server-Side Credentials
GOOGLE_CLIENT_ID=your-google-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-google-client-secret
GOOGLE_REDIRECT_URI=http://localhost:8000/api/v1/auth/google/callback
```

### 8.4 Frontend / Backend Security Boundary
- **Zero Client-Side Secrets:** `GOOGLE_CLIENT_SECRET` is never provided to Next.js or bundled into browser code.
- **No `NEXT_PUBLIC_` Secret:** The variable `NEXT_PUBLIC_GOOGLE_CLIENT_SECRET` must **never** be created.
- **Backend Authorization Flow:** The frontend does not handle OAuth token exchanges directly; it initiates authentication by redirecting the user to `GET /api/v1/auth/google` on the backend API. The backend securely executes the authorization code exchange with Google over a private HTTPS backchannel.

### 8.5 Redirect URI Strategy
- The callback URI is resolved dynamically from `settings.GOOGLE_REDIRECT_URI`.
- **Development Pattern:** `http://localhost:8000/api/v1/auth/google/callback`
- **Production Pattern:** `https://api.riskwise.io/api/v1/auth/google/callback`
- No hardcoded callback URLs exist in application logic.

### 8.6 OAuth State & Anti-CSRF Protection
The authorization flow **must** generate and validate an unpredictable OAuth `state` value:
- **Generation:** A cryptographically signed token (HMAC-SHA256) embedding a high-entropy nonce, timestamp, and validated `return_to` path.
- **Validation:** When Google redirects to `/api/v1/auth/google/callback`, the backend verifies the state signature and checks that it has not expired (< 5 minutes TTL).
- **Protection:** Completely eliminates Cross-Site Request Forgery (CSRF) and login injection attacks.

### 8.7 Google Identity Mapping & Subject Identifier
- **Primary Identifier:** Google's OpenID Connect `sub` (subject identifier) is the immutable, unique anchor representing the external identity.
- **Email Matching:** Email addresses are normalized and used for account matching and deduplication, but identity persistence relies on `sub`.
- **Documented Schema Gap:** The current `users` table lacks an `sso_subject_id VARCHAR(255) NULLABLE UNIQUE` column. This schema change is documented for a future migration.

### 8.8 Production Configuration Notes
1. Enforce HTTPS across all endpoints in staging and production.
2. In production, session cookies must have `Secure=True`, `HttpOnly=True`, and `SameSite=Lax`.
3. Protect the callback endpoint with rate limiting (e.g., max 10 requests/minute per IP) to prevent denial-of-service and brute force replay attempts.

---

## 9. OAuth Redirect URLs & Post-Auth Navigation

### 9.1 Environment Redirect Matrix

| Environment | OAuth Callback (Backend Endpoint) | Post-Auth Destination (Frontend) |
|---|---|---|
| **Development** | `http://localhost:8000/api/v1/auth/google/callback` | `http://localhost:3000/` or `/dashboard` |
| **Staging** | `https://api.staging.riskwise.io/api/v1/auth/google/callback` | `https://staging.riskwise.io/dashboard` |
| **Production** | `https://api.riskwise.io/api/v1/auth/google/callback` | `https://app.riskwise.io/dashboard` |

### 9.2 Open Redirect Prevention
- The `return_to` query parameter allows the frontend to request a post-login destination (e.g., `/shipments/SHP-771`).
- The backend validates `return_to` against a strict relative-path regular expression (`^/[a-zA-Z0-9_\-\/]*$`).
- Any absolute URLs (e.g., `https://evil.com`) or protocol-relative URLs (`//evil.com`) are rejected, defaulting to `/`.


---

## 10. Authentication API Contract

All authentication endpoints are grouped under `/api/v1/auth/`.

### 10.1 `GET /api/v1/auth/google`
- **Purpose:** Initiate Google OAuth 2.0 authorization code flow.
- **Authentication Requirement:** Public.
- **Request Parameters:**
  - `return_to` *(optional, string)*: Validated relative URI to navigate to after authentication.
- **Flow:**
  1. Generates a cryptographically signed anti-CSRF state token embedding a nonce, timestamp, and validated `return_to`.
  2. Constructs Google authorization URL requesting scopes: `openid email profile`.
- **Response (HTTP 302 Found):**
  - Redirects browser to `https://accounts.google.com/o/oauth2/v2/auth?client_id=...&redirect_uri=...&response_type=code&scope=openid%20email%20profile&state=...`
- **Failure Cases:**
  - `400 Bad Request`: If `return_to` violates safe relative path validation.

---

### 10.2 `GET /api/v1/auth/google/callback`
- **Purpose:** Handle Google OAuth 2.0 authorization callback, exchange authorization code for tokens, resolve user/organization, and issue session cookie.
- **Authentication Requirement:** Public (invoked by browser redirect from Google).
- **Request Parameters (Query):**
  - `code` *(required, string)*: Google authorization code.
  - `state` *(required, string)*: Anti-CSRF state token issued by `/api/v1/auth/google`.
- **Processing:**
  1. Validates `state` signature and ensures token is unexpired (< 5 minutes).
  2. Exchanges `code` for Google access token and ID token via backchannel POST to `https://oauth2.googleapis.com/token`.
  3. Validates ID token signature against Google's public JWKS.
  4. Confirms `email_verified == true`.
  5. Executes User and Organization resolution (Sections 6 & 7).
  6. Mints session token and sets secure session cookie.
- **Success Response (HTTP 302 Found):**
  - **Headers:** `Set-Cookie: riskwise_session=<token>; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=604800`
  - **Location:** Validated `return_to` or `/`.
- **Failure Cases:**
  - `400 Bad Request` -> 302 Redirect to `/auth?error=invalid_state` (CSRF state mismatch or expired).
  - `401 Unauthorized` -> 302 Redirect to `/auth?error=oauth_exchange_failed` (Code exchange rejected by Google).
  - `403 Forbidden` -> 302 Redirect to `/auth?error=account_deactivated` (`is_active == False`).
  - `403 Forbidden` -> 302 Redirect to `/auth?error=unverified_email` (`email_verified == False`).

---

### 10.3 `GET /api/v1/auth/me`
- **Purpose:** Retrieve profile, organization context, and RBAC permissions for the currently authenticated user.
- **Authentication Requirement:** Authenticated (Valid `riskwise_session` cookie or `Authorization: Bearer <token>`).
- **Request Body:** None.
- **Success Response (HTTP 200 OK):**
  ```json
  {
    "id": "usr_91a8e7d2b4c1",
    "email": "analyst@riskwise.io",
    "full_name": "Jane Doe",
    "role": "Analyst",
    "org_id": "org_48f0b1a3e9d2",
    "organization": {
      "id": "org_48f0b1a3e9d2",
      "name": "Global Logistics Corp",
      "slug": "global-logistics",
      "plan": "ENTERPRISE"
    },
    "permissions": [
      "views:read",
      "scenarios:run",
      "recommendations:write"
    ]
  }
  ```
- **Failure Cases:**
  - `401 Unauthorized`: Session cookie missing, expired, or invalid (`{"detail": "Not authenticated"}`).
  - `403 Forbidden`: User account deactivated (`{"detail": "Account has been deactivated"}`).

---

### 10.4 `POST /api/v1/auth/logout`
- **Purpose:** Terminate session, invalidate server session token, and clear client session cookie.
- **Authentication Requirement:** Authenticated.
- **Request Body:** None.
- **Success Response (HTTP 200 OK):**
  - **Headers:** `Set-Cookie: riskwise_session=; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=0`
  - **Body:**
    ```json
    {
      "status": "ok",
      "message": "Successfully logged out"
    }
    ```
- **Failure Cases:**
  - `401 Unauthorized`: If request carries no active session.

---

## 11. Session Architecture

### 11.1 Session Storage & Engine
RiskWise implements a server-managed, TTL-backed session persistence model:
- **Primary Store:** **Valkey / Redis** (configured via `settings.REDIS_URL`) utilizing native Redis key expiration (`EXPIRE` / `SETEX`). Key pattern: `session:{session_id}`.
- **Fallback / Local Dev Store:** Thread-safe, in-memory store (`MemorySessionStore`) with atomic locks and active timestamp validation.
- **Payload Schema:** `SessionData` encapsulates `session_id`, `user_id`, `organization_id`, `role`, `created_at`, `expires_at`.
- **Zero Sensitive Data:** Google client secrets, access tokens, refresh tokens, passwords, database credentials, and external API keys are **never** stored in session state.

### 11.2 Cryptographically Unpredictable Session Generation
- **Generator:** `secrets.token_urlsafe(32)` yielding a 256-bit entropy, 43-character URL-safe string.
- **Prohibitions:** User IDs, emails, sequential integers, and client-signed JWTs are strictly forbidden as session identifiers.

### 11.3 Session Lifecycle & State Transitions
1. **Creation:** Generated upon successful authentication (Google OAuth or credentials) with TTL.
2. **Retrieval & Validation:** Looked up on each request via cookie; verified against UTC clock. Expired sessions are deleted on-the-fly.
3. **Session Fixation Prevention & Rotation:** `rotate_session(old_session_id)` issues a fresh random session token, copies user/role/org context, and deletes the pre-existing token.
4. **Revocation & Logout:** Explicit deletion from the store upon `POST /api/v1/auth/logout` or administrator deactivation.

### 11.4 Cookie Configuration & Attributes

| Attribute | Value | Behavior & Security Guarantee |
|---|---|---|
| **Name** | `riskwise_session` | Standard namespace identifier configured via `settings.SESSION_COOKIE_NAME`. |
| **HttpOnly** | `True` | **Enforced in all environments.** Prevents client-side scripts from reading session tokens, mitigating XSS attacks. |
| **Secure** | `True` in Production (`False` in local HTTP dev) | Evaluated via `settings.session_cookie_secure` (`APP_ENV == "production"`). Enforces HTTPS transmission in production. |
| **SameSite** | `Lax` | Configured via `settings.SESSION_SAME_SITE`. Prevents CSRF by blocking third-party cross-site request cookie attachment while permitting top-level navigation. |
| **Path** | `/` | Available across all API and web application paths. |
| **Max-Age** | `604800` (7 days) | Configured via `settings.SESSION_MAX_AGE_SECONDS`. |

### 11.5 Authentication Dependency Pipeline
- **`get_session_data`:** Reads cookie, validates session token against the session store, returns `SessionData`. Missing or expired cookie raises `HTTP 401 Unauthorized`.
- **`get_authenticated_context`:** Resolves user from database via `session_data.user_id`. Verifies `user.is_active == True`. If inactive, revokes session and raises `HTTP 401 Unauthorized`. Resolves `user.organization` and ensures `organization.is_active == True` (raises `HTTP 403 Forbidden` if suspended). Returns `AuthenticatedContext`.
- **`get_current_user`:** Dependency returning active `User` entity.
- **`get_current_organization`:** Dependency returning active `Organization` entity.

### 11.6 Multi-Tenant Organization Isolation
- Every authenticated request is tied to an authoritative tenant: `context.organization_id`.
- The application enforces:
  ```python
  verify_tenant_access(record.org_id, context)
  ```
  Rejecting cross-tenant accesses with `HTTP 403 Forbidden` (`Access denied: organization boundary mismatch`). Client-supplied `org_id` values in request bodies are ignored or validated strictly against `context.organization_id`.

### 11.7 Role-Based Authorization
- **Dependency Factory:** `require_role(*allowed_roles)`
- **Behavior:**
  - Unauthenticated request: `HTTP 401 Unauthorized`.
  - Authenticated user with insufficient role: `HTTP 403 Forbidden` (`{"detail": "Insufficient permissions"}`).
- **Authoritative Boundary:** Evaluated exclusively on the FastAPI backend; frontend UI visibility never acts as a security boundary.

### 11.8 CSRF Strategy
1. **`SameSite=Lax` Cookie Defense:** Browser blocks automatic session cookie inclusion on cross-origin POST, PUT, DELETE, and PATCH requests.
2. **Cryptographic OAuth State:** Google OAuth callbacks validate an HMAC-SHA256 signed `state` parameter (5-minute TTL) to eliminate login CSRF.
3. **CORS Preflight & Header Checks:** Sensitive mutating operations require preflight-validated origins.

### 11.9 CORS Strategy
- **Restricted Allowed Origins:** `settings.CORS_ORIGINS` explicitly whitelists trusted frontend hosts (e.g. `http://localhost:3000`, `https://app.riskwise.io`).
- **Strict Prohibition:** Wildcard `allow_origins=["*"]` is **strictly forbidden** with `allow_credentials=True`.

---

## 12. Public and Protected Routes

Below is the definitive classification of RiskWise API endpoints:

| Endpoint | Method | Classification | Access Requirement | Description |
|---|---|---|---|---|
| `/health` | `GET` | **Public** | None | Service liveness probe. |
| `/ready` | `GET` | **Public** | None | Container readiness probe. |
| `/health/db` | `GET` | **Public** | None | PostgreSQL database connectivity probe (`SELECT 1`). |
| `/` | `GET` | **Public** | None | API root metadata endpoint. |
| `/openapi.json` | `GET` | **Public** | None | OpenAPI 3.1 specification schema. |
| `/docs` | `GET` | **Public** | None | Interactive Swagger UI. |
| `/redoc` | `GET` | **Public** | None | ReDoc API documentation. |
| `/api/v1/auth/google` | `GET` | **Authentication (Public)** | None | Initiates Google OAuth 2.0 authorization code redirect. |
| `/api/v1/auth/google/callback` | `GET` | **Authentication (Public)** | None | Callback receiver from Google Accounts. |
| `/api/v1/auth/me` | `GET` | **Authenticated** | Active Session Cookie | Returns profile, active organization, and permissions. |
| `/api/v1/auth/logout` | `POST` | **Authenticated** | Active Session Cookie | Revokes server session and clears client cookie. |
| **All Business APIs** | `ANY` | **PROTECTED** | Active Session & Role | Scenarios, shipments, risks, suppliers, agents, digital twin, governance (enforce `get_authenticated_context`). |


## 13. Authorization Boundary

### 13.1 Authentication vs. Authorization

```
+-------------------------------------------------------------------------+
| AUTHENTICATION ("Who is this user?")                                    |
| - Proved via Google Accounts OAuth 2.0                                  |
| - Confirms ownership of email and immutable subject ID                  |
| - Output: Validated user identity (User record)                         |
+-------------------------------------------------------------------------+
                                    ↓
+-------------------------------------------------------------------------+
| AUTHORIZATION ("What can this user do?")                                |
| - Boundary 1: Tenant Isolation (User -> Organization via org_id)        |
| - Boundary 2: RBAC Role (User -> Role in ['Viewer'..'Admin'])           |
| - Boundary 3: Capability Guard (FastAPI dependencies & DB RLS)          |
| - Output: Permitted or Denied action                                    |
+-------------------------------------------------------------------------+
```

### 13.2 RBAC Permission Matrix

| Action / Capability | Viewer | Analyst | OpsManager | RiskManager | Admin |
|---|:---:|:---:|:---:|:---:|:---:|
| View risks, shipments, network topology | ✓ | ✓ | ✓ | ✓ | ✓ |
| Run scenario simulations & triage | | ✓ | ✓ | ✓ | ✓ |
| Create & edit recommendations | | ✓ | ✓ | ✓ | ✓ |
| Trigger AI agent investigation workflows | | ✓ | ✓ | ✓ | ✓ |
| Execute operational actions (rerouting) | | | ✓ | ✓ | ✓ |
| Approve / reject critical mitigations | | | | ✓ | ✓ |
| Inspect audit logs & governance history | | | | ✓ | ✓ |
| Manage users, roles & organization config | | | | | ✓ |

Google OAuth establishes identity only; authorization permissions are strictly derived from the internal RBAC role.

---

## 14. Security Requirements

To ensure zero vulnerabilities, the implementation of Google OAuth must satisfy the following security controls:

1. **State Parameter Verification:** Anti-CSRF `state` parameter must be cryptographically signed (HMAC-SHA256) with a 5-minute time-to-live (TTL). Single-use only.
2. **Redirect URI Whitelisting:** Both the OAuth callback URI and any post-authentication `return_to` destinations must be strictly whitelisted.
3. **Verified Email Enforcement:** Only Google accounts with `email_verified == true` may access the application.
4. **Rate Limiting:** Protect all `/api/v1/auth/*` endpoints with rate limiting (e.g., maximum 10 requests per minute per IP).
5. **No Account Enumeration:** Error messages must never reveal whether an account exists.
6. **Tenant Boundary Enforcement:** The application context must **never** accept `org_id` from client request bodies. The active tenant is extracted exclusively from the authenticated session.
7. **Timing Attack Protection:** Constant-time comparison (`hmac.compare_digest`) for all cryptographic tokens and state checks.
8. **Audit Trail Generation:** All authentication events must write an audit record to `audit_logs` capturing `user_id`, `actor_type='USER'`, `action`, `status`, and client IP.

---

## 15. Frontend Contract

### 15.1 Authentication View (`/auth`)
The initial authentication page in `apps/web` will reside at route `/auth`:

- **Views Supported:**
  - "Sign In" view
  - "Sign Up" view
- **Primary Authentication Action:**
  - Prominent "Continue with Google" button with the official Google emblem.
  - Clicking "Continue with Google" initiates navigation to:
    ```
    ${NEXT_PUBLIC_API_URL}/api/v1/auth/google?return_to=${encodeURIComponent(returnTo)}
    ```
- **Error States:**
  - Reads `?error=` query parameter from redirect URL:
    - `?error=invalid_state`: "Authentication session expired. Please try again."
    - `?error=oauth_exchange_failed`: "Unable to verify Google account. Please try again."
    - `?error=account_deactivated`: "Your account has been deactivated. Please contact your organization administrator."
    - `?error=unverified_email`: "Your Google email address is unverified. Please verify your email with Google and retry."
- **Loading & Transitions:**
  - Clean spinner state with `aria-busy="true"` upon clicking the OAuth button.
  - Disabled button state during in-flight redirects to prevent duplicate handshakes.
- **Client Session Bootstrapping:**
  - After successful login, the frontend calls `GET /api/v1/auth/me` with `credentials: "include"` to fetch the authenticated user profile and hydrate the global state.

---

## 16. Required Schema Changes

> [!IMPORTANT]
> In accordance with Phase 3 Step 1 instructions, **NO schema changes or migrations are executed in this step**. The following items are documented as necessary requirements for subsequent migration steps:

1. **`sso_subject_id` Column on `users`:**
   - **Specification:** `VARCHAR(255) NULLABLE UNIQUE`
   - **Index:** `CREATE UNIQUE INDEX idx_users_sso_subject_id ON users(sso_subject_id) WHERE sso_subject_id IS NOT NULL;`
   - **Purpose:** Store Google's immutable OpenID Connect subject identifier (`sub`) to guarantee permanent account mapping regardless of email alias changes.
2. **Optional: `avatar_url` Column on `users`:**
   - **Specification:** `VARCHAR(512) NULLABLE`
   - **Purpose:** Store the profile image URL provided by Google for display in navigation headers.
3. **Optional: `email_verified` Column on `users`:**
   - **Specification:** `BOOLEAN DEFAULT TRUE NOT NULL`
   - **Purpose:** Explicit audit trail recording proof-of-inbox verification status.

---

## 18. Frontend Authentication

> **Phase:** Phase 3 — Google Authentication: Step 5  
> **Status:** Implemented & Verified in `apps/web` (Next.js 16 App Router)  
> **Primary Route:** `/auth`  

### 18.1 Route & View Architecture
The RiskWise authentication interface is implemented at route `/auth` (`apps/web/app/auth/page.tsx`) using Next.js 16 App Router, React 19, and Tailwind CSS v4:
- **Single Viewport Experience:** Focused, zero-scroll desktop experience with precision visual hierarchy, liquid-metal styling, and subtle ambient lighting.
- **Client-Side Suspense:** The core authentication interactive content (`AuthContent`) is wrapped in a `<Suspense>` boundary to guarantee static optimization and safe resolution of `useSearchParams()`.
- **Mode Switcher (`AuthModeSwitch`):** Implements an accessible tablist (`role="tablist"`, `role="tab"`) toggling between:
  1. `Sign In`: Directs users with active enterprise accounts to access their workspace.
  2. `Sign Up`: Informs new users of instant organization tenant provisioning via Google Workspace Single Sign-On (SSO).
- **Backend-Truth Compliance:** Because the backend exclusively supports Google OAuth SSO, the interface accurately communicates Google Workspace SSO as the active provider and never displays simulated email/password inputs or fake handlers.

### 18.2 Google Authentication Button Flow
The primary interaction mechanism is the `GoogleAuthButton` (`apps/web/components/auth/GoogleAuthButton.tsx`):
1. **User Action:** User clicks "Continue with Google" (or "Sign up with Google Workspace").
2. **Double-Click Prevention & Progress UX:** Button instantly transitions to a disabled loading state displaying an animated spinner (`Loader2`) and the message `"Connecting to Google…"`, setting `aria-busy="true"`.
3. **Endpoint Resolution:** Constructs the real backend URL using `process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"`.
4. **Open-Redirect Hardening:** The `return_to` parameter is strictly validated (`returnTo.startsWith("/") && !returnTo.startsWith("//") ? returnTo : "/"`) before being encoded into query parameters.
5. **Direct Navigation:** The browser navigates directly to:
   ```
   ${NEXT_PUBLIC_API_URL}/api/v1/auth/google?return_to=${encodeURIComponent(sanitizedReturnTo)}
   ```
6. **Backend OAuth Initiation:** The FastAPI backend generates an HMAC-SHA256 signed anti-CSRF state token and issues an HTTP 302 redirect to Google Accounts consent.
7. **Callback & Session Issuance:** After consent, Google redirects to `/api/v1/auth/google/callback`. The backend verifies the state, resolves or provisions the tenant user, sets the secure `riskwise_session` HttpOnly cookie, and redirects the browser back to the frontend.

### 18.3 Authenticated User Redirect
To eliminate unnecessary authentication friction:
1. **Mount Hook:** On mount, `AuthContent` executes an asynchronous credentialed probe:
   ```typescript
   GET ${NEXT_PUBLIC_API_URL}/api/v1/auth/me
   credentials: "include"
   ```
2. **Active Session Detected (HTTP 200):** If an active session is returned, the component displays an accessible status message (`"Session verified. Redirecting to RiskWise workspace…"`) and executes:
   ```typescript
   router.replace(returnTo);
   ```
3. **Unauthenticated (HTTP 401 / Network Error):** The auth card renders normally.

### 18.4 Error Handling & User Experience
The `AuthErrorBanner` (`apps/web/components/auth/AuthErrorBanner.tsx`) provides accessible, sanitized feedback without exposing internal stack traces, tokens, or infrastructure details:
- **Screen Reader Accessibility:** Uses `role="alert"`, `aria-live="assertive"`, and `tabIndex={-1}` to immediately notify assistive technology.
- **Backend Error Code Mapping:**
  - `invalid_state`: "Your authentication session timed out or security verification failed. Please try again."
  - `oauth_exchange_failed`: "Google authentication could not be completed. Please try again or contact support."
  - `account_deactivated`: "Your RiskWise account has been deactivated. Please contact your organization administrator."
  - `unverified_email`: "Your Google email address is not verified. Please verify your email with Google before signing in."
  - `google_not_configured`: "Google Single Sign-On is not currently enabled on this environment."
  - `access_denied`: "Google sign-in request was cancelled. You may retry whenever you are ready."
  - `session_expired`: "Your previous session has expired. Please sign in to resume your workspace."
  - `network_error`: "Unable to connect to the authentication server. Please check your connection and retry."
- **Dismissal & URL Hygiene:** Clicking the dismiss button removes the visual banner and cleanses the query string (`?error=...`) from the browser address bar via `window.history.replaceState`.

### 18.5 Environment Variables
The frontend requires only a single public environment variable:
- `NEXT_PUBLIC_API_URL`: Points to the FastAPI backend API gateway (defaults to `http://localhost:8000` in local development).
- **Prohibition:** Under no circumstances are `GOOGLE_CLIENT_SECRET`, AWS credentials, database URIs, or session secrets exposed to the frontend or prefixed with `NEXT_PUBLIC_`.

### 18.6 Security Considerations
1. **Zero Client-Side Token Storage:** Tokens and session IDs are never stored in `localStorage`, `sessionStorage`, or IndexedDB.
2. **HttpOnly Cookie Boundary:** The session cookie `riskwise_session` is managed strictly by the FastAPI backend with `HttpOnly=True`, `SameSite=Lax`, and `Secure=True` (in production).
3. **Open-Redirect Defense:** Relative path sanitization prevents external phishing redirects via `return_to`.
4. **Reduced Motion & Accessibility:** Adheres to WCAG 2.2 AA contrast standards, keyboard tab navigation with visible focus rings (`focus-visible:ring-2`), and `@media (prefers-reduced-motion: reduce)` styling.

---

## 19. Frontend / Backend Integration

> **Phase:** Phase 3 — Google Authentication: Step 6  
> **Status:** Completed, Verified & Tested  
> **Target Subsystems:** `apps/web` (Next.js 16 App Router) ↔ `apps/api` (FastAPI 0.115)  

### 19.1 Frontend API Configuration
- **Base URL Resolution:** Resolved dynamically from `process.env.NEXT_PUBLIC_API_URL` (defaults to `http://localhost:8000` in development). Never hardcoded.
- **Client Implementation (`apps/web/lib/api/client.ts`):** Single unified `apiClient` instance enforcing:
  - `credentials: "include"` on all HTTP requests to guarantee cross-origin transmission of the browser's HttpOnly `riskwise_session` cookie.
  - Standardized JSON serialization, headers (`Accept: application/json`), and error parsing.
  - `ApiClientError` normalization capturing HTTP status, detail, and error codes.
  - Global `onUnauthorized` callback dispatcher for reactive session expiration handling.

### 19.2 Google Login & Handshake Flow
```
User (Browser)
    ↓  Click "Continue with Google"
Next.js (apps/web)
    ↓  Navigation to `${NEXT_PUBLIC_API_URL}/api/v1/auth/google?return_to=...`
FastAPI Gateway (apps/api)
    ↓  302 Redirect to Google Accounts Consent
Google Accounts (OIDC)
    ↓  User grants consent & Google redirects to callback
FastAPI Gateway (`/api/v1/auth/google/callback`)
    ↓  Verifies HMAC state, exchanges code for ID token, maps user & organization
FastAPI Session Service
    ↓  Mints 256-bit session token, stores in cache (TTL 7 days)
    ↓  Issues Set-Cookie: riskwise_session=...; HttpOnly; SameSite=Lax; Path=/
FastAPI Gateway
    ↓  302 Redirect to Frontend (`/` or validated return_to)
Next.js AuthProvider (apps/web)
    ↓  GET /api/v1/auth/me (credentials: "include")
    ↓  Resolves User + Organization + Role + Capabilities
Authenticated Application Active
```

### 19.3 Session Restoration & `/api/v1/auth/me`
On application startup, the centralized `AuthProvider` (`apps/web/lib/auth/AuthContext.tsx`) automatically initiates session restoration:
- Calls `GET /api/v1/auth/me` with `credentials: "include"`.
- **Response Mapping:**
  ```json
  {
    "id": "usr_91a8e7d2b4c1",
    "email": "analyst@riskwise.io",
    "full_name": "Jane Doe",
    "role": "ANALYST",
    "org_id": "org_48f0b1a3e9d2",
    "organization": {
      "id": "org_48f0b1a3e9d2",
      "name": "Global Logistics Corp",
      "slug": "global-logistics",
      "plan": "ENTERPRISE",
      "is_active": true
    },
    "permissions": ["views:read", "scenarios:run", "recommendations:write"]
  }
  ```
- **State Machine Transitions:**
  - `HTTP 200` with active user and active organization → `status: "authenticated"`
  - `HTTP 200` with `org_id === null` → `status: "onboarding-required"`
  - `HTTP 200` with `organization.is_active === false` → `status: "access-pending"`
  - `HTTP 401 Unauthorized` → `status: "unauthenticated"`
  - `HTTP 403 Forbidden` → `status: "access-denied"` (preserves session, no automatic logout)
  - `Network / 500 Failure` → `status: "authentication-error"`

### 19.4 Logout Behavior
Frontend logout is bound directly to the real backend revocation endpoint:
1. User activates "Sign Out".
2. `logout()` executes `POST /api/v1/auth/logout` via `apiClient.auth.logout()` with `credentials: "include"`.
3. The FastAPI backend deletes the session from the server-side store (Redis/Memory) and issues an expired `riskwise_session` cookie (`Max-Age=0`).
4. `AuthProvider` clears all cached user and organization context.
5. The browser navigates immediately to `/auth`.

### 19.5 Protected Routes & Guard Architecture
Protected routes are guarded by `<ProtectedRoute>` (`apps/web/components/auth/ProtectedRoute.tsx`):
- **Unauthenticated Access:** Seamlessly redirects unauthenticated users to `/auth?return_to=${encodeURIComponent(pathname)}`.
- **Session Expiration:** When an authenticated request fails with `401 Unauthorized`, `apiClient` triggers `notifyUnauthorized()`, clearing client state and redirecting to `/auth?error=session_expired`. Redirect loops are strictly avoided by checking `pathname !== "/auth"`.
- **Granular RBAC Authorization (403):** Supports optional `requiredRole` and `requiredPermission` parameters. If a user lacks the required role or permission:
  - The guard renders an accessible 403 Forbidden panel.
  - **Crucial Security Principle:** The user is **NOT** logged out. Their session remains active, and a "Return to Home" action is provided.
- **Onboarding Required State:** Renders a workspace setup guide informing the user their Google account is verified, but awaiting organization association.
- **Access Pending State:** Informs the user their organization is pending administrative review or subscription activation.

### 19.6 Cross-Origin Resource Sharing (CORS) Policy
- **Configured Origins:** Backend `CORS_ORIGINS` explicitly whitelists `["http://localhost:3000", "http://127.0.0.1:3000"]` (and staging/production domains).
- **Credentials Enforcement:** Backend `CORSMiddleware` enforces `allow_credentials=True`.
- **Strict Prohibition:** Wildcard `allow_origins=["*"]` is strictly prohibited with credentials.

### 19.7 Zero-Token Client Security Invariant
All authentication assertions enforce that:
- `localStorage` contains zero tokens, session IDs, or secrets.
- `sessionStorage` contains zero tokens, session IDs, or secrets.
- `GOOGLE_CLIENT_SECRET` is never bundled or referenced in frontend code.
- All session boundaries reside exclusively within the browser's HttpOnly cookie jar managed by the FastAPI backend.



