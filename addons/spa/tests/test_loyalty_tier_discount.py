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
        self.assertEqual(get_customer_type(499), 'new')
        self.assertEqual(get_customer_type(500), 'silver')
        self.assertEqual(get_customer_type(1499), 'silver')
        self.assertEqual(get_customer_type(1500), 'gold')
        self.assertEqual(get_customer_type(1999), 'gold')
        self.assertEqual(get_customer_type(2000), 'diamond')

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
            (500, 'silver', 5.0),
            (1500, 'gold', 10.0),
            (2000, 'diamond', 20.0),
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
            'loyalty_point': 1499,
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
            'loyalty_point': 2000,
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
