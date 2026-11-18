Sock Shop is a web shop made of services that call each other over HTTP, with a message queue for shipping.

- front-end serves the web pages and calls the other services. It is where user requests enter.
- catalogue serves the products from catalogue-db.
- carts stores carts in carts-db.
- orders places orders in orders-db and calls carts, payment, user and shipping.
- payment authorises payments.
- user holds accounts in user-db.
- shipping puts shipments on rabbitmq, and queue-master reads them.

A slow or failing service can show its effects first in the services that call it.
