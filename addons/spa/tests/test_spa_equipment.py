from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestSpaEquipment(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        product_template = cls.env['product.template'].create({
            'name': 'Thiết bị Spa kiểm thử sửa chữa',
            'type': 'consu',
            'is_storable': True,
            'spa_inventory_type': 'equipment',
        })
        cls.product = product_template.product_variant_id
        cls.asset = cls.env['spa.equipment.asset'].create({
            'product_id': cls.product.id,
            'serial_number': 'SPA-TEST-EQUIPMENT-001',
            'status': 'in_use',
        })

    def test_repair_lifecycle_restores_asset_status(self):
        repair = self.env['spa.equipment.repair'].create({
            'asset_id': self.asset.id,
            'description': 'Máy không khởi động được',
            'priority': '2',
        })
        self.assertEqual(self.asset.status, 'reported')
        self.assertEqual(repair.previous_asset_status, 'in_use')

        repair.action_mark_waiting()
        self.assertEqual(repair.state, 'waiting')
        self.assertEqual(self.asset.status, 'waiting_repair')

        repair.action_start_repair()
        self.assertEqual(repair.state, 'in_repair')
        self.assertEqual(self.asset.status, 'in_repair')

        repair.action_mark_repaired()
        self.assertEqual(repair.state, 'repaired')
        self.assertEqual(self.asset.status, 'in_use')
        self.assertTrue(repair.repaired_date)

    def test_cannot_create_another_open_repair_for_asset(self):
        self.env['spa.equipment.repair'].create({
            'asset_id': self.asset.id,
            'description': 'Sự cố thứ nhất',
        })

        with self.assertRaisesRegex(UserError, 'chưa được xử lý xong'):
            self.env['spa.equipment.repair'].create({
                'asset_id': self.asset.id,
                'description': 'Sự cố trùng',
            })

    def test_cancelling_repair_restores_previous_asset_status(self):
        repair = self.env['spa.equipment.repair'].create({
            'asset_id': self.asset.id,
            'description': 'Báo nhầm sự cố',
        })

        repair.action_cancel()

        self.assertEqual(repair.state, 'cancelled')
        self.assertEqual(self.asset.status, 'in_use')

    def test_equipment_and_repair_states_cannot_be_changed_directly(self):
        repair = self.env['spa.equipment.repair'].create({
            'asset_id': self.asset.id,
            'description': 'Kiểm tra bảo vệ trạng thái',
        })

        with self.assertRaisesRegex(UserError, 'bằng các nút xử lý'):
            self.asset.write({'status': 'available'})
        with self.assertRaisesRegex(UserError, 'Không thể sửa trực tiếp'):
            repair.write({'state': 'repaired'})

    def test_scrapping_repair_marks_asset_as_scrapped(self):
        repair = self.env['spa.equipment.repair'].create({
            'asset_id': self.asset.id,
            'description': 'Hỏng không thể sửa',
        })

        repair.action_scrap()

        self.assertEqual(repair.state, 'scrapped')
        self.assertEqual(self.asset.status, 'scrapped')
        with self.assertRaisesRegex(UserError, 'đã thanh lý'):
            self.env['spa.equipment.repair'].create({
                'asset_id': self.asset.id,
                'description': 'Không thể báo lại sau thanh lý',
            })

    def test_equipment_assets_require_equipment_products(self):
        product_template = self.env['product.template'].create({
            'name': 'Sản phẩm bán lẻ không phải thiết bị',
            'type': 'consu',
            'is_storable': True,
            'spa_inventory_type': 'retail',
        })

        with self.assertRaises(ValidationError):
            self.env['spa.equipment.asset'].create({
                'product_id': product_template.product_variant_id.id,
            })

    def test_breakdown_report_can_be_submitted_for_catalog_equipment(self):
        report = self.env['spa.equipment.breakdown.report'].create({
            'product_id': self.product.id,
            'description': 'Máy không khởi động được',
            'priority': '2',
        })

        self.assertEqual(report.state, 'draft')
        with self.assertRaisesRegex(UserError, 'bằng nút Gửi phiếu'):
            report.write({'state': 'submitted'})

        action = report.action_submit()

        self.assertEqual(report.state, 'submitted')
        self.assertEqual(report.product_id, self.product)
        self.assertEqual(action['res_model'], 'spa.equipment.breakdown.report')

    def test_breakdown_report_cannot_be_created_as_submitted(self):
        with self.assertRaisesRegex(UserError, 'mới phải ở trạng thái chưa gửi'):
            self.env['spa.equipment.breakdown.report'].create({
                'product_id': self.product.id,
                'description': 'Máy không khởi động được',
                'state': 'submitted',
            })

    def test_breakdown_report_rejects_non_equipment_catalog_products(self):
        product_template = self.env['product.template'].create({
            'name': 'Sản phẩm bán lẻ không phải thiết bị',
            'type': 'consu',
            'is_storable': True,
            'spa_inventory_type': 'retail',
        })

        with self.assertRaises(ValidationError):
            self.env['spa.equipment.breakdown.report'].create({
                'product_id': product_template.product_variant_id.id,
                'description': 'Không được báo hỏng sản phẩm bán',
            })
