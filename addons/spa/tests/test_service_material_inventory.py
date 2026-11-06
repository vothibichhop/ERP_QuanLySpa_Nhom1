from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestSpaServiceMaterialInventory(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env.ref('stock.warehouse0')
        cls.work_date = fields.Date.today() + timedelta(days=10)
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Nhân viên kiểm thử định lượng kho',
        })
        cls.env['spa.work.shift'].create({
            'name': 'Ca kiểm thử định lượng kho',
            'work_date': cls.work_date,
            'employee_ids': [(6, 0, cls.employee.ids)],
        })
        cls.room = cls.env['spa.room'].create({
            'name': 'Phòng kiểm thử định lượng kho',
        })
        cls.bed = cls.env['spa.bed'].create({
            'name': 'Giường kiểm thử định lượng kho',
            'room_id': cls.room.id,
        })
        cls.customer = cls.env['res.partner'].create({
            'name': 'Khách kiểm thử định lượng kho',
        })
        cls.material = cls.env['product.template'].create({
            'name': 'Tinh dầu kiểm thử',
            'type': 'consu',
            'is_storable': True,
            'spa_inventory_type': 'service_material',
        }).product_variant_id
        cls.service = cls.env['product.template'].create({
            'name': 'Massage kiểm thử định lượng',
            'type': 'service',
            'spa_duration_minutes': 60,
            'spa_employee_ids': [(6, 0, cls.employee.ids)],
            'spa_service_material_ids': [(0, 0, {
                'product_id': cls.material.id,
                'quantity': 2,
            })],
        })

    def _create_appointment(self, **values):
        appointment_values = {
            'customer_id': self.customer.id,
            'customer_phone': '0900000000',
            'appointment_date': self.work_date,
            'start_time': 9,
            'end_time': 10,
            'employee_id': self.employee.id,
            'room_id': self.room.id,
            'bed_id': self.bed.id,
            'service_product_id': self.service.id,
            'status': 'in_progress',
        }
        appointment_values.update(values)
        return self.env['spa.appointment'].create(appointment_values)

    def _create_billing_user(self):
        return self.env['res.users'].create({
            'name': 'Người dùng thanh toán kho Spa',
            'login': 'spa_material_billing_user',
            'groups_id': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.env.ref('spa.group_customer_management_user').id,
            ])],
        })

    def test_completed_service_consumes_recipe_from_stock(self):
        self.env['stock.quant']._update_available_quantity(
            self.material,
            self.warehouse.lot_stock_id,
            20,
        )
        appointment = self._create_appointment(guest_count=2)
        billing_user = self._create_billing_user()

        action = appointment.with_user(billing_user).action_done()
        wizard = self.env[
            'spa.material.consumption.wizard'
        ].with_user(billing_user).browse(action['res_id'])

        self.assertEqual(wizard.line_ids.planned_quantity, 4)
        self.assertEqual(wizard.line_ids.quantity, 4)

        wizard.action_confirm()

        self.assertEqual(self.material.qty_available, 16)
        self.assertEqual(appointment.status, 'done')
        self.assertEqual(len(appointment.spa_material_picking_ids), 1)
        picking = appointment.spa_material_picking_ids
        self.assertEqual(picking.state, 'done')
        self.assertEqual(picking.move_ids.product_uom_qty, 4)
        self.assertEqual(picking.move_ids.quantity, 4)

    def test_completed_service_consumes_multiple_materials_from_stock(self):
        second_material = self.env['product.template'].create({
            'name': 'Kem dưỡng kiểm thử',
            'type': 'consu',
            'is_storable': True,
            'spa_inventory_type': 'service_material',
        }).product_variant_id
        self.env['spa.service.material'].create({
            'service_id': self.service.id,
            'product_id': second_material.id,
            'quantity': 3,
        })
        self.env['stock.quant']._update_available_quantity(
            self.material,
            self.warehouse.lot_stock_id,
            20,
        )
        self.env['stock.quant']._update_available_quantity(
            second_material,
            self.warehouse.lot_stock_id,
            20,
        )
        appointment = self._create_appointment()
        billing_user = self._create_billing_user()

        action = appointment.with_user(billing_user).action_done()
        wizard = self.env[
            'spa.material.consumption.wizard'
        ].with_user(billing_user).browse(action['res_id'])

        self.assertEqual(len(wizard.line_ids), 2)
        wizard.action_confirm()

        picking = appointment.spa_material_picking_ids
        self.assertEqual(picking.state, 'done')
        self.assertEqual(self.material.qty_available, 18)
        self.assertEqual(second_material.qty_available, 17)
        self.assertEqual(
            set(picking.move_ids.mapped('product_id').ids),
            {self.material.id, second_material.id},
        )
        quantities_by_product = dict(zip(
            picking.move_ids.mapped('product_id').ids,
            picking.move_ids.mapped('quantity'),
        ))
        self.assertEqual(
            quantities_by_product,
            {self.material.id: 2, second_material.id: 3},
        )
        self.assertEqual(appointment.status, 'done')

    def test_combo_material_quantities_include_selected_service_recipes(self):
        combo_choices = self.env['product.combo'].create([{
            'name': 'Dịch vụ combo kiểm thử lượt 1',
            'combo_item_ids': [(0, 0, {
                'product_id': self.service.product_variant_id.id,
            })],
        }, {
            'name': 'Dịch vụ combo kiểm thử lượt 2',
            'combo_item_ids': [(0, 0, {
                'product_id': self.service.product_variant_id.id,
            })],
        }])
        combo = self.env['product.template'].create({
            'name': 'Combo kiểm thử định lượng',
            'type': 'combo',
            'combo_ids': [(6, 0, combo_choices.ids)],
            'spa_duration_minutes': 60,
        })
        self.assertIn('Tinh dầu kiểm thử: 4', combo.spa_combo_material_summary)
        appointment = self._create_appointment(
            guest_count=2,
            appointment_line_ids=[(0, 0, {
                'product_id': combo.id,
                'duration_minutes': 60,
                'combo_choice_ids': [
                    (0, 0, {
                        'combo_id': choice.id,
                        'combo_item_id': choice.combo_item_ids.id,
                    })
                    for choice in combo_choices
                ],
            })],
        )

        action = appointment.with_user(
            self._create_billing_user()
        ).action_done()
        wizard = self.env[
            'spa.material.consumption.wizard'
        ].browse(action['res_id'])

        self.assertEqual(wizard.line_ids.product_id, self.material)
        self.assertEqual(wizard.line_ids.planned_quantity, 8)
        self.assertEqual(wizard.line_ids.quantity, 8)

    def test_actual_material_quantity_can_be_adjusted_before_consumption(self):
        self.env['stock.quant']._update_available_quantity(
            self.material,
            self.warehouse.lot_stock_id,
            20,
        )
        appointment = self._create_appointment(guest_count=2)
        billing_user = self._create_billing_user()

        action = appointment.with_user(billing_user).action_done()
        wizard = self.env[
            'spa.material.consumption.wizard'
        ].with_user(billing_user).browse(action['res_id'])
        wizard.line_ids.quantity = 3

        wizard.action_confirm()

        self.assertEqual(self.material.qty_available, 17)
        self.assertEqual(appointment.status, 'done')
        self.assertEqual(appointment.spa_material_picking_ids.move_ids.quantity, 3)

    def test_service_material_consumption_rejects_insufficient_stock(self):
        self.env['stock.quant']._update_available_quantity(
            self.material,
            self.warehouse.lot_stock_id,
            1,
        )
        appointment = self._create_appointment()
        billing_user = self._create_billing_user()
        action = appointment.with_user(billing_user).action_done()
        wizard = self.env[
            'spa.material.consumption.wizard'
        ].with_user(billing_user).browse(action['res_id'])

        with self.assertRaisesRegex(UserError, 'Không đủ nguyên vật liệu'):
            wizard.action_confirm()

        self.assertEqual(self.material.qty_available, 1)
        self.assertFalse(appointment.spa_material_picking_ids)
        self.assertFalse(appointment.sale_order_id)
        self.assertEqual(appointment.status, 'in_progress')

    def test_actual_material_quantity_cannot_be_negative(self):
        action = self._create_appointment().with_user(
            self._create_billing_user()
        ).action_done()
        wizard = self.env[
            'spa.material.consumption.wizard'
        ].browse(action['res_id'])

        with self.assertRaises(ValidationError):
            wizard.line_ids.quantity = -1

    def test_service_recipe_only_accepts_service_material_products(self):
        retail_product = self.env['product.template'].create({
            'name': 'Sản phẩm bán kiểm thử',
            'type': 'consu',
            'is_storable': True,
            'spa_inventory_type': 'retail',
        }).product_variant_id

        with self.assertRaises(ValidationError):
            self.env['spa.service.material'].create({
                'service_id': self.service.id,
                'product_id': retail_product.id,
                'quantity': 1,
            })

    def test_inventory_material_expiration_date_can_be_set(self):
        self.material.product_tmpl_id.spa_expiration_date = fields.Date.from_string(
            '2027-12-31'
        )

        self.assertEqual(
            self.material.product_tmpl_id.spa_expiration_date,
            fields.Date.from_string('2027-12-31'),
        )

    def test_inventory_status_warns_at_ten_or_less(self):
        self.env['stock.quant']._update_available_quantity(
            self.material,
            self.warehouse.lot_stock_id,
            10,
        )

        self.assertEqual(self.material.product_tmpl_id.spa_stock_status, 'low')

        equipment = self.env['product.template'].create({
            'name': 'Máy móc kiểm thử',
            'type': 'consu',
            'is_storable': True,
            'spa_inventory_type': 'equipment',
        })
        self.env['stock.quant']._update_available_quantity(
            equipment.product_variant_id,
            self.warehouse.lot_stock_id,
            10,
        )
        self.assertEqual(equipment.spa_stock_status, 'available')

        self.env['stock.quant']._update_available_quantity(
            self.material,
            self.warehouse.lot_stock_id,
            -10,
        )
        self.assertEqual(
            self.material.product_tmpl_id.spa_stock_status,
            'out_of_stock',
        )

    def test_inventory_status_updates_when_type_changes(self):
        equipment = self.env['product.template'].create({
            'name': 'Máy móc đổi loại kiểm thử',
            'type': 'consu',
            'is_storable': True,
            'spa_inventory_type': 'equipment',
        })
        self.env['stock.quant']._update_available_quantity(
            equipment.product_variant_id,
            self.warehouse.lot_stock_id,
            10,
        )

        self.assertEqual(equipment.spa_stock_status, 'available')

        equipment.spa_inventory_type = 'retail'

        self.assertEqual(equipment.spa_stock_status, 'low')
