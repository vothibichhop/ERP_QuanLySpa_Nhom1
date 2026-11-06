from datetime import timedelta

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


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
        cls.work_date = fields.Date.today() + timedelta(days=10)
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
        self._create_appointment(status='cancelled')
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
