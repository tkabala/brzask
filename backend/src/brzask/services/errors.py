"""Errors a person can act on; interfaces show the message as it is."""


class ServiceError(Exception):
    pass


class NotFoundError(ServiceError):
    pass


class ConflictError(ServiceError):
    pass
