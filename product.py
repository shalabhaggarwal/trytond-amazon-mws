# -*- coding: UTF-8 -*-
'''
    product

    :copyright: (c) 2013 by Openlabs Technologies & Consulting (P) Limited
    :license: BSD, see LICENSE for more details.
'''
from decimal import Decimal
from lxml import etree
from lxml.builder import E

from trytond.model import ModelSQL, ModelView, fields
from trytond.transaction import Transaction
from trytond.wizard import Wizard, StateView, StateTransition, Button
from trytond.pool import PoolMeta, Pool
from trytond.pyson import Bool, Eval

from mws import mws


__all__ = [
    'Product', 'ExportCatalogStart', 'ExportCatalog', 'ProductMwsAccount',
    'ExportCatalogDone', 'ExportCatalogPricingStart', 'ExportCatalogPricing',
    'ExportCatalogPricingDone', 'ExportCatalogInventoryStart',
    'ExportCatalogInventory', 'ExportCatalogInventoryDone',
    'ProductIdentifier',
]
__metaclass__ = PoolMeta


class Product:
    "Product"

    __name__ = "product.product"

    amazon_identifiers = fields.One2Many(
        'amazon.product.identifier', 'product', 'Amazon Identifiers',
    )
    mws_accounts = fields.One2Many(
        'product.mws.account', 'product', 'MWS Accounts',
    )

    @classmethod
    def __setup__(cls):
        """
        Setup the class before adding to pool
        """
        super(Product, cls).__setup__()
        cls._error_messages.update({
            "invalid_amazon_product":
                'Product with Amazon Code/SKU "%s" already exists',
            "missing_amazon_product_identifiers": (
                'Product "%(product)s" misses Amazon Product Identifiers'
            ),
            "missing_product_code": (
                'Product "%(product)s" misses Product Code'
            )
        })

    @classmethod
    def validate(cls, products):
        super(Product, cls).validate(products)
        for product in products:
            product.check_amazon_code()

    def check_amazon_code(self):
        "Check the product code for duplicates"
        if self.amazon_identifiers and self.search([
            ('code', '=', self.code),
            ('id', '!=', self.id),
        ]):
            self.raise_user_error(
                'invalid_amazon_product', (self.code,)
            )

    @classmethod
    def export_to_amazon(cls, products):
        """Export the products to the Amazon account in context
        """
        MwsAccount = Pool().get('amazon.mws.account')

        mws_account = MwsAccount(
            Transaction().context['amazon_mws_account']
        )

        NS = "http://www.w3.org/2001/XMLSchema-instance"
        location_attribute = '{%s}noNamespaceSchemaLocation' % NS

        products_xml = []
        for product in products:
            if not product.code:
                cls.raise_user_error(
                    'missing_product_code', {
                        'product': product.template.name
                    }
                )
            if not product.amazon_identifiers:
                cls.raise_user_error(
                    'missing_amazon_product_identifiers', {
                        'product': product.template.name
                    }
                )
            products_xml.append(E.Message(
                E.MessageID(str(product.id)),
                E.OperationType('Update'),
                E.Product(
                    E.SKU(product.code),
                    E.StandardProductID(
                        E.Type(product.amazon_identifiers[0].product_id_type),
                        E.Value(product.amazon_identifiers[0].product_id),
                    ),
                    E.DescriptionData(
                        E.Title(product.template.name),
                        E.Description(product.description),
                    ),
                    # Amazon needs this information so as to place the product
                    # under a category.
                    # FIXME: Either we need to create all that inside our
                    # system or figure out a way to get all that via API
                    E.ProductData(
                        E.Miscellaneous(
                            E.ProductType('Misc_Other'),
                        ),
                    ),
                )
            ))

        envelope_xml = E.AmazonEnvelope(
            E.Header(
                E.DocumentVersion('1.01'),
                E.MerchantIdentifier(mws_account.merchant_id)
            ),
            E.MessageType('Product'),
            E.PurgeAndReplace('false'),
            *(product_xml for product_xml in products_xml)
        )

        envelope_xml.set(location_attribute, 'amznenvelope.xsd')

        feeds_api = mws.Feeds(
            mws_account.access_key,
            mws_account.secret_key,
            mws_account.merchant_id
        )

        response = feeds_api.submit_feed(
            etree.tostring(envelope_xml),
            feed_type='_POST_PRODUCT_DATA_',
            marketplaceids=[mws_account.marketplace_id]
        )

        cls.write(products, {
            'mws_accounts': [('create', [{
                'product': product.id,
                'account': mws_account.id,
            } for product in products])]
        })

        return response.parsed

    @classmethod
    def export_pricing_to_amazon(cls, products):
        """Export prices of the products to the Amazon account in context
        """
        MwsAccount = Pool().get('amazon.mws.account')

        mws_account = MwsAccount(
            Transaction().context['amazon_mws_account']
        )

        NS = "http://www.w3.org/2001/XMLSchema-instance"
        location_attribute = '{%s}noNamespaceSchemaLocation' % NS

        pricing_xml = []
        for product in products:

            if mws_account in [acc.account for acc in product.mws_accounts]:
                pricing_xml.append(E.Message(
                    E.MessageID(str(product.id)),
                    E.OperationType('Update'),
                    E.Price(
                        E.SKU(product.code),
                        E.StandardPrice(
                            str(product.template.list_price),
                            currency=mws_account.company.currency.code
                        ),
                    )
                ))

        envelope_xml = E.AmazonEnvelope(
            E.Header(
                E.DocumentVersion('1.01'),
                E.MerchantIdentifier(mws_account.merchant_id)
            ),
            E.MessageType('Price'),
            E.PurgeAndReplace('false'),
            *(price_xml for price_xml in pricing_xml)
        )

        envelope_xml.set(location_attribute, 'amznenvelope.xsd')

        feeds_api = mws.Feeds(
            mws_account.access_key,
            mws_account.secret_key,
            mws_account.merchant_id
        )

        response = feeds_api.submit_feed(
            etree.tostring(envelope_xml),
            feed_type='_POST_PRODUCT_PRICING_DATA_',
            marketplaceids=[mws_account.marketplace_id]
        )

        return response.parsed

    @classmethod
    def export_inventory_to_amazon(cls, products):
        """Export inventory of the products to the Amazon account in context
        """
        MwsAccount = Pool().get('amazon.mws.account')
        Location = Pool().get('stock.location')

        mws_account = MwsAccount(
            Transaction().context['amazon_mws_account']
        )
        locations = Location.search([('type', '=', 'storage')])

        NS = "http://www.w3.org/2001/XMLSchema-instance"
        location_attribute = '{%s}noNamespaceSchemaLocation' % NS

        inventory_xml = []
        for product in products:

            with Transaction().set_context({'locations': map(int, locations)}):
                quantity = product.template.quantity

            if not quantity:
                continue

            if mws_account in [acc.account for acc in product.mws_accounts]:
                inventory_xml.append(E.Message(
                    E.MessageID(str(product.id)),
                    E.OperationType('Update'),
                    E.Inventory(
                        E.SKU(product.code),
                        E.Quantity(str(int(quantity))),
                        E.FulfillmentLatency('7'),    # FIXME
                    )
                ))

        envelope_xml = E.AmazonEnvelope(
            E.Header(
                E.DocumentVersion('1.01'),
                E.MerchantIdentifier(mws_account.merchant_id)
            ),
            E.MessageType('Inventory'),
            E.PurgeAndReplace('false'),
            *(inv_xml for inv_xml in inventory_xml)
        )

        envelope_xml.set(location_attribute, 'amznenvelope.xsd')

        feeds_api = mws.Feeds(
            mws_account.access_key,
            mws_account.secret_key,
            mws_account.merchant_id
        )

        response = feeds_api.submit_feed(
            etree.tostring(envelope_xml),
            feed_type='_POST_INVENTORY_AVAILABILITY_DATA_',
            marketplaceids=[mws_account.marketplace_id]
        )

        return response.parsed


