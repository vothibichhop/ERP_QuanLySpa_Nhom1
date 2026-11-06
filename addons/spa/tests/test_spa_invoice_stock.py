from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestSpaInvoiceStock(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env.ref('stock.warehouse0')
        cls.partner = cls.env['res.partner'].create({
            'name': 'Khách hàng kiểm thử xuất kho hóa đơn',
        })
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Nhân viên kiểm thử xuất kho hóa đơn',
        })
        cls.product = cls.env['product.product'].create({
            'name': 'Sản phẩm kiểm thử xuất kho hóa đơn',
            'type': 'consu',
            'is_storable': True,
            'sale_ok': True,
            'list_price': 100000,
        })

    def test_posting_sales_invoice_validates_existing_delivery(self):
        self.env['stock.quant']._update_available_quantity(
            self.product,
            self.warehouse.lot_stock_id,
            5,
        )
        order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'order_line': [(0, 0, {
                'product_id': self.product.id,
                'product_uom_qty': 2,
                'spa_employee_id': self.employee.id,
            })],
        })
        order.action_confirm()
        delivery = order.picking_ids.filtered(
            lambda picking: picking.picking_type_code == 'outgoing'
        )
        self.assertTrue(delivery)
        self.assertNotEqual(delivery.state, 'done')

        invoice = order._create_invoices()
        invoice.action_post()

        self.assertEqual(delivery.state, 'done')
        product = self.product.with_company(self.env.company)
        self.assertEqual(product.qty_available, 3)

        invoice.action_post()

        self.assertEqual(product.qty_available, 3)

    def test_confirm_payment_does_not_repost_an_existing_invoice(self):
        room = self.env['spa.room'].create({
            'name': 'Phòng kiểm thử xác nhận hóa đơn',
        })
        bed = self.env['spa.bed'].create({
            'name': 'Giường kiểm thử xác nhận hóa đơn',
            'room_id': room.id,
        })
        service = self.env['product.product'].create({
            'name': 'Dịch vụ kiểm thử hóa đơn Spa',
            'type': 'service',
            'list_price': 100000,
            'invoice_policy': 'order',
        })
        service.product_tmpl_id.spa_duration_minutes = 60
        service.product_tmpl_id.spa_employee_ids = [(6, 0, self.employee.ids)]
        appointment = self.env['spa.appointment'].create({
            'customer_id': self.partner.id,
            'appointment_date': fields.Date.today(),
            'employee_id': self.employee.id,
            'room_id': room.id,
            'bed_id': bed.id,
            'start_time': 9,
            'end_time': 10,
            'service_product_id': service.product_tmpl_id.id,
            'status': 'done',
        })
        billing_user = self.env['res.users'].create({
            'name': 'Người dùng xác nhận thanh toán kiểm thử',
            'login': 'spa_invoice_billing_test',
            'groups_id': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.env.ref('spa.group_customer_management_user').id,
            ])],
        })
        order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'spa_appointment_id': appointment.id,
            'user_id': billing_user.id,
            'order_line': [(0, 0, {
                'product_id': service.id,
                'product_uom_qty': 1,
            })],
        })
        order.action_confirm()
        invoice = order._create_invoices()
        invoice.action_post()

        action = order.with_user(
            billing_user
        ).action_spa_confirm_payment()

        self.assertEqual(invoice.state, 'posted')
        self.assertEqual(appointment.invoice_id, invoice)
        self.assertEqual(action['res_id'], invoice.id)
