Train Ticket is a railway booking system made of many small services, mostly named ts-<purpose>-service, that call each other over HTTP.

- ts-ui-dashboard is the gateway where user requests enter.
- Booking flows pass through services such as ts-preserve-service, ts-travel-service, ts-seat-service, ts-order-service and ts-inside-payment-service.
- Query flows pass through services such as ts-travel-plan-service, ts-route-service, ts-station-service, ts-train-service, ts-basic-service, ts-ticketinfo-service and ts-price-service.
- Account flows use ts-auth-service, ts-user-service, ts-verification-code-service and ts-contacts-service.
- Many services keep their own datastore, named after the service.

Requests cross long call chains, so a slow or failing service can show its effects first in services several calls away.
