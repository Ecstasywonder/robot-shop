# Initial Robot Shop deployment

This directory holds the namespace policy and a low-rate, intentional baseline load generator for the first Robot Shop rollout. The application chart is patched by `robot-shop-initial.patch` before rendering.

The load generator uses two clients, does not inject payment errors, and runs continuously (`RUN_TIME=0`). It is a functional baseline only; performance testing and observability are configured separately.

The chart routes checkout's payment-gateway check to `http://web:8080/`, an in-cluster HTTP-200 stub. This avoids external PayPal traffic; checkout is deliberately simulated for this course deployment.

The upstream application has demo-oriented database settings and does not define database credentials in its Helm chart. No credentials are generated or committed here. It retains residual demo risks that make it unsuitable for production: MySQL permits an empty root password, RabbitMQ uses `guest`/`guest`, MongoDB has no authentication, and seeded users include plaintext demo passwords. Services remain ClusterIP-only and the namespace NetworkPolicy limits ingress to in-namespace pods, but those controls do not resolve the upstream application credential model.

The chart removes its Instana environment settings. The upstream web image can still contain optional Instana libraries, but without a build-time Instana key the entrypoint removes the active Nginx tracing directives; removal of baked libraries belongs to a later rebuilt-image change.
