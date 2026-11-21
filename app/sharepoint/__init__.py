"""SharePoint as the portal's system of record, through Microsoft Graph.

- config:  where the tenant, site and app registration are read from
- graph:   the HTTP client — token, retries, paging, JSON batching
- schema:  one SharePoint list per portal table, and the value conversions
- store:   provisioning, migration, the local read cache, write-through
           push and delta pull
- files:   the Documents and Reports libraries
"""
