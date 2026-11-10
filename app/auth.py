import secrets

from fastapi import Header, HTTPException

from app import config


def require_key(authorization: str | None = Header(default=None)) -> None:
    """Reject any request that does not carry the shared API key as a Bearer token."""
    scheme, _, token = (authorization or "").partition(" ")
    # compare_digest takes the same time however many characters match, so response
    # timing cannot be used to guess the key. An unset key never matches anything.
    if (
        config.API_KEY
        and scheme.lower() == "bearer"
        and secrets.compare_digest(token.encode(), config.API_KEY.encode())
    ):
        return
    raise HTTPException(401, "invalid or missing API key", headers={"WWW-Authenticate": "Bearer"})
