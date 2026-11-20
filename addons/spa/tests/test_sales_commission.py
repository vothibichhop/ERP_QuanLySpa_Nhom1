from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestSpaSalesCommission(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env['res.partner'].create({
            'name': 'SPA Sales Commission Customer',
        })
        cls.product = cls.env['product.product'].create({
            'name': 'SPA Commission Retail Product',
            'type': 'consu',
            'list_price': 100.0,
        })
        cls.service = cls.env['product.product'].create({
            'name': 'SPA Commission Service',
            'type': 'service',
            'list_price': 300.0,
        })
        cls.employee = cls.env['hr.employee'].create({
            'name': 'SPA Commission Employee',
        })
        cls.second_employee = cls.env['hr.employee'].create({
            'name': 'SPA Commission Employee Two',
        })
        cls.order = cls.env['sale.order'].create({
            'partner_id': cls.partner.id,
            'order_line': [
                (0, 0, {
                    'product_id': cls.product.id,
                    'product_uom_qty': 2,
                    'price_unit': 100,
                }),
                (0, 0, {
                    'product_id': cls.service.id,
                    'product_uom_qty': 1,
                    'price_unit': 300,
                }),
            ],
        })

    def _create_salesperson_user(self, login):
        return self.env['res.users'].sudo().create({
            'name': login,
            'login': login,
            'groups_id': [(6, 0, [self.env.ref('base.group_user').id])],
        })

    def test_employee_selection_is_copied_to_invoice_line(self):
        sale_line = self.order.order_line.filtered(
            lambda line: line.product_id == self.product
        )
        sale_line.spa_employee_id = self.employee
        invoice_values = sale_line._prepare_invoice_line()

        self.assertEqual(invoice_values['spa_employee_id'], self.employee.id)
        invoice_line = self.env['account.move.line'].new(invoice_values)
        self.assertEqual(invoice_line.spa_employee_id, self.employee)

    def test_employee_can_be_selected_directly_on_locked_order_line(self):
        sale_line = self.order.order_line.filtered(
            lambda line: line.product_id == self.product
        )
        self.order.locked = True

        sale_line.write({'spa_employee_id': self.employee.id})

        self.assertEqual(sale_line.spa_employee_id, self.employee)

    def test_retail_products_require_seller_before_order_confirmation(self):
        seller_user = self._create_salesperson_user(
            'spa_unassigned_salesperson'
        )
        self.order.user_id = seller_user

        with self.assertRaisesRegex(UserError, 'Nhân viên bán sản phẩm'):
            self.order.action_confirm()

        retail_line = self.order.order_line.filtered(
            lambda line: line.product_id == self.product
        )
        retail_line.spa_employee_id = self.employee
        self.order.action_confirm()

        self.assertEqual(self.order.state, 'sale')

    def test_salesperson_employee_is_assigned_and_commission_recorded_at_confirmation(
        self,
    ):
        seller_user = self._create_salesperson_user('spa_commission_seller')
        employee = self.env['hr.employee'].create({
            'name': 'SPA Commission Seller Employee',
            'user_id': seller_user.id,
        })
        self.order.user_id = seller_user

        self.order.action_confirm()

        retail_line = self.order.order_line.filtered(
            lambda line: line.product_id == self.product
        )
        commission = self.env['spa.sales.commission'].search([
            ('sale_order_line_id', '=', retail_line.id),
        ])
        self.assertEqual(retail_line.spa_employee_id, employee)
        self.assertEqual(len(commission), 1)
        self.assertEqual(commission.employee_id, employee)
        self.assertEqual(commission.base_amount, 200)
        self.assertEqual(commission.rate, 3.0)
        self.assertEqual(commission.commission_amount, 6)
        self.assertEqual(retail_line.spa_commission_status, 'applied')
        self.assertEqual(employee.spa_sales_commission_order_count, 1)
        self.assertFalse(commission.invoice_id)

    def test_cancelling_order_cancels_pending_commission(self):
        retail_line = self.order.order_line.filtered(
            lambda line: line.product_id == self.product
        )
        retail_line.spa_employee_id = self.employee
        self.order.action_confirm()
        commission = self.env['spa.sales.commission'].search([
            ('sale_order_line_id', '=', retail_line.id),
        ])

        self.order.action_cancel()

        self.assertEqual(commission.state, 'cancelled')

    def test_employee_can_be_assigned_after_confirmation_and_syncs_invoice(self):
        self.order.user_id = self._create_salesperson_user(
            'spa_commission_unassigned_seller'
        )
        sale_line = self.order.order_line.filtered(
            lambda line: line.product_id == self.product
        )
        self.order.action_confirm()
        invoice = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.partner.id,
            'invoice_line_ids': [
                (0, 0, {
                    'product_id': self.product.id,
                    'quantity': 2,
                    'price_unit': 100,
                    'sale_line_ids': [(6, 0, sale_line.ids)],
                }),
            ],
        })
        invoice_line = invoice.invoice_line_ids.filtered(
            lambda line: line.product_id == self.product
        )

        sale_line.write({'spa_employee_id': self.employee.id})

        self.assertEqual(invoice_line.spa_employee_id, self.employee)

    def test_employee_cannot_be_changed_after_commission_is_recorded(self):
        sale_line = self.order.order_line.filtered(
            lambda line: line.product_id == self.product
        )
        invoice = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.partner.id,
            'invoice_line_ids': [
                (0, 0, {
                    'product_id': self.product.id,
                    'quantity': 2,
                    'price_unit': 100,
                    'sale_line_ids': [(6, 0, sale_line.ids)],
                    'spa_employee_id': self.employee.id,
                }),
            ],
        })
        invoice_line = invoice.invoice_line_ids.filtered(
            lambda line: line.product_id == self.product
        )
        self.env['spa.sales.commission'].create({
            'invoice_id': invoice.id,
            'invoice_line_id': invoice_line.id,
            'employee_id': self.employee.id,
        })

        with self.assertRaises(UserError):
            sale_line.write({
                'spa_employee_id': self.second_employee.id,
            })

    def test_employee_sales_order_action_lists_confirmed_product_lines(self):
        sale_line = self.order.order_line.filtered(
            lambda line: line.product_id == self.product
        )
        sale_line.spa_employee_id = self.employee
        self.order.action_confirm()

        action = self.employee.action_spa_view_sales_orders()

        self.assertEqual(action['res_model'], 'sale.order.line')
        self.assertIn(
            ('spa_employee_id', '=', self.employee.id),
            action['domain'],
        )
        self.assertIn(
            ('order_id.state', 'in', ('sale', 'done')),
            action['domain'],
        )

    def test_employee_commission_button_opens_commission_sales_list(self):
        action = self.employee.action_spa_view_sales_commissions()

        self.assertEqual(action['name'], 'Hoa hồng - %s' % self.employee.name)
        self.assertEqual(action['res_model'], 'sale.order.line')
        self.assertIn(
            ('spa_employee_id', '=', self.employee.id),
            action['domain'],
        )

    def test_employee_order_line_shows_three_percent_and_commission_status(self):
        sale_line = self.order.order_line.filtered(
            lambda line: line.product_id == self.product
        )
        sale_line.spa_employee_id = self.employee
        self.assertEqual(sale_line.spa_commission_rate, 3.0)
        self.assertEqual(sale_line.spa_commission_amount, 6.0)
        self.assertFalse(sale_line.spa_commission_calculated)
        self.assertEqual(sale_line.spa_commission_status, 'pending')

        invoice = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.partner.id,
            'invoice_line_ids': [
                (0, 0, {
                    'product_id': self.product.id,
                    'quantity': 2,
                    'price_unit': 100,
                    'sale_line_ids': [(6, 0, sale_line.ids)],
                    'spa_employee_id': self.employee.id,
                }),
            ],
        })
        invoice_line = invoice.invoice_line_ids.filtered(
            lambda line: line.product_id == self.product
        )
        self.env['spa.sales.commission'].create({
            'invoice_id': invoice_line.move_id.id,
            'invoice_line_id': invoice_line.id,
            'employee_id': self.employee.id,
        })

        self.assertTrue(sale_line.spa_commission_calculated)
        self.assertEqual(sale_line.spa_commission_status, 'applied')

    def test_invoice_product_revenue_is_grouped_by_assigned_employee(self):
        self.order.order_line.create({
            'order_id': self.order.id,
            'product_id': self.product.id,
            'product_uom_qty': 1,
            'price_unit': 50,
        })
        self.order.order_line.create({
            'order_id': self.order.id,
            'product_id': self.product.id,
            'product_uom_qty': 1,
            'price_unit': 25,
        })
        invoice = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.partner.id,
            'invoice_line_ids': [
                (0, 0, {
                    'product_id': self.product.id,
                    'quantity': 2,
                    'price_unit': 100,
                    'sale_line_ids': [(6, 0, self.order.order_line[:1].ids)],
                    'spa_employee_id': self.employee.id,
                }),
                (0, 0, {
                    'product_id': self.product.id,
                    'quantity': 1,
                    'price_unit': 50,
                    'sale_line_ids': [(6, 0, self.order.order_line[2:3].ids)],
                    'spa_employee_id': self.second_employee.id,
                }),
            ],
        })

        self.assertEqual(
            self.order._get_spa_product_revenue_by_employee(invoice),
            {
                self.employee.id: 200,
                self.second_employee.id: 50,
            },
        )

    def test_invoice_assignment_supplies_employee_after_posting(self):
        sale_line = self.order.order_line.filtered(
            lambda line: line.product_id == self.product
        )
        invoice = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.partner.id,
            'invoice_line_ids': [
                (0, 0, {
                    'product_id': self.product.id,
                    'quantity': 2,
                    'price_unit': 100,
                    'sale_line_ids': [(6, 0, sale_line.ids)],
                }),
            ],
        })
        invoice_line = invoice.invoice_line_ids.filtered(
            lambda line: line.product_id == self.product
        )
        commission = self.env['spa.sales.commission'].create({
            'invoice_id': invoice.id,
            'invoice_line_id': invoice_line.id,
            'employee_id': self.employee.id,
        })

        self.assertEqual(commission.base_amount, 200)
        self.assertEqual(
            self.order._get_spa_product_revenue_by_employee(invoice),
            {self.employee.id: 200},
        )

    def test_commission_rate_defaults_to_three_percent(self):
        rule = self.env.ref('spa.sales_commission_rule_default')
        self.assertEqual(rule.rate, 3.0)

    def test_commission_uses_order_product_revenue_and_tracks_status(self):
        commission = self.env['spa.sales.commission'].sudo().create({
            'sale_order_id': self.order.id,
            'employee_id': self.employee.id,
            'base_amount': 200,
            'rate': 3.0,
        })

        self.assertEqual(commission.commission_amount, 6)
        self.assertEqual(commission.state, 'draft')
        commission.action_approve()
        self.assertEqual(commission.state, 'approved')
        commission.action_mark_paid()
        self.assertEqual(commission.state, 'paid')
        self.assertTrue(commission.paid_date)
        with self.assertRaises(UserError):
            commission.action_cancel()

    def test_commission_status_cannot_be_changed_directly(self):
        commission = self.env['spa.sales.commission'].sudo().create({
            'sale_order_id': self.order.id,
            'employee_id': self.employee.id,
            'base_amount': 200,
            'rate': 3,
        })

        with self.assertRaises(UserError):
            commission.write({'state': 'approved'})
