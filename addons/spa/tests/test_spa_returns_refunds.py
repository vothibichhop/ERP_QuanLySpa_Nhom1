from odoo.exceptions import AccessError, UserError
from odoo.tests import Form, TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestSpaReturnsRefunds(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env['res.partner'].create({
            'name': 'Spa Return and Refund Customer',
        })
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Spa Return Test Employee',
        })

    def _create_user(self, login, group_xmlid):
        return self.env['res.users'].create({
            'name': login,
            'login': login,
            'groups_id': [(6, 0, [self.env.ref(group_xmlid).id])],
        })

    def _create_delivered_order(self, quantity=2):
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
            quantity,
        )
        order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'order_line': [(0, 0, {
                'product_id': product.id,
                'product_uom_qty': quantity,
                'spa_employee_id': self.employee.id,
            })],
        })
        order.action_confirm()
        delivery = order.picking_ids.filtered(
            lambda picking: picking.picking_type_code == 'outgoing'
        )
        self.assertTrue(delivery)
        delivery.action_assign()
        delivery.move_ids.quantity = quantity
        delivery.move_ids.picked = True
        delivery.button_validate()
        return order, product, delivery

    def _create_return_request(self, order, delivery, quantity):
        request = self.env['spa.return.request'].create({
            'order_id': order.id,
            'delivery_picking_id': delivery.id,
            'reason': 'Sản phẩm bị lỗi, khách đã cung cấp hình ảnh.',
            'line_ids': [(0, 0, {
                'move_id': delivery.move_ids[0].id,
                'quantity': quantity,
            })],
        })
        return request

    def _receive_return(self, picking):
        picking.action_confirm()
        picking.action_assign()
        picking.move_ids.quantity = sum(picking.move_ids.mapped('product_uom_qty'))
        picking.move_ids.picked = True
        picking.button_validate()

    def test_return_requires_approval_and_respects_partial_quantity(self):
        order, _product, delivery = self._create_delivered_order()
        request = self._create_return_request(order, delivery, 1)

        with self.assertRaises(UserError):
            self.env['stock.return.picking'].with_context(
                active_model='stock.picking',
                active_id=delivery.id,
                active_ids=delivery.ids,
            ).create({}).action_create_returns()

        request.action_submit()
        self.assertEqual(request.state, 'submitted')
        with self.assertRaises(UserError):
            request.line_ids.write({'quantity': 2})

        regular_user = self._create_user(
            'spa_return_regular_user',
            'spa.group_customer_management_user',
        )
        with self.assertRaises(AccessError):
            request.with_user(regular_user).action_approve()

        manager = self._create_user(
            'spa_return_manager',
            'spa.group_customer_management_manager',
        )
        request.with_user(manager).action_approve()

        self.assertEqual(request.state, 'approved')
        self.assertEqual(request.approver_id, manager)
        self.assertEqual(request.return_picking_id.return_id, delivery)
        self.assertAlmostEqual(
            request.return_picking_id.move_ids.product_uom_qty,
            1.0,
        )
        self._receive_return(request.return_picking_id)
        self.assertEqual(request.return_state, 'done')

    def test_credit_note_uses_standard_odoo_wizard_after_goods_received(self):
        order, _product, delivery = self._create_delivered_order()
        invoice = order._create_invoices()
        invoice.action_post()
        request = self._create_return_request(order, delivery, 1)
        request.action_submit()
        manager = self._create_user(
            'spa_return_refund_manager',
            'spa.group_customer_management_manager',
        )
        request.with_user(manager).action_approve()

        with self.assertRaises(UserError):
            request.action_create_refund()

        self._receive_return(request.return_picking_id)
        request.invoice_id = invoice
        action = request.action_create_refund()

        self.assertEqual(action['res_model'], 'account.move.reversal')
        self.assertEqual(action['target'], 'new')
        self.assertEqual(action['context']['active_ids'], invoice.ids)
        self.assertEqual(
            action['context']['default_spa_return_request_id'],
            request.id,
        )

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
        self.assertEqual(request.credit_note_id, credit_note)
        refunded_product_lines = credit_note.invoice_line_ids.filtered(
            lambda line: line.product_id == order.order_line.product_id
        )
        self.assertAlmostEqual(refunded_product_lines.quantity, 1.0)

        credit_note.action_post()
        self.assertEqual(order.spa_refundable_invoice_count, 0)

    def test_refund_is_unavailable_without_a_completed_approved_return(self):
        order, _product, delivery = self._create_delivered_order()
        invoice = order._create_invoices()
        invoice.action_post()
        request = self._create_return_request(order, delivery, 1)
        request.action_submit()
        manager = self._create_user(
            'spa_return_unreceived_manager',
            'spa.group_customer_management_manager',
        )
        request.with_user(manager).action_approve()

        with self.assertRaises(UserError):
            request.action_create_refund()

        with self.assertRaises(UserError):
            order.action_spa_create_refund()
