"""Mocked authentication responses for testing."""

AUTH_TOKEN_SUCCESS = {
    "token": "mock-opstoken-xyz-1234567890",
    "validity": 1729000000000,
}

AUTH_UNAUTHORIZED = {
    "message": "Invalid username or password.",
    "httpStatusCode": 401,
}
