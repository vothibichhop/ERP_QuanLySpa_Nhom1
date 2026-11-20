from datetime import timedelta

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import Form, TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestSpaEmployeeServices(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Nhân viên massage',
        })
        cls.other_employee = cls.env['hr.employee'].create({
            'name': 'Nhân viên chăm sóc da',
        })
        cls.work_date = fields.Date.context_today(cls.env.user) + timedelta(days=1)
        cls.env['spa.work.shift'].create({
            'name': 'Ca kỹ thuật viên kiểm thử',
            'work_date': cls.work_date,
            'employee_ids': [(6, 0, [
                cls.employee.id,
                cls.other_employee.id,
            ])],
        })
        cls.room = cls.env['spa.room'].create({
            'name': 'Phòng kiểm thử lịch hẹn',
        })
        cls.bed = cls.env['spa.bed'].create({
            'name': 'Giường kiểm thử lịch hẹn',
            'room_id': cls.room.id,
        })
        cls.second_bed = cls.env['spa.bed'].create({
            'name': 'Giường thứ hai kiểm thử lịch hẹn',
            'room_id': cls.room.id,
        })
        cls.customer = cls.env['res.partner'].create({
            'name': 'Khách kiểm thử lịch hẹn',
        })
        cls.service = cls.env['product.template'].create({
            'name': 'Dịch vụ massage kiểm thử',
            'type': 'service',
            'list_price': 100000,
            'spa_duration_minutes': 60,
            'spa_employee_ids': [(6, 0, cls.employee.ids)],
        })
        cls.group_service = cls.service.copy({
            'name': 'Dịch vụ nhóm kiểm thử',
            'spa_employee_ids': [(6, 0, (
                cls.employee | cls.other_employee
            ).ids)],
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
        }
        appointment_values.update(values)
        return self.env['spa.appointment'].create(appointment_values)

    def _create_group_appointment(self, line_values):
        return self.env['spa.appointment'].create({
            'customer_id': self.customer.id,
            'customer_phone': '0900000000',
            'appointment_date': self.work_date,
            'start_time': 9,
            'end_time': 10.5,
            'guest_count': len(line_values),
            'employee_id': False,
            'room_id': False,
            'bed_id': False,
            'appointment_line_ids': [
                fields.Command.create(values)
                for values in line_values
            ],
        })

    def test_group_services_start_together_and_use_distinct_resources(self):
        appointment = self._create_group_appointment([
            {
                'product_id': self.group_service.id,
                'duration_minutes': 60,
                'bed_id': self.bed.id,
                'employee_id': self.employee.id,
            },
            {
                'product_id': self.group_service.id,
                'duration_minutes': 90,
                'bed_id': self.second_bed.id,
                'employee_id': self.other_employee.id,
            },
        ])

        self.assertTrue(appointment.is_group_booking)
        self.assertEqual(appointment.service_duration_minutes, 90)
        self.assertEqual(appointment.end_time, 10.5)
        self.assertEqual(
            set(appointment.appointment_line_ids.mapped('bed_id').ids),
            {self.bed.id, self.second_bed.id},
        )
        self.assertEqual(
            set(appointment.appointment_line_ids.mapped('employee_id').ids),
            {self.employee.id, self.other_employee.id},
        )

    def test_group_booking_rejects_duplicate_beds_and_employees(self):
        duplicate_bed_lines = [
            {
                'product_id': self.group_service.id,
                'duration_minutes': 60,
                'bed_id': self.bed.id,
            },
            {
                'product_id': self.group_service.id,
                'duration_minutes': 60,
                'bed_id': self.bed.id,
            },
        ]
        with self.assertRaises(ValidationError):
            self._create_group_appointment(duplicate_bed_lines)

        duplicate_employee_lines = [
            {
                'product_id': self.group_service.id,
                'duration_minutes': 60,
                'bed_id': self.bed.id,
                'employee_id': self.employee.id,
            },
            {
                'product_id': self.group_service.id,
                'duration_minutes': 60,
                'bed_id': self.second_bed.id,
                'employee_id': self.employee.id,
            },
        ]
        with self.assertRaises(ValidationError):
            self._create_group_appointment(duplicate_employee_lines)

    def test_group_resources_are_unavailable_during_another_booking(self):
        self._create_group_appointment([{
            'product_id': self.group_service.id,
            'duration_minutes': 60,
            'bed_id': self.bed.id,
            'employee_id': self.employee.id,
        }, {
            'product_id': self.group_service.id,
            'duration_minutes': 60,
            'bed_id': self.second_bed.id,
            'employee_id': self.other_employee.id,
        }])
        candidate = self.env['spa.appointment'].new({
            'appointment_date': self.work_date,
            'start_time': 9.5,
            'end_time': 10.5,
            'appointment_line_ids': [fields.Command.create({
                'product_id': self.group_service.id,
                'duration_minutes': 60,
            })],
        }).appointment_line_ids

        self.assertNotIn(self.bed.id, candidate.available_bed_ids.ids)
        self.assertNotIn(
            self.employee.id,
            candidate.available_employee_ids.ids,
        )

    def test_single_appointment_form_can_select_room_and_bed(self):
        appointment_form = Form(self.env['spa.appointment'])
        appointment_form.customer_phone = '0900000000'
        appointment_form.customer_id = self.customer
        appointment_form.appointment_date = self.work_date
        appointment_form.start_time = 9
        appointment_form.end_time = 10

        with appointment_form.appointment_line_ids.new() as service_line:
            service_line.product_id = self.service
            service_line.duration_minutes = 60

        onchange_results = []
        perform_onchange = appointment_form._perform_onchange

        def capture_onchange(field_name=None):
            result = perform_onchange(field_name)
            onchange_results.append((field_name, result))
            return result

        object.__setattr__(appointment_form, '_perform_onchange', capture_onchange)
        appointment_form.room_id = self.room
        self.assertEqual(appointment_form.room_id, self.room)
        appointment_form.bed_id = self.bed
        self.assertEqual(
            appointment_form.room_id,
            self.room,
            msg=(
                f'{onchange_results!r}; '
                f'{self.env["spa.appointment"]._onchange_methods.get("bed_id")!r}'
            ),
        )
        self.assertEqual(appointment_form.bed_id, self.bed)
        appointment = appointment_form.save()

        self.assertEqual(appointment.room_id, self.room)
        self.assertEqual(appointment.bed_id, self.bed)

    def test_group_bed_selection_refreshes_sibling_bed_options(self):
        appointment_form = Form(self.env['spa.appointment'])
        appointment_form.customer_id = self.customer
        appointment_form.customer_phone = '0900000000'
        appointment_form.appointment_date = self.work_date
        appointment_form.start_time = 9
        appointment_form.end_time = 10
        appointment_form.guest_count = 2

        with appointment_form.appointment_line_ids.new() as first_line:
            first_line.product_id = self.group_service
            first_line.duration_minutes = 60
            first_line.bed_id = self.bed
            self.assertEqual(first_line.bed_id.id, self.bed.id)

        self.assertEqual(len(appointment_form.appointment_line_ids), 1)
        self.assertEqual(
            appointment_form.appointment_line_ids._records[0]['bed_id'],
            self.bed.id,
        )
        self.assertFalse(appointment_form.bed_id)
        self.assertTrue(appointment_form.is_group_booking)

        with appointment_form.appointment_line_ids.new() as second_line:
            second_line.product_id = self.group_service
            second_line.duration_minutes = 60
            self.assertNotIn(
                self.bed.id,
                second_line.available_bed_ids.ids,
            )
            second_line.bed_id = self.second_bed

    def test_group_booking_form_saves_distinct_service_employees(self):
        second_service = self.group_service.copy({
            'name': 'Dịch vụ nhóm thứ hai kiểm thử',
            'spa_employee_ids': [(6, 0, self.other_employee.ids)],
        })
        appointment_form = Form(self.env['spa.appointment'])
        appointment_form.customer_phone = '0900000000'
        appointment_form.customer_id = self.customer
        appointment_form.appointment_date = self.work_date
        appointment_form.start_time = 9
        appointment_form.end_time = 10
        appointment_form.guest_count = 2

        with appointment_form.appointment_line_ids.new() as first_line:
            first_line.product_id = self.group_service
            first_line.duration_minutes = 60
            first_line.bed_id = self.bed
            first_line.employee_id = self.env[
                'hr.employee.public'
            ].browse(self.employee.id)
            self.assertEqual(first_line.employee_id.id, self.employee.id)
        self.assertEqual(
            appointment_form.appointment_line_ids._records[0]['employee_id'],
            self.employee.id,
        )

        with appointment_form.appointment_line_ids.new() as second_line:
            second_line.product_id = second_service
            second_line.duration_minutes = 60
            second_line.bed_id = self.second_bed
            second_line.employee_id = self.env[
                'hr.employee.public'
            ].browse(self.other_employee.id)
            self.assertEqual(
                second_line.employee_id.id,
                self.other_employee.id,
            )
        self.assertEqual(
            appointment_form.appointment_line_ids._records[1]['employee_id'],
            self.other_employee.id,
        )

        appointment = appointment_form.save()

        employee_by_bed = {
            line.bed_id.id: line.employee_id.id
            for line in appointment.appointment_line_ids
        }
        self.assertEqual(employee_by_bed, {
            self.bed.id: self.employee.id,
            self.second_bed.id: self.other_employee.id,
        })

    def test_group_booking_cannot_start_until_every_service_has_an_employee(self):
        appointment = self._create_group_appointment([{
            'product_id': self.group_service.id,
            'duration_minutes': 60,
            'bed_id': self.bed.id,
        }, {
            'product_id': self.group_service.id,
            'duration_minutes': 60,
            'bed_id': self.second_bed.id,
        }])
        appointment.action_confirm()
        appointment.action_check_in()

        with self.assertRaisesRegex(ValidationError, 'từng khách'):
            appointment.action_start()

    def test_booking_can_be_saved_unassigned_but_not_staffed_early(self):
        appointment_date = (
            fields.Date.context_today(self.env.user) + timedelta(days=10)
        )
        self.env['spa.work.shift'].create({
            'name': 'Ca làm việc trong tương lai',
            'work_date': appointment_date,
            'employee_ids': [(4, self.employee.id)],
        })
        appointment = self._create_appointment(
            appointment_date=appointment_date,
            employee_id=False,
        )

        self.assertFalse(appointment.employee_id)
        self.assertFalse(appointment.can_assign_employees)
        with self.assertRaisesRegex(ValidationError, 'ngày trước lịch hẹn'):
            appointment.write({'employee_id': self.employee.id})

    def test_service_employee_is_assigned_the_day_before_and_required_to_start(self):
        appointment = self.env['spa.appointment'].create({
            'customer_id': self.customer.id,
            'customer_phone': '0900000000',
            'appointment_date': self.work_date,
            'start_time': 9,
            'end_time': 10,
            'room_id': self.room.id,
            'bed_id': self.bed.id,
            'appointment_line_ids': [fields.Command.create({
                'product_id': self.service.id,
                'duration_minutes': 60,
            })],
        })

        self.assertTrue(appointment.can_assign_employees)
        self.assertFalse(appointment.employee_id)
        appointment.action_confirm()
        appointment.action_check_in()
        with self.assertRaisesRegex(ValidationError, 'phân công nhân viên'):
            appointment.action_start()

        appointment.appointment_line_ids.employee_id = self.employee.id
        appointment.action_start()

        self.assertEqual(appointment.status, 'in_progress')

    def test_confirmed_appointment_can_be_rescheduled(self):
        appointment = self._create_appointment(
            employee_id=False,
            appointment_line_ids=[fields.Command.create({
                'product_id': self.service.id,
                'duration_minutes': 60,
                'employee_id': self.employee.id,
            })],
        )
        appointment.action_confirm()
        rescheduled_date = self.work_date + timedelta(days=10)
        self.env['spa.work.shift'].create({
            'name': 'Ca sau khi đổi lịch',
            'work_date': rescheduled_date,
            'employee_ids': [(4, self.employee.id)],
        })

        appointment.write({'appointment_date': rescheduled_date})

        self.assertEqual(appointment.appointment_date, rescheduled_date)
        self.assertEqual(appointment.status, 'confirmed')

    def test_service_employee_cannot_be_assigned_before_the_day_before(self):
        appointment_date = (
            fields.Date.context_today(self.env.user) + timedelta(days=10)
        )
        self.env['spa.work.shift'].create({
            'name': 'Ca làm việc cho lịch xa',
            'work_date': appointment_date,
            'employee_ids': [(4, self.employee.id)],
        })
        appointment = self.env['spa.appointment'].create({
            'customer_id': self.customer.id,
            'customer_phone': '0900000000',
            'appointment_date': appointment_date,
            'start_time': 9,
            'end_time': 10,
            'room_id': self.room.id,
            'bed_id': self.bed.id,
            'appointment_line_ids': [fields.Command.create({
                'product_id': self.service.id,
                'duration_minutes': 60,
            })],
        })

        with self.assertRaisesRegex(ValidationError, 'ngày trước lịch hẹn'):
            appointment.appointment_line_ids.employee_id = self.employee.id

    def test_service_assignment_is_available_from_employee(self):
        self.assertIn(self.service, self.employee.spa_service_ids)

    def test_service_line_offers_only_qualified_employees_with_a_shift(self):
        appointment = self.env['spa.appointment'].new({
            'appointment_date': self.work_date,
            'start_time': 9,
            'end_time': 10,
            'appointment_line_ids': [fields.Command.create({
                'product_id': self.service.id,
                'duration_minutes': 60,
            })],
        })
        service_line = appointment.appointment_line_ids

        self.assertIn(self.employee.id, service_line.available_employee_ids.ids)
        self.assertNotIn(
            self.other_employee.id,
            service_line.available_employee_ids.ids,
        )

    def test_order_line_values_record_the_performing_employee(self):
        order_line_values = self.env['spa.appointment']._prepare_order_line(
            self.service,
            employee=self.employee,
        )

        self.assertEqual(order_line_values['spa_employee_id'], self.employee.id)

    def test_service_line_employee_is_counted_as_busy_for_other_appointments(self):
        unassigned_service = self.service.copy({
            'name': 'Dịch vụ chưa phân công kỹ thuật viên',
            'spa_employee_ids': [(5, 0, 0)],
        })
        self._create_appointment(
            employee_id=self.other_employee.id,
            service_product_id=False,
            appointment_line_ids=[fields.Command.create({
                'product_id': unassigned_service.id,
                'duration_minutes': 60,
                'employee_id': self.employee.id,
            })],
        )
        appointment = self.env['spa.appointment'].new({
            'appointment_date': self.work_date,
            'start_time': 9.5,
            'end_time': 10.5,
            'appointment_line_ids': [fields.Command.create({
                'product_id': unassigned_service.id,
                'duration_minutes': 60,
            })],
        })

        self.assertNotIn(
            self.employee.id,
            appointment.appointment_line_ids.available_employee_ids.ids,
        )

    def test_spa_user_can_read_service_assignments(self):
        user = self.env['res.users'].create({
            'name': 'Nhân viên Spa kiểm thử',
            'login': 'spa_employee_services_user',
            'groups_id': [(6, 0, [
                self.env.ref('spa.group_customer_management_user').id,
            ])],
        })

        self.assertEqual(
            self.service.with_user(user).spa_employee_ids.ids,
            self.employee.ids,
        )

    def test_appointment_employee_options_follow_service_assignments(self):
        appointment = self.env['spa.appointment'].new({
            'service_product_id': self.service.id,
            'appointment_date': self.work_date,
        })

        self.assertEqual(
            appointment.available_employee_ids.ids,
            self.employee.ids,
        )

    def test_unassigned_service_only_offers_employees_with_a_shift(self):
        service = self.service.copy({
            'name': 'Dịch vụ chưa phân công kiểm thử',
            'spa_employee_ids': [(5, 0, 0)],
        })
        appointment = self.env['spa.appointment'].new({
            'service_product_id': service.id,
            'appointment_date': self.work_date,
        })

        self.assertEqual(
            set(appointment.available_employee_ids.ids),
            set(self.employee.ids + self.other_employee.ids),
        )

    def test_appointment_rejects_an_employee_not_assigned_to_service(self):
        appointment = self.env['spa.appointment'].new({
            'employee_id': self.other_employee.id,
            'service_product_id': self.service.id,
            'appointment_date': fields.Date.context_today(self.env.user),
        })

        with self.assertRaises(ValidationError):
            appointment._check_employee_service_eligibility()

    def test_appointment_rejects_an_employee_without_a_shift_on_that_date(self):
        employee_without_shift = self.env['hr.employee'].create({
            'name': 'Nhân viên không có ca',
        })
        self.env['spa.work.shift'].create({
            'name': 'Ca ngày khác',
            'work_date': self.work_date - timedelta(days=1),
            'employee_ids': [(4, employee_without_shift.id)],
        })
        unassigned_service = self.service.copy({
            'name': 'Dịch vụ chưa phân công nhân viên',
            'spa_employee_ids': [(5, 0, 0)],
        })
        appointment = self.env['spa.appointment'].new({
            'employee_id': employee_without_shift.id,
            'appointment_date': self.work_date,
            'service_product_id': unassigned_service.id,
        })

        self.assertNotIn(
            employee_without_shift.id,
            appointment.available_employee_ids.ids,
        )
        with self.assertRaises(ValidationError):
            appointment._check_employee_work_shift()

    def test_employee_with_pending_leave_is_not_available_for_appointment(self):
        leave = self.env['spa.leave.request'].create({
            'employee_id': self.employee.id,
            'start_date': self.work_date,
            'end_date': self.work_date,
        })
        leave.action_submit()
        appointment = self.env['spa.appointment'].new({
            'service_product_id': self.service.id,
            'appointment_date': self.work_date,
        })

        self.assertNotIn(
            self.employee.id,
            appointment.available_employee_ids.ids,
        )

    def test_appointment_rejects_employee_with_approved_leave(self):
        leave = self.env['spa.leave.request'].create({
            'employee_id': self.employee.id,
            'start_date': self.work_date,
            'end_date': self.work_date,
        })
        leave.action_submit()
        leave.action_approve()
        appointment = self.env['spa.appointment'].new({
            'employee_id': self.employee.id,
            'appointment_date': self.work_date,
        })

        with self.assertRaises(ValidationError):
            appointment._check_employee_work_shift()

    def test_cancelled_leave_does_not_hide_employee(self):
        leave = self.env['spa.leave.request'].create({
            'employee_id': self.employee.id,
            'start_date': self.work_date,
            'end_date': self.work_date,
        })
        leave.action_submit()
        leave.action_cancel()
        appointment = self.env['spa.appointment'].new({
            'service_product_id': self.service.id,
            'appointment_date': self.work_date,
        })

        self.assertIn(
            self.employee.id,
            appointment.available_employee_ids.ids,
        )

    def test_busy_employee_is_hidden_for_overlapping_appointment_time(self):
        self._create_appointment()
        appointment = self.env['spa.appointment'].new({
            'service_product_id': self.service.id,
            'appointment_date': self.work_date,
            'start_time': 9.5,
            'end_time': 10.5,
        })

        self.assertNotIn(
            self.employee.id,
            appointment.available_employee_ids.ids,
        )

    def test_employee_is_available_for_adjacent_appointment_time(self):
        self._create_appointment()
        appointment = self.env['spa.appointment'].new({
            'service_product_id': self.service.id,
            'appointment_date': self.work_date,
            'start_time': 10,
            'end_time': 11,
        })

        self.assertIn(
            self.employee.id,
            appointment.available_employee_ids.ids,
        )

    def test_cancelled_appointment_does_not_make_employee_busy(self):
        appointment = self._create_appointment()
        appointment.action_cancel()
        appointment = self.env['spa.appointment'].new({
            'service_product_id': self.service.id,
            'appointment_date': self.work_date,
            'start_time': 9.5,
            'end_time': 10.5,
        })

        self.assertIn(
            self.employee.id,
            appointment.available_employee_ids.ids,
        )
