import logging

logging.basicConfig(level=logging.DEBUG)
rasterio_logger = logging.getLogger("rasterio")
rasterio_logger.setLevel(logging.DEBUG)
pystac_client_logger = logging.getLogger("pystac_client")
pystac_client_logger.setLevel(logging.DEBUG)
logger = logging.getLogger(__name__)

from prescient_sdk.client import PrescientClient


import rasterio
from rasterio.session import AWSSession
import pystac_client




def main():
    logger.debug("Starting the script")
    client = PrescientClient(env_file="config.env")
    catalog = pystac_client.Client.open(client.stac_catalog_url, headers=client.headers)
    item = catalog.search(limit=1).get_items()[0]
    asset = item.assets["INT"]
    logger.debug(f"Asset href: {asset.href}")
    logger.debug(client.session)
    logger.debug(client.bucket_credentials)
    logger.debug(client.settings)
    with rasterio.Env(session=AWSSession(client.session)):
        with rasterio.open(asset.href) as src:
            print(src.checksum(1))

if __name__ == "__main__":
    main()