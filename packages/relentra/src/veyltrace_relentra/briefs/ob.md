Online Boutique is a web shop made of small services that call each other over gRPC.

- frontend serves the web pages and calls the other services.
- frontend-external is the externally exposed entry: user requests reach frontend through it.
- checkoutservice runs an order: it calls cartservice, productcatalogservice, currencyservice, shippingservice, paymentservice and emailservice.
- cartservice stores carts in its own Redis datastore, which is not a separate service here.
- productcatalogservice serves the product list.
- recommendationservice suggests products and reads the product list.
- adservice returns text ads.
- currencyservice converts prices, shippingservice quotes and ships, paymentservice charges cards, emailservice sends confirmations.
- loadgenerator sends simulated user traffic to frontend.

Each service usually runs as one replica. A slow or failing service can show its effects first in the services that call it.