class ProductIdentifier(ModelSQL, ModelView):
    "Amazon Product Identifier"
    __name__ = 'amazon.product.identifier'
    _rec_name = 'product_id'

    product_id = fields.Char(
        'Amazon Product ID', required=True,
        help="An UPC / EAN / ISBN code to be used in Amazon product listing."
    )
    product_id_type = fields.Selection([
        ('EAN', 'EAN'),
        ('UPC', 'UPC'),
        ('ISBN', 'ISBN'),
        ('ASIN', 'ASIN'),
        ('GTIN', 'GTIN'),
    ], 'Amazon Product ID Type', states={
        'required': Bool(Eval('product_id')),
    })
    product = fields.Many2One('product.product', 'Product', required=True)

    @classmethod
    def __setup__(cls):
        """
        Setup the class before adding to pool
        """
        super(ProductIdentifier, cls).__setup__()
        cls._sql_constraints += [
            (
                'unique_product_id_type',
                'UNIQUE(product_id, product_id_type)',
                'A product identifier must be unique by type.'
            )
        ]


class ProductMwsAccount(ModelSQL, ModelView):
    '''Product - MWS Account

    This model keeps a record of a product's association with MWS accounts.
    A product can be listen on multiple marketplaces
    '''
    __name__ = 'product.mws.account'

    account = fields.Many2One(
        'amazon.mws.account', 'MWS Account', required=True
    )
    product = fields.Many2One(
        'product.product', 'Product', required=True
    )

    @classmethod
    def __setup__(cls):
        '''
        Setup the class and define constraints
        '''
        super(ProductMwsAccount, cls).__setup__()
        cls._sql_constraints += [
            (
                'account_product_unique',
                'UNIQUE(account, product)',
                'Each product in can be linked to only one MWS account!'
            )
        ]

    @classmethod
    def create(cls, vlist):
        """If a record already exists for the same product and account combo,
        then just remove that one from the list instead of creating a new.
        This is because the Feed being send to amazon might be for the
        updation of a product which was already exported earlier
        """
        for vals in vlist:
            if cls.search([
                ('product', '=', vals['product']),
                ('account', '=', vals['account'])
            ]):
                vlist.remove(vals)
        return super(ProductMwsAccount, cls).create(vlist)


