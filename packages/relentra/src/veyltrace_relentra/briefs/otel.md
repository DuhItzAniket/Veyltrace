The OpenTelemetry Demo is a web shop made of services written in many languages, calling each other over gRPC and HTTP, with a message queue for finished orders.

- frontend-proxy receives user requests and passes them to frontend.
- frontend serves the web pages and calls the other services.
- checkout runs an order: it calls cart, product-catalog, currency, shipping, payment and email, then publishes the order to kafka.
- cart stores carts in a key-value datastore.
- accounting and fraud-detection read orders from kafka.
- recommendation suggests products, ad returns ads, quote prices shipping, image-provider serves images.
- load-generator sends simulated user traffic.

A slow or failing service can show its effects first in the services that call it.
