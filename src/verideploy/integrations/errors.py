class IntegrationError(RuntimeError):
    code = "integration_error"

class IntegrationUnconfigured(IntegrationError):
    code = "integration_unconfigured"

class IntegrationHostDenied(IntegrationError):
    code = "integration_host_denied"

class IntegrationQuotaExceeded(IntegrationError):
    code = "integration_quota_exceeded"

class IntegrationRequestFailed(IntegrationError):
    code = "integration_request_failed"
