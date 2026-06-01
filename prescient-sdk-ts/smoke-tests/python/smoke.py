from prescient_sdk import PrescientClient

client = PrescientClient(env_file="/workspace/smoke-tests/config.env")

print("endpoint_url    :", client.settings.endpoint_url)
print("stac_catalog_url:", client.stac_catalog_url)
print("✓ Python smoke test passed")
