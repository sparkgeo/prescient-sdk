import prescient_sdk

client = prescient_sdk.PrescientClient(
    endpoint_url='https://api.example.com',
    client_id='test-client-id',
    auth_url='https://login.microsoftonline.com',
    tenant_id='test-tenant-id',
)

print('endpoint_url    :', client.settings.endpoint_url)
print('stac_catalog_url:', client.stac_catalog_url)
print('✓ Python smoke test passed')
