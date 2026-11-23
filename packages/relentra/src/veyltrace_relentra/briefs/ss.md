Sock Shop is a web shop made of services that call each other over HTTP, with a message queue for shipping.

- front-end serves the web pages and calls the other services. It is where user requests enter.
- session holds front-end's user sessions.
- catalogue serves the products from its own database.
- carts stores carts in its own database.
- orders stores orders in its own database and calls carts, payment, user and shipping.
- payment authorises payments.
- user holds accounts in its own database.
- shipping puts shipments on rabbitmq.
- rabbitmq is the message queue for shipments.
- queue-master reads the shipments from rabbitmq.
- rabbitmq-exporter reports rabbitmq's metrics.

The databases are not separate services here. A slow or failing service can show its effects first in the services that call it.
