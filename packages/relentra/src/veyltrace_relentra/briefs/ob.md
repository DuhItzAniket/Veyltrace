Online Boutique is a web shop made of small services that call each other over gRPC.

- frontend serves the web pages and calls the other services. It is where user requests enter.
- frontend-external is the external load balancer in front of frontend; it only reports request rate.
- checkoutservice runs an order: it calls cartservice, productcatalogservice, currencyservice, shippingservice, paymentservice and emailservice.
- cartservice stores carts in redis.
- redis is a cache with its own metrics.
- productcatalogservice serves the product list.
- recommendationservice suggests products and reads the product list.
- adservice returns text ads.
- currencyservice converts prices.
- shippingservice quotes and ships orders.
- paymentservice charges cards.
- emailservice sends order confirmations.

Each service usually runs as one replica. A slow or failing service can show its effects first in the services that call it.
