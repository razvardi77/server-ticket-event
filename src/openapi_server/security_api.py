# coding: utf-8

from typing import List

from fastapi import Depends, Security  # noqa: F401
from fastapi.openapi.models import OAuthFlowImplicit, OAuthFlows  # noqa: F401
from fastapi.security import (  # noqa: F401
    HTTPAuthorizationCredentials,
    HTTPBasic,
    HTTPBasicCredentials,
    HTTPBearer,
    OAuth2,
    OAuth2AuthorizationCodeBearer,
    OAuth2PasswordBearer,
    SecurityScopes,
)
from fastapi.security.api_key import APIKeyCookie, APIKeyHeader, APIKeyQuery  # noqa: F401

import jwt

from openapi_server.auth import USERS, decode_access_token
from openapi_server.errors import ApiError
from openapi_server.models.extra_models import TokenModel


bearer_auth = HTTPBearer(auto_error=False)


def get_token_bearerAuth(credentials: HTTPAuthorizationCredentials = Depends(bearer_auth)) -> TokenModel:
    """
    Check and retrieve authentication information from custom bearer token.

    :param credentials Credentials provided by Authorization header
    :type credentials: HTTPAuthorizationCredentials
    :return: Decoded token information
    :rtype: TokenModel
    :raises ApiError: 401 if the token is missing, invalid, expired, or its user no longer exists
    """
    if credentials is None:
        raise ApiError(401, "UNAUTHORIZED", "Missing Authorization: Bearer <token> header.")
    try:
        payload = decode_access_token(credentials.credentials)
    except jwt.ExpiredSignatureError:
        raise ApiError(401, "TOKEN_EXPIRED", "The token has expired. Log in again.")
    except jwt.PyJWTError:
        raise ApiError(401, "INVALID_TOKEN", "The token is invalid.")
    if payload["sub"] not in USERS:
        raise ApiError(401, "INVALID_TOKEN", "The user for this token no longer exists.")
    return TokenModel(sub=payload["sub"])

