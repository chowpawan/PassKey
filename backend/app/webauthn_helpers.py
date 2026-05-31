"""Thin wrappers around py_webauthn for the registration / authentication ceremonies."""

import json
from typing import Any

from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from app.config import get_settings


def build_registration_options(
    user_id: bytes,
    username: str,
    existing_credential_ids: list[bytes],
) -> tuple[dict[str, Any], bytes]:
    """Returns (options-dict-for-browser, raw-challenge-bytes-to-persist)."""
    settings = get_settings()
    opts = generate_registration_options(
        rp_id=settings.rp_id,
        rp_name=settings.rp_name,
        user_id=user_id,
        user_name=username,
        user_display_name=username,
        exclude_credentials=[
            PublicKeyCredentialDescriptor(id=cid) for cid in existing_credential_ids
        ],
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
    )
    return json.loads(options_to_json(opts)), opts.challenge


def verify_registration(
    attestation: dict[str, Any],
    expected_challenge: bytes,
) -> tuple[bytes, bytes, int]:
    """Returns (credential_id, public_key_bytes, sign_count)."""
    settings = get_settings()
    verified = verify_registration_response(
        credential=attestation,
        expected_challenge=expected_challenge,
        expected_origin=settings.expected_origin,
        expected_rp_id=settings.rp_id,
        require_user_verification=False,
    )
    return verified.credential_id, verified.credential_public_key, verified.sign_count


def build_authentication_options(
    allow_credential_ids: list[bytes],
) -> tuple[dict[str, Any], bytes]:
    settings = get_settings()
    opts = generate_authentication_options(
        rp_id=settings.rp_id,
        allow_credentials=[
            PublicKeyCredentialDescriptor(id=cid) for cid in allow_credential_ids
        ],
        user_verification=UserVerificationRequirement.PREFERRED,
    )
    return json.loads(options_to_json(opts)), opts.challenge


def verify_authentication(
    assertion: dict[str, Any],
    expected_challenge: bytes,
    stored_public_key: bytes,
    stored_sign_count: int,
) -> int:
    """Returns the new sign_count."""
    settings = get_settings()
    verified = verify_authentication_response(
        credential=assertion,
        expected_challenge=expected_challenge,
        expected_origin=settings.expected_origin,
        expected_rp_id=settings.rp_id,
        credential_public_key=stored_public_key,
        credential_current_sign_count=stored_sign_count,
        require_user_verification=False,
    )
    return verified.new_sign_count
