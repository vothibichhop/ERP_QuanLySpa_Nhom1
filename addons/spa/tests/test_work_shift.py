from datetime import time

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestSpaWorkShift(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Nhân viên ca trực',
        })
        cls.guard = cls.env['hr.employee'].create({
            'name': 'Bảo vệ ca trực',
            'job_id': cls.env.ref('spa.job_spa_security').id,
        })

    def _create_shift(self, **values):
        work_date = fields.Date.context_today(self.env.user)
        shift_values = {
            'name': 'Ca sáng',
            'employee_ids': [(4, self.employee.id)],
            'work_date': work_date,
        }
        shift_values.update(values)
        return self.env['spa.work.shift'].create(shift_values)

    def test_shift_rejects_non_full_day_hours(self):
        work_date = fields.Date.context_today(self.env.user)
        with self.assertRaises(ValidationError):
            self._create_shift(
                start_datetime=self.env['spa.work.shift']._shift_datetime(
                    work_date, time(8),
                ),
            )

    def test_employee_cannot_have_overlapping_shifts(self):
        shift = self._create_shift()
        with self.assertRaises(ValidationError):
            self._create_shift(
                name='Ca trùng',
                work_date=shift.work_date,
            )

    def test_employee_cannot_be_scheduled_during_leave(self):
        work_date = fields.Date.context_today(self.env.user)
        leave = self.env['spa.leave.request'].create({
            'employee_id': self.employee.id,
            'start_date': work_date,
            'end_date': work_date,
        })
        leave.action_submit()

        with self.assertRaises(ValidationError):
            self._create_shift()

    def test_cancelled_overlaps_are_allowed(self):
        shift = self._create_shift()
        self._create_shift(
            name='Ca thay thế',
            state='cancelled',
        )

        self.assertEqual(len(self.employee.shift_ids), 2)
        self.assertEqual(shift.shift_type, 'full_day')
        self.assertEqual(shift.work_date, fields.Date.context_today(self.env.user))

    def test_daily_guard_schedule_is_generated_once(self):
        shifts = self.env['spa.work.shift']
        shifts._cron_create_daily_guard_shift()
        shifts._cron_create_daily_guard_shift()

        guard_shift = shifts.search([
            ('auto_generated', '=', True),
            ('work_date', '=', fields.Date.context_today(self.env.user)),
        ])
        expected_guards = self.env['hr.employee'].search([
            ('active', '=', True),
            '|',
            ('job_title', 'ilike', 'bảo vệ'),
            ('job_id.name', 'ilike', 'bảo vệ'),
        ])
        self.assertEqual(len(guard_shift), 1)
        self.assertEqual(guard_shift.employee_ids, expected_guards)
        self.assertEqual(guard_shift.shift_type, 'full_day')
