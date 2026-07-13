# Meta Ads MCP OAuth notes

Endpoint verified from Meta help content:
- `https://mcp.facebook.com/ads`

Protected-resource discovery:
- Initial unauthenticated request returns `401 Unauthorized`
- `WWW-Authenticate` advertises:
  - `resource_metadata="https://mcp.facebook.com/.well-known/oauth-protected-resource/ads"`
  - scopes: `ads_management ads_read catalog_management business_management`

Observed protected-resource metadata:
```json
{
  "resource": "https://mcp.facebook.com/ads",
  "authorization_servers": ["https://mcp.facebook.com/ads"],
  "scopes_supported": [
    "ads_management",
    "ads_read",
    "catalog_management",
    "business_management"
  ],
  "bearer_methods_supported": ["header"]
}
```

Observed client behavior during login/auth attempts:
- Claude: server can be added as HTTP MCP, but status shows failed connect
- Codex: server can be added and listed, but `codex mcp login meta-ads` fails
- Hermes: config with `auth: oauth` is accepted, but `hermes mcp test meta-ads` fails

Common failure:
- `invalid_client_metadata`
- `Dynamic registration is not available for this client.`

Interpretation:
- Meta Ads MCP appears to reject generic dynamic client registration
- A pre-registered OAuth client is probably required
- Safe state wording: **configured/registered, awaiting provider-issued OAuth client credentials**

Hermes starter config:
```yaml
mcp_servers:
  meta-ads:
    url: https://mcp.facebook.com/ads
    auth: oauth
    oauth:
      scope: ads_management ads_read catalog_management business_management
    enabled: true
```

When credentials are available:
```yaml
mcp_servers:
  meta-ads:
    url: https://mcp.facebook.com/ads
    auth: oauth
    oauth:
      client_id: YOUR_PRE_REGISTERED_CLIENT_ID
      client_secret: YOUR_PRE_REGISTERED_CLIENT_SECRET   # only if required
      scope: ads_management ads_read catalog_management business_management
    enabled: true
```

Validation language to use with users:
- "installed/configured" is correct
- "connected/authenticated" is not correct until OAuth succeeds
