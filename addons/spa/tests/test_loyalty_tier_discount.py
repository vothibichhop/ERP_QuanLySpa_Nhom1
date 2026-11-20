from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestSpaLoyaltyTierDiscount(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env['res.partner'].create({
            'name': 'SPA Loyalty Discount Customer',
        })
        cls.product = cls.env['product.product'].create({
            'name': 'SPA Loyalty Discount Service',
            'type': 'service',
            'list_price': 100.0,
        })

    def test_customer_tier_thresholds(self):
        get_customer_type = self.partner._customer_type_for_loyalty_points
        self.assertEqual(get_customer_type(99), 'new')
        self.assertEqual(get_customer_type(100), 'silver')
        self.assertEqual(get_customer_type(499), 'silver')
        self.assertEqual(get_customer_type(500), 'gold')
        self.assertEqual(get_customer_type(1500), 'gold')
        self.assertEqual(get_customer_type(1501), 'diamond')

    def test_writing_loyalty_points_updates_tier_automatically(self):
        for points, customer_type in (
            (99, 'new'),
            (100, 'silver'),
            (499, 'silver'),
            (500, 'gold'),
            (1500, 'gold'),
            (1501, 'diamond'),
        ):
            self.partner.write({'loyalty_point': points})
            self.assertEqual(self.partner.customer_type, customer_type)

    def test_new_customer_uses_base_pricelist_instead_of_tier_pricelist(self):
        company = self.env.company
        base_pricelist = self.env['product.pricelist'].create({
            'name': 'SPA Test Base Pricelist',
            'currency_id': company.currency_id.id,
            'company_id': company.id,
            'sequence': 1,
        })
        tier_pricelist = self.env['product.pricelist'].create({
            'name': 'SPA Test Silver Pricelist',
            'currency_id': company.currency_id.id,
            'company_id': company.id,
        })
        self.env['product.pricelist.item'].create({
            'pricelist_id': tier_pricelist.id,
            'applied_on': '1_product',
            'product_tmpl_id': self.product.product_tmpl_id.id,
            'compute_price': 'fixed',
            'fixed_price': 50.0,
        })
        self.partner.write({
            'customer_type': 'new',
            'property_product_pricelist': tier_pricelist.id,
        })

        order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
        })
        line = self.env['sale.order.line'].create({
            'order_id': order.id,
            'product_id': self.product.id,
            'product_uom_qty': 1.0,
        })

        self.assertEqual(order.pricelist_id, base_pricelist)
        self.assertAlmostEqual(line.price_unit, self.product.list_price)

    def test_new_customer_creates_base_pricelist_when_missing(self):
        company = self.env.company
        pricelist_model = self.env['product.pricelist']
        base_domain = [
            ('active', '=', True),
            ('currency_id', '=', company.currency_id.id),
            ('item_ids', '=', False),
        ]
        existing_base_pricelists = pricelist_model.search(
            base_domain + [('company_id', '=', company.id)]
        ) | pricelist_model.search(
            base_domain + [('company_id', '=', False)]
        )
        existing_base_pricelists.write({'active': False})

        tier_pricelist = pricelist_model.create({
            'name': 'SPA Test Silver Pricelist Without Base',
            'currency_id': company.currency_id.id,
            'company_id': company.id,
        })
        self.env['product.pricelist.item'].create({
            'pricelist_id': tier_pricelist.id,
            'applied_on': '1_product',
            'product_tmpl_id': self.product.product_tmpl_id.id,
            'compute_price': 'fixed',
            'fixed_price': 50.0,
        })
        self.partner.write({
            'customer_type': 'new',
            'property_product_pricelist': tier_pricelist.id,
        })

        order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
        })
        line = self.env['sale.order.line'].create({
            'order_id': order.id,
            'product_id': self.product.id,
            'product_uom_qty': 1.0,
        })

        self.assertEqual(order.pricelist_id.name, 'Giá cơ sở')
        self.assertEqual(order.pricelist_id.currency_id, company.currency_id)
        self.assertAlmostEqual(line.price_unit, self.product.list_price)

    def test_order_line_uses_matching_customer_tier_discount(self):
        for points, customer_type, expected_discount in (
            (100, 'silver', 5.0),
            (500, 'gold', 10.0),
            (1501, 'diamond', 20.0),
        ):
            self.partner.write({
                'loyalty_point': points,
                'customer_type': customer_type,
            })
            order = self.env['sale.order'].create({
                'partner_id': self.partner.id,
            })
            line = self.env['sale.order.line'].create({
                'order_id': order.id,
                'product_id': self.product.id,
                'product_uom_qty': 1.0,
            })
            self.assertAlmostEqual(line.discount, expected_discount)
            self.assertAlmostEqual(
                line.price_subtotal,
                100.0 * (1 - expected_discount / 100),
            )

    def test_order_line_requires_rank_and_minimum_points(self):
        self.partner.write({
            'loyalty_point': 499,
            'customer_type': 'gold',
        })
        order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
        })
        line = self.env['sale.order.line'].create({
            'order_id': order.id,
            'product_id': self.product.id,
            'product_uom_qty': 1.0,
        })
        self.assertEqual(line.discount, 0.0)

    def test_order_displays_customer_tier_and_points(self):
        self.partner.write({
            'loyalty_point': 500,
            'customer_type': 'silver',
        })
        order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
        })

        self.assertEqual(order.spa_customer_type, 'silver')
        self.assertEqual(order.spa_customer_loyalty_point, 500)
        self.assertEqual(order.spa_tier_discount, 5.0)

    def test_confirming_service_order_awards_loyalty_points_once(self):
        service = self.env['product.product'].create({
            'name': 'SPA Loyalty Points Service',
            'type': 'service',
            'list_price': 250000,
        })
        order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'order_line': [(0, 0, {
                'product_id': service.id,
                'product_uom_qty': 1,
            })],
        })

        order.action_confirm()

        expected_amount_vnd = order.currency_id._convert(
            order.order_line.price_total,
            self.env.ref('base.VND'),
            order.company_id,
            fields.Date.context_today(order),
        )
        expected_points = int(expected_amount_vnd / 10_000)
        transaction = self.env['customer.loyalty.transaction'].search([
            ('sale_order_id', '=', order.id),
        ])
        self.assertEqual(self.partner.loyalty_point, expected_points)
        self.assertEqual(len(transaction), 1)
        self.assertEqual(transaction.state, 'applied')

        order._award_spa_loyalty_points()

        self.assertEqual(self.partner.loyalty_point, expected_points)
        self.assertEqual(
            self.env['customer.loyalty.transaction'].search_count([
                ('sale_order_id', '=', order.id),
            ]),
            1,
        )

    def test_rank_changes_do_not_reprice_existing_orders(self):
        self.partner.write({
            'loyalty_point': 500,
            'customer_type': 'silver',
        })
        order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
        })
        line = self.env['sale.order.line'].create({
            'order_id': order.id,
            'product_id': self.product.id,
            'product_uom_qty': 1.0,
        })

        self.partner.write({
            'loyalty_point': 1501,
            'customer_type': 'diamond',
        })

        self.assertEqual(order.spa_tier_discount, 5.0)
        self.assertEqual(line.discount, 5.0)

    def test_applying_loyalty_points_updates_open_quotations(self):
        order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
        })
        line = self.env['sale.order.line'].create({
            'order_id': order.id,
            'product_id': self.product.id,
            'product_uom_qty': 1.0,
        })
        transaction = self.env['customer.loyalty.transaction'].create({
            'name': 'Test tier upgrade',
            'partner_id': self.partner.id,
            'transaction_type': 'adjust_add',
            'points': 500,
        })

        transaction.action_apply_points()

        self.assertEqual(self.partner.customer_type, 'silver')
        self.assertEqual(order.spa_tier_discount, 5.0)
        self.assertEqual(line.discount, 5.0)
