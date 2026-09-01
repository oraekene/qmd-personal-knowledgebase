# 0004-python-sourceplugin-connectors.md

# Connectors stay Python SourcePlugin; gateways deferred

v1 connectors are Python scripts extending the existing SourcePlugin
architecture. Connector gateway platforms (Composio, Nango, Pipedream)
were evaluated and deferred: their catalogs cover SaaS business apps, not
personal sources (chat exports, X bookmarks, Simplenote, Keep), so they
would add a TypeScript runtime and managed-OAuth overhead without
replacing a single v1 connector. Revisit when a source genuinely needs
managed OAuth (e.g. Gmail).