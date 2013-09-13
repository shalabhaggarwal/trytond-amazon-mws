# -*- coding: utf-8 -*-
"""
    __init__

    Initialize module

    :copyright: (c) 2013 by Openlabs Technologies & Consulting (P) Limited
    :license: BSD, see LICENSE for more details.
"""
from trytond.pool import Pool
from .amazon import AmazonMWSAccount
from .product import (
    Product, ExportCatalogStart, ExportCatalog, ProductMwsAccount,
    ExportCatalogDone, ExportCatalogPricingStart, ExportCatalogPricing,
    ExportCatalogPricingDone, ExportCatalogInventoryStart,
    ExportCatalogInventory, ExportCatalogInventoryDone, ProductIdentifier,
)


def register():
    """
    Register classes with pool
    """
    Pool.register(
        AmazonMWSAccount,
        Product,
        ProductIdentifier,
        ProductMwsAccount,
        ExportCatalogStart,
        ExportCatalogDone,
        ExportCatalogPricingStart,
        ExportCatalogPricingDone,
        ExportCatalogInventoryStart,
        ExportCatalogInventoryDone,
        module='amazon_mws', type_='model'
    )
    Pool.register(
        ExportCatalog,
        ExportCatalogPricing,
        ExportCatalogInventory,
        module='amazon_mws', type_='wizard'
    )
