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