class ExportCatalogStart(ModelView):
    'Export Catalog to Amazon View'
    __name__ = 'amazon.export_catalog.start'

    products = fields.Many2Many(
        'product.product', None, None, 'Products', required=True,
        domain=[
            ('amazon_identifiers', 'not in', []),
            ('code', '!=', None),
        ],
    )


class ExportCatalogDone(ModelView):
    'Export Catalog to Amazon Done View'
    __name__ = 'amazon.export_catalog.done'

    status = fields.Char('Status', readonly=True)
    submission_id = fields.Char('Submission ID', readonly=True)


class ExportCatalog(Wizard):
    '''Export catalog to Amazon

    Export the products selected to this amazon account
    '''
    __name__ = 'amazon.export_catalog'

    start = StateView(
        'amazon.export_catalog.start',
        'amazon_mws.export_catalog_start', [
            Button('Cancel', 'end', 'tryton-cancel'),
            Button('Continue', 'export_', 'tryton-ok', default=True),
        ]
    )
    export_ = StateTransition()
    done = StateView(
        'amazon.export_catalog.done',
        'amazon_mws.export_catalog_done', [
            Button('OK', 'end', 'tryton-cancel'),
        ]
    )

    def transition_export_(self):
        """
        Export the products selected to this amazon account
        """
        MwsAccount = Pool().get('amazon.mws.account')
        Product = Pool().get('product.product')

        mws_account = MwsAccount(Transaction().context['active_id'])

        if not self.start.products:
            return 'end'

        with Transaction().set_context({
            'amazon_mws_account': mws_account.id,
        }):
            response = Product.export_to_amazon(self.start.products)

        Transaction().set_context({'response': response})

        return 'done'

    def default_done(self, fields):
        "Display response"
        response = Transaction().context['response']
        return {
            'status': response['FeedSubmissionInfo'][
                'FeedProcessingStatus'
            ]['value'],
            'submission_id': response['FeedSubmissionInfo'][
                'FeedSubmissionId'
            ]['value']
        }


class ExportCatalogPricingStart(ModelView):
    'Export Catalog Pricing to Amazon View'
    __name__ = 'amazon.export_catalog_pricing.start'

    products = fields.Many2Many(
        'product.product', None, None, 'Products', required=True,
        domain=[
            ('amazon_identifiers', 'not in', []),
            ('code', '!=', None),
            ('mws_accounts', 'not in', []),
        ],
    )


