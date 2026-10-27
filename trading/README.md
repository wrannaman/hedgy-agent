# Trading

Start with the [repository setup guide](../README.md). Portfolio analysis supports
broker-independent CSV inputs without credentials; live options scanning uses the
optional Schwab integration.

- [Portfolio input format and example data](examples/README.md)
- [Local account configuration template](accounts.example.json)
- [Scheduler setup](deploy/launchd/README.md)
- [Shared safety rules](AGENTS.md)

Each folder under `strategies/` owns its strategy rules and state. `shared/`
contains account configuration, CSV loading, authentication, and market-data
plumbing. Credentials, filled configuration, holdings, journals, state and logs
stay local. Every order requires the account owner's live confirmation.
