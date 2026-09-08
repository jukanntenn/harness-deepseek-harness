"""GitHub issue and pull-request policy engine.

The submodules separate concerns by concept: ``config`` holds the repository
and Project configuration format, ``rules`` the pure validation and lifecycle
logic, ``client`` the REST/GraphQL access, and ``commands`` the ``hdsh
policy`` subcommand entries.
"""