class ExportCatalogPricingDone(ModelView):
    'Export Catalog Pricing to Amazon Done View'
    __name__ = 'amazon.export_catalog_pricing.done'

    status = fields.Char('Status', readonly=True)
    submission_id = fields.Char('Submission ID', readonly=True)


class ExportCatalogPricing(Wizard):
    '''Export catalog pricing to Amazon

    Export the prices products selected to this amazon account
    '''
    __name__ = 'amazon.export_catalog_pricing'

    start = StateView(
        'amazon.export_catalog_pricing.start',
        'amazon_mws.export_catalog_pricing_start', [
            Button('Cancel', 'end', 'tryton-cancel'),
            Button('Continue', 'export_', 'tryton-ok', default=True),
        ]
    )
    export_ = StateTransition()
    done = StateView(
        'amazon.export_catalog_pricing.done',
        'amazon_mws.export_catalog_pricing_done', [
            Button('OK', 'end', 'tryton-cancel'),
        ]
    )

    def transition_export_(self):
        """
        Export the prices for products selected to this amazon account
        """
        MwsAccount = Pool().get('amazon.mws.account')
        Product = Pool().get('product.product')

        mws_account = MwsAccount(Transaction().context['active_id'])

        if not self.start.products:
            return 'end'

        with Transaction().set_context({
            'amazon_mws_account': mws_account.id,
        }):
            response = Product.export_pricing_to_amazon(self.start.products)

        Transaction().set_context({'response': response})

        return 'done'

    def default_done(self, fields):
        "Display response"
        response = Transaction().context['response']
        return {
            'status': response['FeedSubmissionInfo'][
                'FeedProcessingStatus'
            ]['value'],
            'submission_id': response['FeedSubmissionInfo'][
                'FeedSubmissionId'
            ]['value']
        }


class ExportCatalogInventoryStart(ModelView):
    'Export Catalog Inventory to Amazon View'
    __name__ = 'amazon.export_catalog_inventory.start'

    products = fields.Many2Many(
        'product.product', None, None, 'Products', required=True,
        domain=[
            ('amazon_identifiers', 'not in', []),
            ('code', '!=', None),
            ('mws_accounts', 'not in', []),
        ],
    )


class ExportCatalogInventoryDone(ModelView):
    'Export Catalog Inventory to Amazon Done View'
    __name__ = 'amazon.export_catalog_inventory.done'

    status = fields.Char('Status', readonly=True)
    submission_id = fields.Char('Submission ID', readonly=True)


class ExportCatalogInventory(Wizard):
    '''Export catalog inventory to Amazon

    Export the prices products selected to this amazon account
    '''
    __name__ = 'amazon.export_catalog_inventory'

    start = StateView(
        'amazon.export_catalog_inventory.start',
        'amazon_mws.export_catalog_inventory_start', [
            Button('Cancel', 'end', 'tryton-cancel'),
            Button('Continue', 'export_', 'tryton-ok', default=True),
        ]
    )
    export_ = StateTransition()
    done = StateView(
        'amazon.export_catalog_inventory.done',
        'amazon_mws.export_catalog_inventory_done', [
            Button('OK', 'end', 'tryton-cancel'),
        ]
    )

    def transition_export_(self):
        """
        Export the prices for products selected to this amazon account
        """
        MwsAccount = Pool().get('amazon.mws.account')
        Product = Pool().get('product.product')

        mws_account = MwsAccount(Transaction().context['active_id'])

        if not self.start.products:
            return 'end'

        with Transaction().set_context({
            'amazon_mws_account': mws_account.id,
        }):
            response = Product.export_inventory_to_amazon(self.start.products)

        Transaction().set_context({'response': response})

        return 'done'

    def default_done(self, fields):
        "Display response"
        response = Transaction().context['response']
        return {
            'status': response['FeedSubmissionInfo'][
                'FeedProcessingStatus'
            ]['value'],
            'submission_id': response['FeedSubmissionInfo'][
                'FeedSubmissionId'
            ]['value']
        }
