from odoo.tests import TransactionCase, tagged
from odoo.tools.safe_eval import safe_eval


@tagged('post_install', '-at_install')
class TestSpaProductSales(TransactionCase):

    def test_spa_product_catalog_creates_storable_saleable_goods(self):
        action = self.env.ref('spa.action_spa_products')
        defaults = safe_eval(action.context)
        product = self.env['product.template'].with_context(**defaults).create({
            'name': 'SPA Retail Product',
            'list_price': 250000,
        })

        self.assertEqual(product.type, 'consu')
        self.assertTrue(product.is_storable)
        self.assertTrue(product.sale_ok)
        self.assertIn(
            product,
            self.env['product.template'].search(safe_eval(action.domain)),
        )

    def test_spa_services_are_not_listed_as_retail_products(self):
        action = self.env.ref('spa.action_spa_products')
        service = self.env.ref('spa.product_service_massage_body_relax')

        self.assertNotIn(
            service,
            self.env['product.template'].search(safe_eval(action.domain)),
        )

    def test_spa_starter_retail_catalog_is_storable_and_starts_without_stock(self):
        products = self.env['product.template'].search([
            ('id', 'in', [
                self.env.ref(f'spa.{xml_id}').id
                for xml_id in (
                    'product_spa_gentle_cleanser',
                    'product_spa_hydrating_toner',
                    'product_spa_hyaluronic_serum',
                    'product_spa_vitamin_c_serum',
                    'product_spa_moisturizer',
                    'product_spa_sunscreen',
                    'product_spa_hydrating_mask',
                    'product_spa_herbal_shampoo',
                    'product_spa_hair_conditioner',
                    'product_spa_body_scrub',
                    'product_spa_body_lotion',
                    'product_spa_massage_oil',
                )
            ]),
        ])

        self.assertEqual(len(products), 12)
        self.assertTrue(all(products.mapped('is_storable')))
        self.assertTrue(all(products.mapped('sale_ok')))
        self.assertTrue(all(price > 0 for price in products.mapped('list_price')))
        self.assertTrue(all(
            product.qty_available == 0
            for product in products.product_variant_id
        ))
