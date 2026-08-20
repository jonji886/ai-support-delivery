"""Mock Customer Systems – synthetic enterprise backend.

This package simulates the customer's OMS, logistics carrier and ticket
systems as real HTTP services. It is a *synthetic* implementation used for
POC demos, integration tests and local evaluation. It does not contain or
represent any real customer data or production system.

Service map (one FastAPI app, separate routers per external system):

* ``/oms``         – Mock customer OMS (order + fulfillment facts)
* ``/logistics``   – Mock logistics carrier (tracking)
* ``/ticket``      – Mock customer service ticket system

Fault injection is available on every endpoint through the ``X-Fault-Inject``
header or ``?fault=`` query parameter. Supported values:

* ``normal``          – return the standard response
* ``429``             – too many requests
* ``500``             – internal server error
* ``timeout``         – hang until the caller gives up
* ``slow_response``   – sleep ``X-Mock-Slow-Ms`` (default 3000) then respond
* ``invalid_schema``  – return malformed JSON / wrong fields
"""
