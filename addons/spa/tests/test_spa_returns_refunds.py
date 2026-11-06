from odoo.tests import Form, TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestSpaReturnsRefunds(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env['res.partner'].create({
            'name': 'Spa Return and Refund Customer',
        })

    def _create_sale_order(self, product):
        order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'order_line': [(0, 0, {
                'product_id': product.id,
                'product_uom_qty': 1,
            })],
        })
        order.action_confirm()
        return order

    def test_return_button_opens_only_delivered_storable_products(self):
        warehouse = self.env['stock.warehouse'].search([
            ('company_id', '=', self.env.company.id),
        ], limit=1)
        product = self.env['product.product'].create({
            'name': 'Spa returnable retail product',
            'is_storable': True,
            'sale_ok': True,
            'list_price': 100000,
        })
        self.env['stock.quant']._update_available_quantity(
            product,
            warehouse.lot_stock_id,
            1,
        )
        order = self._create_sale_order(product)
        delivery = order.picking_ids.filtered(
            lambda picking: picking.picking_type_code == 'outgoing'
        )
        self.assertTrue(delivery)
        delivery.action_assign()
        delivery.move_ids.quantity = 1
        delivery.move_ids.picked = True
        delivery.button_validate()

        self.assertEqual(order.spa_returnable_picking_count, 1)
        action = order.action_spa_return_delivered_products()
        self.assertEqual(action['res_id'], delivery.id)

        return_wizard = self.env['stock.return.picking'].with_context(
            active_model='stock.picking',
            active_id=delivery.id,
            active_ids=delivery.ids,
        ).create({})
        return_wizard.product_return_moves.quantity = 1
        return_action = return_wizard.action_create_returns()
        return_picking = self.env['stock.picking'].browse(
            return_action['res_id']
        )
        return_picking.action_confirm()
        return_picking.action_assign()
        return_picking.move_ids.quantity = 1
        return_picking.move_ids.picked = True
        return_picking.button_validate()

        self.assertEqual(order.spa_returnable_picking_count, 0)
        self.assertFalse(order._get_spa_returnable_pickings())

    def test_refund_button_opens_standard_credit_note_wizard(self):
        product = self.env['product.product'].create({
            'name': 'Spa refundable service',
            'type': 'service',
            'sale_ok': True,
            'list_price': 100000,
        })
        order = self._create_sale_order(product)
        invoice = order._create_invoices()
        invoice.action_post()

        self.assertEqual(order.spa_refundable_invoice_count, 1)
        action = order.action_spa_create_refund()
        self.assertEqual(action['res_model'], 'account.move.reversal')
        self.assertEqual(action['target'], 'new')
        self.assertEqual(action['context']['active_ids'], invoice.ids)

        wizard_form = Form(
            self.env['account.move.reversal'].with_context(
                **action['context']
            )
        )
        wizard = wizard_form.save()
        wizard.refund_moves()
        credit_note = wizard.new_move_ids
        self.assertEqual(credit_note.move_type, 'out_refund')
        self.assertEqual(credit_note.state, 'draft')

        credit_note.action_post()
        self.assertEqual(order.spa_refundable_invoice_count, 0)

    def test_refund_button_rejects_orders_without_a_posted_invoice(self):
        product = self.env['product.product'].create({
            'name': 'Spa service without invoice',
            'type': 'service',
            'sale_ok': True,
            'list_price': 100000,
        })
        order = self._create_sale_order(product)

        self.assertFalse(order._get_spa_refundable_invoices())
