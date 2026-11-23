class DomainError(Exception):
    status = 400
class NotFound(DomainError):
    status = 404
class OutOfStock(DomainError):
    status = 409
class PaymentDeclined(DomainError):
    status = 402
class Unavailable(DomainError):
    status = 503
