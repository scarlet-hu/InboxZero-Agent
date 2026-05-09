"""OAuth + session endpoints.

Flow:
  GET  /auth/login    -> 302 to Google (PKCE + signed state)
  GET  /auth/callback -> exchange code, set session cookie, 302 to frontend
  POST /auth/logout   -> clear cookie
  GET  /auth/me       -> current user info, 401 if no session
"""
from app.services.auth import (
    SESSION_COOKIE_NAME,
    SESSION_TTL_SECONDS,
    SessionData,
    build_google_flow,
    email_from_userinfo,
    extract_email_from_id_token,
    frontend_url,
    generate_oauth_state,
    generate_pkce_verifier,
    get_current_session,
    is_valid_oauth_state,
    pop_verifier,
    session_cookie_kwargs,
    sign_session,
    store_verifier,
)
from fastapi import APIRouter, Depends, Query, Response, status
from fastapi.responses import JSONResponse, RedirectResponse

router = APIRouter()


@router.get("/login")
def auth_login() -> RedirectResponse:
    flow = build_google_flow()
    state = generate_oauth_state()
    verifier = generate_pkce_verifier()
    flow.code_verifier = verifier
    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state=state,
    )
    store_verifier(state, verifier)
    return RedirectResponse(auth_url, status_code=status.HTTP_302_FOUND)


@router.get("/callback")
def auth_callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
) -> RedirectResponse:
    front = frontend_url()

    def _redirect_with_error(reason: str) -> RedirectResponse:
        return RedirectResponse(f"{front}/?auth_error={reason}", status_code=status.HTTP_302_FOUND)

    if error:
        return _redirect_with_error(error)
    if not code or not is_valid_oauth_state(state):
        return _redirect_with_error("invalid_state")

    verifier = pop_verifier(state)
    flow = build_google_flow(state=state)
    if verifier:
        flow.code_verifier = verifier

    try:
        flow.fetch_token(code=code)
    except Exception as exc:
        return _redirect_with_error(f"token_exchange_failed:{exc.__class__.__name__}")

    creds = flow.credentials
    raw_token = getattr(flow.oauth2session, "token", {}) or {}
    email = (
        extract_email_from_id_token(raw_token.get("id_token"))
        or email_from_userinfo(creds.token)
        or "unknown@example.com"
    )

    session = SessionData(
        email=email,
        token=creds.token,
        refresh_token=creds.refresh_token,
        token_uri=creds.token_uri,
        scopes=list(creds.scopes or []),
    )
    jwt_token = sign_session(session)

    resp = RedirectResponse(f"{front}/dashboard", status_code=status.HTTP_302_FOUND)
    resp.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=jwt_token,
        httponly=True,
        max_age=SESSION_TTL_SECONDS,
        path="/",
        **session_cookie_kwargs(),
    )
    return resp


@router.get("/demo-login")
def auth_demo_login() -> RedirectResponse:
    """Mint a demo session — no Google OAuth required.

    Lets reviewers exercise the full UI without granting access to a real
    Gmail account. The session is flagged is_demo=True; protected endpoints
    serve fixture data instead of hitting Google APIs.
    """
    session = SessionData(
        email="demo@inboxzero.dev",
        token="demo",
        refresh_token=None,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=["demo"],
        is_demo=True,
    )
    jwt_token = sign_session(session)
    resp = RedirectResponse(f"{frontend_url()}/dashboard", status_code=status.HTTP_302_FOUND)
    resp.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=jwt_token,
        httponly=True,
        max_age=SESSION_TTL_SECONDS,
        path="/",
        **session_cookie_kwargs(),
    )
    return resp


@router.post("/logout")
def auth_logout() -> Response:
    resp = Response(status_code=status.HTTP_204_NO_CONTENT)
    resp.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return resp


@router.get("/me")
def auth_me(session: SessionData = Depends(get_current_session)) -> JSONResponse:
    return JSONResponse({
        "email": session.email,
        "scopes": session.scopes,
        "is_demo": session.is_demo,
    })
