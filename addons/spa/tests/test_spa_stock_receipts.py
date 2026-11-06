from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestSpaStockReceipts(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env.ref('stock.warehouse0')
        cls.vendor = cls.env['res.partner'].create({
            'name': 'Nhà cung cấp kiểm thử phiếu nhập',
            'supplier_rank': 1,
        })
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Nhân viên lập phiếu nhập kiểm thử',
        })
        cls.product = cls.env['product.template'].create({
            'name': 'Sản phẩm nhập kho kiểm thử',
            'type': 'consu',
            'is_storable': True,
            'tracking': 'lot',
            'spa_inventory_type': 'retail',
        }).product_variant_id

    def _create_receipt(
        self,
        product=None,
        lot_name='LOT-SPA-001',
        demand_quantity=5,
    ):
        today = fields.Date.context_today(self)
        return self.env['stock.picking'].create({
            'picking_type_id': self.warehouse.in_type_id.id,
            'partner_id': self.vendor.id,
            'spa_receipt_date': today,
            'spa_receipt_employee_id': self.employee.id,
            'spa_receipt_invoice_code': 'INV-SPA-001',
            'spa_receipt_total_amount': 250000,
            'note': 'Nhập hàng kiểm thử',
            'move_ids': [(0, 0, {
                'name': (product or self.product).display_name,
                'product_id': (product or self.product).id,
                'product_uom_qty': demand_quantity,
                'product_uom': (product or self.product).uom_id.id,
                'spa_lot_name': lot_name,
            })],
        })

    def test_confirm_receipt_updates_stock_and_tracks_lot(self):
        receipt = self._create_receipt()

        receipt.button_validate()

        self.assertEqual(receipt.state, 'done')
        self.assertEqual(receipt.spa_receipt_status, 'confirmed')
        self.assertEqual(receipt.spa_receipt_invoice_code, 'INV-SPA-001')
        self.assertEqual(receipt.spa_receipt_total_amount, 250000)
        self.assertEqual(
            fields.Date.to_date(receipt.scheduled_date),
            receipt.spa_receipt_date,
        )
        self.assertEqual(self.product.qty_available, 5)
        self.assertEqual(
            receipt.move_ids.move_line_ids.lot_id.name,
            'LOT-SPA-001',
        )

    def test_entered_receipt_quantity_is_used_instead_of_demand(self):
        receipt = self._create_receipt(demand_quantity=8)
        move = receipt.move_ids

        move.quantity = 3
        receipt.button_validate()

        self.assertEqual(receipt.state, 'done')
        self.assertEqual(move.quantity, 3)
        self.assertEqual(self.product.qty_available, 3)
        self.assertEqual(move.move_line_ids.lot_id.name, 'LOT-SPA-001')

    def test_cancelled_receipt_has_cancelled_status(self):
        receipt = self._create_receipt()

        receipt.action_cancel()

        self.assertEqual(receipt.state, 'cancel')
        self.assertEqual(receipt.spa_receipt_status, 'cancelled')
        self.assertEqual(self.product.qty_available, 0)

    def test_serial_receipt_requires_one_unit_per_lot(self):
        serial_product = self.env['product.template'].create({
            'name': 'Sản phẩm theo dõi số sê-ri kiểm thử',
            'type': 'consu',
            'is_storable': True,
            'tracking': 'serial',
            'spa_inventory_type': 'equipment',
        }).product_variant_id
        receipt = self._create_receipt(
            product=serial_product,
            lot_name='SERIAL-SPA-001',
        )

        with self.assertRaisesRegex(UserError, 'số lượng bằng 1'):
            receipt.button_validate()
